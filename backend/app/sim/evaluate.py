"""Counterfactual evaluation (PRD §5.10, §7.6; FR-011, AC-022, D-15).

1. Deep-copy the view's world — never the authoritative object.
2. Expand the assignments into timed legs (locked legs are already prepended by the router's normalization).
3. Run the step loop from the current step to the horizon **without any scheduled or injected events**: no forecast,
   for any method, knows about disruptions that have not happened (no clairvoyance).
4. Return an `Evaluation`: metrics, violations, per-leg timing, target checks on the view's basis.

Three kinds of numbers never mix: a view forecast (basis `view_X`), the authoritative forecast (basis
`authoritative`) and realized metrics (the executed run); `kind` and `basis` say which this is.
"""

from __future__ import annotations

import copy
import time
from types import SimpleNamespace
from typing import Any

from app.models import Assignment, AssignmentDraft, Evaluation, Scenario, WorldState
from app.sim.contract import BeliefView
from app.sim.engine import Engine, leg_info_from_assignments
from app.sim.metrics import finalize, target_checks
from app.sim.validate import validate_and_expand


def evaluation_id(plan_hash: str, basis: str, state_version: int) -> str:
    return f"ev-{plan_hash[:12]}-{basis}-v{state_version}"


def evaluate_plan(scenario: Scenario, view: BeliefView, assignments: list[Assignment | AssignmentDraft], *,
                  plan_hash: str, horizon: int, seed: int, run_id: str,
                  locked: list[Assignment] | None = None) -> Evaluation:
    t0 = time.perf_counter()
    world_d: dict[str, Any] = copy.deepcopy(view.world)                       # §5.10 step 1: a clone, always
    params = scenario.fire_params
    violations, expansion = validate_and_expand(world_d, assignments, params, locked=locked, current_step=view.step)
    common = dict(evaluation_id=evaluation_id(plan_hash, view.basis, view.state_version), plan_hash=plan_hash,
                  basis=view.basis, kind="forecast", run_id=run_id, state_version=view.state_version,
                  from_step=view.step, horizon=horizon, seed=seed, leg_timing=expansion.legs, trace_ref=None)
    if violations:
        return Evaluation(valid=False, violations=violations, metrics=None, target_checks=[],
                          sim_ms=int((time.perf_counter() - t0) * 1000), **common)

    world = WorldState.model_validate(world_d)                                  # masked statics as the view believes them
    world.step = view.step
    timed = [SimpleNamespace(resource_id=a.resource_id, task=a.task, start_step=t["start_step"], end_step=t["end_step"],
                             people_count=a.people_count, zone_id=a.zone_id, shelter_id=a.shelter_id, crew_id=a.crew_id,
                             target_cells=list(a.target_cells)) for a, t in zip(assignments, expansion.timing)]
    engine = Engine(scenario, world, expansion.legs, seed=seed, leg_info=leg_info_from_assignments(timed, expansion.legs),
                    check_invariants=False)
    engine.run_to(horizon)                                                      # D-15: no events in a forecast
    engine.metrics.wait_risk_legs = expansion.wait_risk_legs
    metrics = finalize(engine.metrics, world, params=params)
    return Evaluation(valid=True, violations=[], metrics=metrics, target_checks=target_checks(metrics, scenario.targets),
                      sim_ms=int((time.perf_counter() - t0) * 1000), **common)
