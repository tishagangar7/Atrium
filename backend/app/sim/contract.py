"""The A → B/C simulator contract frozen at G0 (PRD §12.2), plus the belief-view and route value types.

`app.sim.service.SimulatorService` implements it; `app.agents.sim_stub.StubSim` is the fast test double. Consumers
(actors' tools, router delivery services, commit gate, baselines, run controller) depend only on this module.

`BeliefView.world` is a plain dict (the serialized `WorldState` plus `nodes`, `horizon`, `scenario_id`, `targets` and
derived per-entity values) so prompts and tools can be built from it without importing simulator internals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.models import AgentId, Assignment, AssignmentDraft, EvalBasis, Evaluation, Evidence, Violation

HORIZON = 60
ViewAgent = Literal["EVAC", "FIRE", "LOG", "union", "authoritative"]


@dataclass
class BeliefView:
    """Immutable-by-convention masked copy of the world (§5.9). Tools compute on this, never on the authority."""

    agent: ViewAgent
    world: dict[str, Any]
    held_evidence: list[Evidence]
    state_version: int
    step: int

    @property
    def basis(self) -> EvalBasis:
        if self.agent == "authoritative":
            return "authoritative"
        if self.agent == "union":
            return "union"
        return f"view_{self.agent}"  # type: ignore[return-value]


@dataclass
class Route:
    route_ids: list[str]
    nodes: list[str]
    travel_steps: int


class SimService(Protocol):
    """reset, step, apply_event, find_routes, validate_plan, evaluate_plan, build_belief_view (+ runtime helpers)."""

    def reset(self, scenario_id: str, seed: int, run_id: str) -> dict[str, Any]: ...
    def step(self, n: int = 1) -> dict[str, Any]: ...
    def apply_event(self, event: dict[str, Any]) -> int: ...
    def build_belief_view(self, agent: ViewAgent) -> BeliefView: ...
    def find_routes(self, view: BeliefView, origin: str, destination: str, *, resource_id: str) -> list[Route]: ...
    def validate_plan(self, view: BeliefView, assignments: list[AssignmentDraft]) -> list[Violation]: ...
    def evaluate_plan(self, view: BeliefView, assignments: list[AssignmentDraft], *, plan_hash: str,
                      horizon: int = HORIZON, seed: int | None = None) -> Evaluation: ...
    def plan_timing(self, view: BeliefView, assignments: list[AssignmentDraft], *,
                    current_step: int | None = None) -> list[dict[str, int]]:
        """Per assignment `{start_step, end_step, wait_steps}` (§7.6 'computed by runtime'), used by §6.7
        normalization. `start_step=None` resolves to the resource's previous end or the current step."""
        ...
    def apply_accepted_plan(self, assignments: list[Assignment], plan_hash: str) -> int:
        """Called only by the commit gate (§6.2), under the run lock (§4.3). Increments and returns state_version."""
        ...
    def disclose(self, evidence_id: str, to: AgentId) -> None:
        """Router hook (§4.3): the recipient's view shows the true value from now on."""
        ...
