"""`SimulatorService`: the A → B/C contract over the real engine (PRD §12.2, §4.3, §5.7, §5.8, §5.10).

Authoritative state lives here and is mutated by exactly three paths — `step()`, `apply_event()` and
`apply_accepted_plan()` — all meant to be called by the run controller under its lock (§4.3). Everything an agent
touches goes through a `BeliefView` (a masked copy) and `evaluate_plan` runs on a further copy (invariant 4).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from app.models import AgentId, Assignment, AssignmentDraft, Evaluation, Leg, Violation
from app.sim import beliefs, routes
from app.sim.contract import HORIZON, BeliefView, Route, ViewAgent
from app.sim.engine import Engine, LegInfo, LegKey, leg_info_from_assignments
from app.sim.evaluate import evaluate_plan as _evaluate
from app.sim.events import apply_event as _apply_event, events_at
from app.sim.metrics import finalize
from app.sim.plans import expand
from app.sim.scenario import load_scenario
from app.sim.validate import validate_plan as _validate
from app.sim.world import build_world, world_dict

LOCKABLE_TASKS = ("drive", "load", "unload", "transfer_crew")   # §5.8: contain / clear_road are interruptible


class SimulatorService:
    label = "Synthetic simulation"

    def __init__(self, scenario_id: str = "normal", seed: int = 1, run_id: str | None = None):
        self.reset(scenario_id, seed, run_id or f"run-local-{scenario_id}-s{seed}")

    # --- lifecycle (run controller) ---------------------------------------------------------------------------------

    def reset(self, scenario_id: str, seed: int, run_id: str) -> dict[str, Any]:
        self.scenario = load_scenario(scenario_id)
        self.world = build_world(self.scenario, run_id, seed)
        self.evidence = [e.model_copy(deep=True) for e in self.scenario.evidence]
        self.committed: list[Assignment] = []
        self.applied_event_ids: set[str] = set()
        self.engine = Engine(self.scenario, self.world, [], seed=seed)
        self.last_changes: list[dict[str, Any]] = []
        return world_dict(self.world, self.scenario)

    def step(self, n: int = 1) -> dict[str, Any]:
        """Execute up to `n` steps of the committed plan. A scheduled event at a step is applied first and the run
        pauses there (§5.7 phase 1); the controller renegotiates, then calls `step` again to continue."""
        self.last_changes = []
        for _ in range(n):
            if self.world.step >= self.scenario.horizon:
                self.world.paused = True
                break
            due = [e for e in events_at(self.scenario.events, self.world.step) if e.event_id not in self.applied_event_ids]
            if due:
                for ev in due:
                    self.apply_event(ev.model_dump(mode="json"))
                    self.applied_event_ids.add(ev.event_id)
                break
            self.world.paused = False
            report = self.engine.step([])
            self.last_changes += report.events
        return world_dict(self.world, self.scenario)

    def apply_event(self, event: dict[str, Any]) -> int:
        """Injected or scheduled event (§5.8, §5.11): mutates the authority, bumps `state_version`, pauses the run."""
        ev = _apply_event(self.world, event, pending_out_of_service=self.engine.pending_out_of_service)
        if ev.event_id:
            self.applied_event_ids.add(ev.event_id)
        self.world.paused = True
        self.last_changes.append({"kind": "event.applied", "data": ev.model_dump(mode="json")})
        return self.world.state_version

    def apply_accepted_plan(self, assignments: list[Assignment], plan_hash: str) -> int:
        """Called only by the commit gate (§6.2) after authoritative validation. Expands legs on the authoritative
        world, replaces the active legs (locked legs are already part of `assignments`) and bumps the version."""
        world_d = world_dict(self.world, self.scenario)
        expansion = expand(assignments, world_d, self.scenario.fire_params, current_step=self.world.step)
        timed = [SimpleNamespace(resource_id=a.resource_id, task=a.task, start_step=t["start_step"], end_step=t["end_step"],
                                 people_count=a.people_count, zone_id=a.zone_id, shelter_id=a.shelter_id, crew_id=a.crew_id,
                                 target_cells=list(a.target_cells)) for a, t in zip(assignments, expansion.timing)]
        self.committed = [a.model_copy(update={"end_step": t["end_step"], "wait_steps": t["wait_steps"],
                                               "start_step": t["start_step"]})
                          for a, t in zip(assignments, expansion.timing)]
        self.engine.legs = sorted(expansion.legs, key=lambda l: (l.start_step, l.resource_id, l.end_step))
        self.engine.leg_info = leg_info_from_assignments(timed, expansion.legs)
        self.engine.skipped.clear()
        self.engine.metrics.wait_risk_legs += expansion.wait_risk_legs
        self.world.active_legs = list(self.engine.legs)
        self.world.committed_plan_hash = plan_hash
        self.world.state_version += 1
        self.world.paused = False
        return self.world.state_version

    def locked_legs(self) -> list[Assignment]:
        """§5.8: assignments in progress at the pause (vehicle mid-edge, load/unload under way, crew boarding) are
        locked into the next decision point's plans. Crew work is interruptible and never locked."""
        t = self.world.step
        locked: list[Assignment] = []
        for a in self.committed:
            if a.task not in LOCKABLE_TASKS or not (a.start_step < t < a.end_step):
                continue
            if a.task == "drive":
                current = self._current_edge_of(a)
                if current is None:          # between edges (at a node): nothing in progress, the vehicle holds
                    continue
                a = current
            locked.append(a)
        return [a.model_copy(update={"order": i, "locked": True}) for i, a in enumerate(locked)]

    def _current_edge_of(self, a: Assignment) -> Assignment | None:
        """For a multi-edge drive interrupted mid-way, only the edge being travelled is in progress (§5.8, D-10):
        lock a one-edge drive for it instead of the whole remaining route."""
        res = self.world.resources.get(a.resource_id)
        if res is None or res.edge is None or res.edge not in a.route_ids:
            return None
        node = a.origin
        for rid in a.route_ids:
            road = self.world.roads[rid]
            nxt = road.b if road.a == node else road.a
            if rid == res.edge:
                leg = next((l for l in self.engine.legs if l.resource_id == a.resource_id and l.kind == "traverse"
                            and l.edge_id == rid and l.start_step < self.world.step <= l.end_step), None)
                if leg is None:
                    return None
                return a.model_copy(update={"origin": node, "destination": nxt, "route_ids": [rid],
                                            "start_step": leg.start_step, "end_step": leg.end_step, "wait_steps": 0})
            node = nxt
        return None

    def realized_metrics(self):
        """Metrics of the executed run so far (kind 'realized', §5.10)."""
        return finalize(self.engine.metrics, self.world, params=self.scenario.fire_params)

    def set_target_aspiration(self, agent: AgentId, metric: str, aspiration: float) -> None:
        """§6.11: a logged target revision (agent within its floor, or a human). Changes the public policy table the
        simulator's target checks read; never the physics or the world state."""
        self.scenario.targets[agent] = [t.model_copy(update={"aspiration": aspiration}) if t.metric == metric else t
                                        for t in self.scenario.targets.get(agent, [])]

    def evidence_holders(self) -> dict[str, list[AgentId]]:
        return beliefs.holders(self.evidence)

    # --- views and tools (agents, router, gate) ------------------------------------------------------------------------

    def build_belief_view(self, agent: ViewAgent) -> BeliefView:
        return beliefs.build_view(self.scenario, self.world, self.evidence, agent)

    def find_routes(self, view: BeliefView, origin: str, destination: str, *, resource_id: str) -> list[Route]:
        return routes.find_routes(view.world, origin, destination, resource_id=resource_id)

    def validate_plan(self, view: BeliefView, assignments: list[AssignmentDraft]) -> list[Violation]:
        return _validate(view.world, assignments, self.scenario.fire_params, current_step=view.step)

    def evaluate_plan(self, view: BeliefView, assignments: list[AssignmentDraft], *, plan_hash: str,
                      horizon: int = HORIZON, seed: int | None = None) -> Evaluation:
        return _evaluate(self.scenario, view, assignments, plan_hash=plan_hash, horizon=min(horizon, self.scenario.horizon),
                         seed=self.world.seed if seed is None else seed, run_id=self.world.run_id)

    def plan_timing(self, view: BeliefView, assignments: list[AssignmentDraft], *,
                    current_step: int | None = None) -> list[dict[str, int]]:
        return expand(assignments, view.world, self.scenario.fire_params,
                      current_step=view.step if current_step is None else current_step).timing

    def disclose(self, evidence_id: str, to: AgentId) -> None:
        beliefs.disclose(self.evidence, evidence_id, to)
