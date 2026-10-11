"""Wires Ali's (WS-B) `NegotiationService` into Tisha's (WS-C) HTTP/SSE layer for queue item
C4 (PRD §12.3). Owner: Tisha / WS-C -- this file only ever calls into `app.agents`/
`app.negotiation`'s PUBLIC classes (`Actor`, `StubSim`, `NegotiationService`); it never edits
them (Ali's exclusive scope, AGENTS.md §2).

**Scope decision:** negotiation runs against its own `StubSim`, decoupled from
`RunController`'s live-run world. `StubSim`'s world does not match `app.models.WorldState`
(its `Cell` entries have no `x`/`y`/`state`/`intensity`/`ignited_step`, it has no
`metrics_so_far`, and it ignores whatever `scenario_id` is passed to `reset()` -- one fixed
internal map regardless). This is a real, previously-unreviewed gap between WS-B's stub and
WS-C's contracts (G0 only reviewed §7.5-7.7 agent/message fields, not §7.2 world fields --
nobody's fault, just nobody's job yet since world fields are nominally Madhav's). Padding
fake `x`/`y`/`intensity` values onto `StubSim`'s world to force it into `WorldState` would be
its own kind of fabrication -- inventing fire/position data that isn't there. So `GET /state`
keeps showing `RunController`'s own stub world unchanged; a negotiation session's state only
surfaces through its own envelopes (via `sink`) and `GET /proposals`. Revisit once Madhav's
real `app.sim` gives everyone the same world representation.

No live model credentials exist anywhere (OPEN-05). Running this for real means the labeled
TEST PROVIDER (`RESCUEMESH_TEST=1`, `RESCUEMESH_PROVIDER=fake`) with a hand-written script --
exactly how Ali's own 150 protocol tests work -- never presented as live output (AGENTS.md
invariant 8, AC-026).
"""

from __future__ import annotations

from typing import Callable

from app.agents import contracts as b
from app.agents.actor import Actor, ActorState
from app.agents.prompt import DEFAULT_TARGETS
from app.agents.provider import Provider, ProviderError, Settings, get_provider
from app.agents.sim_stub import StubSim
from app.sim.service import SimulatorService
from app.sim.contract import BeliefView
from app.models import Assignment as SimAssignment, AssignmentDraft as SimDraft
from app.negotiation.router import RouterEvent, RouterSettings
from app.negotiation.service import NegotiationService

AGENT_IDS = ("EVAC", "FIRE", "LOG")


class ContractBridge:
    """Convert the two existing Pydantic contract families at the WS-C boundary.

    Both describe PRD §7, but Pydantic treats their nested model classes as distinct.
    The authoritative simulator remains the sole owner of physics and state.
    """

    def __init__(self, simulator: SimulatorService):
        self.authority = simulator

    @property
    def world(self):
        return self.authority.world

    def build_belief_view(self, agent):
        view = self.authority.build_belief_view(agent)
        return BeliefView(agent=view.agent, world=view.world,
                          held_evidence=[b.Evidence.model_validate(e.model_dump()) for e in view.held_evidence],
                          state_version=view.state_version, step=view.step)

    def find_routes(self, view, origin, destination, *, resource_id):
        return self.authority.find_routes(view, origin, destination, resource_id=resource_id)

    def validate_plan(self, view, assignments):
        violations = self.authority.validate_plan(
            view, [SimDraft.model_validate(a.model_dump()) for a in assignments])
        return [b.Violation.model_validate(v.model_dump()) for v in violations]

    def evaluate_plan(self, view, assignments, *, plan_hash, horizon=60, seed=None):
        evaluation = self.authority.evaluate_plan(
            view, [SimDraft.model_validate(a.model_dump()) for a in assignments],
            plan_hash=plan_hash, horizon=horizon, seed=seed)
        return b.Evaluation.model_validate(evaluation.model_dump(mode="json"))

    def plan_timing(self, view, assignments, *, current_step=None):
        return self.authority.plan_timing(
            view, [SimDraft.model_validate(a.model_dump()) for a in assignments],
            current_step=current_step)

    def apply_accepted_plan(self, assignments, plan_hash):
        return self.authority.apply_accepted_plan(
            [SimAssignment.model_validate(a.model_dump()) for a in assignments], plan_hash)

    def disclose(self, evidence_id, to):
        self.authority.disclose(evidence_id, to)

# §5.11 names the composite disruption events; the real catalog (which cells/roads they touch
# per scenario) is Madhav's (scenarios/**, not yet built). This is a minimal, explicitly
# stand-in mapping onto StubSim's own 3 primitive event kinds (road_status/wind_change/
# resource_status) and its fixed R2/B1 identifiers, only so the /events/inject wiring is
# provable now -- not a claim about real disruption physics.
INJECT_EVENT_CATALOG: dict[str, list[dict]] = {
    "wind_shift": [{"kind": "wind_change", "target": None, "value": "W:3"}],
    "road_closure": [{"kind": "road_status", "target": "R2", "value": "CLOSED_HARD"}],
    "wind_shift_road_closure": [
        {"kind": "wind_change", "target": None, "value": "W:3"},
        {"kind": "road_status", "target": "R2", "value": "CLOSED_HARD"},
    ],
    "compound_failure": [
        {"kind": "wind_change", "target": None, "value": "W:3"},
        {"kind": "road_status", "target": "R2", "value": "CLOSED_HARD"},
        {"kind": "resource_status", "target": "B1", "value": "OUT_OF_SERVICE"},
    ],
}


class NegotiationSession:
    """One per active run_id. Built lazily on the first negotiation-family HTTP call for that
    run, discarded on the next `reset()` (see `app.main`'s session dict)."""

    def __init__(
        self,
        run_id: str,
        scenario_id: str,
        *,
        on_envelope: Callable[[str, str, dict], None],
        simulator: SimulatorService | None = None,
        script: dict | None = None,
        mode: str = "live",
        delay_s: float = 0.0,
    ):
        settings = Settings.from_env()
        # `delay_s` is real wall-clock per-call delay on the TEST PROVIDER (provider_fake.py) --
        # harmless no-op on live providers (absorbed and ignored). Lets tests reliably exercise
        # the "negotiation already in progress" 409 path without a scheduling race.
        provider: Provider = get_provider(settings, script=script, delay_s=delay_s)

        self.run_id = run_id
        self.sim = ContractBridge(simulator) if simulator else StubSim(scenario_id=scenario_id, run_id=run_id)
        targets = ({agent: [b.Target.model_validate(t.model_dump()) for t in rows]
                    for agent, rows in simulator.scenario.targets.items()}
                   if simulator else DEFAULT_TARGETS)
        self.actors = {
            a: Actor(ActorState(agent_id=a, targets=targets), provider, self.sim)
            for a in AGENT_IDS
        }
        self._on_envelope = on_envelope
        self.service = NegotiationService(
            self.actors, self.sim, run_id=run_id, scenario_id=scenario_id,
            sink=self._sink, settings=RouterSettings(turn_deadline_s=settings.turn_deadline_s),
            mode=mode, targets=targets,
        )

    def _sink(self, event: RouterEvent) -> None:
        self._on_envelope(self.run_id, event.type, {
            "dp_id": event.dp_id,
            "round": event.round,
            "state_version": event.state_version,
            "agent": event.agent,
            **event.data,
        })

    def apply_inject_event(self, event_name: str) -> int:
        """Raises `KeyError` for an unrecognized name -- caller maps that to 422/404."""
        primitives = INJECT_EVENT_CATALOG[event_name]
        new_version = self.sim.world["state_version"]
        for primitive in primitives:
            new_version = self.sim.apply_event(primitive)
        return new_version
