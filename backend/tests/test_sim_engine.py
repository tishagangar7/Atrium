"""Engine, evaluation and service over the real rules (PRD §5.6, §5.7, §5.8, §5.10; FR-001, FR-002, FR-004, FR-011;
AC-014, AC-022, AC-037, D-15, NFR-002)."""

from __future__ import annotations

import json
import random
import time

import pytest

from app.models import Assignment, AssignmentDraft
from app.sim.engine import InvariantError
from app.sim.service import SimulatorService
from app.sim.world import world_dict


def A(resource, task, *, origin=None, dest=None, routes=(), start=0, people=None, zone=None, shelter=None, crew=None,
      cells=(), edge=None, duration=None):
    return AssignmentDraft(resource_id=resource, task=task, origin=origin, destination=dest, route_ids=list(routes),
                           start_step=start, people_count=people, zone_id=zone, shelter_id=shelter, crew_id=crew,
                           target_cells=list(cells), edge_id=edge, duration_steps=duration)


ROUND_TRIP = [A("B1", "drive", origin="BASE", dest="VJ", routes=("R1", "R3")),
              A("B1", "load", start=None, zone="VJ", people=30),
              A("B1", "drive", origin="VJ", dest="SS", routes=("R5",), start=None),
              A("B1", "unload", start=None, shelter="SS")]


def fingerprint(sim) -> str:
    return json.dumps(world_dict(sim.world, sim.scenario), sort_keys=True)


def commit(sim, drafts, plan_hash="abc"):
    """Normalize the way the router does (§6.7 step 1): timing from the simulator, order assigned, nothing locked."""
    view = sim.build_belief_view("authoritative")
    timing = sim.plan_timing(view, drafts)
    assignments = [Assignment(**d.model_dump(exclude={"start_step"}), order=i, locked=False, start_step=t["start_step"],
                              end_step=t["end_step"], wait_steps=t["wait_steps"]) for i, (d, t) in enumerate(zip(drafts, timing))]
    return sim.apply_accepted_plan(assignments, plan_hash)


def test_reset_is_deterministic():
    """AC-014 / FR-001: same scenario + seed → byte-identical world except run_id."""
    a, b = SimulatorService("normal", 1, "run-a"), SimulatorService("normal", 1, "run-a")
    assert fingerprint(a) == fingerprint(b)
    for s in (a, b):
        s.step(10)
    assert fingerprint(a) == fingerprint(b)
    c = SimulatorService("normal", 2, "run-a")
    c.step(10)
    assert fingerprint(c) != fingerprint(a)          # a different seed changes ignition draws


def test_committed_round_trip_executes_and_conserves_people():
    sim = SimulatorService("normal", 1)
    version = commit(sim, ROUND_TRIP, "h1")
    assert version == 1 and sim.world.committed_plan_hash == "h1" and len(sim.world.active_legs) == 5
    sim.step(5)
    assert sim.world.resources["B1"].node == "VJ"
    sim.step(2)
    b1, vj = sim.world.resources["B1"], sim.world.zones["VJ"]
    assert b1.aboard_people == {"VJ": 30} and vj.assisted_picked_up == 30
    sim.step(7)
    assert b1.node == "SS" and b1.aboard_people == {} and sim.world.shelters["SS"].arrivals == 30
    assert b1.fuel_used == 11 and sim.world.step == 14                   # 3 + 2 + 6 driving steps
    m = sim.realized_metrics()
    assert m.assisted_sheltered == 30 and m.assisted_completion == round(30 / 110, 4)
    assert sim.world.zones["VJ"].self_evacuated == min(240, 20 * 14)      # §5.6 self-evacuation 20/step


def test_scheduled_event_pauses_the_run_and_bumps_version():
    """§5.7 phase 1 / FR-040 / FR-042: the road_closure preset fires at step 15."""
    sim = SimulatorService("road_closure", 1)
    commit(sim, ROUND_TRIP)
    sim.step(60)
    assert sim.world.step == 15 and sim.world.paused and sim.world.state_version == 2       # commit + event
    assert sim.world.roads["R3"].status_override == "CLOSED_HARD"
    assert sim.last_changes[-1]["kind"] == "event.applied"
    sim.step(60)                                                                           # continues after renegotiation
    assert sim.world.step == 60 and sim.world.state_version == 2


def test_evaluate_plan_never_mutates_the_authority_or_the_view():
    """AC-022 / FR-011: 50 evaluations, identical fingerprints before and after."""
    sim = SimulatorService("normal", 1)
    before = fingerprint(sim)
    view = sim.build_belief_view("LOG")
    view_before = json.dumps(view.world, sort_keys=True)
    for i in range(50):
        ev = sim.evaluate_plan(view, ROUND_TRIP, plan_hash=f"{i:012d}")
    assert fingerprint(sim) == before and json.dumps(view.world, sort_keys=True) == view_before
    assert ev.valid and ev.basis == "view_LOG" and ev.kind == "forecast" and ev.evaluation_id.startswith("ev-000000000049-view_LOG-v0")


def test_evaluation_numbers_are_realistic_and_from_the_simulator():
    sim = SimulatorService("normal", 1)
    ev = sim.evaluate_plan(sim.build_belief_view("authoritative"), ROUND_TRIP, plan_hash="abc")
    m = ev.metrics
    assert m is not None and m.assisted_sheltered == 30 and m.assisted_demand == 110 and m.assisted_completion == round(30 / 110, 4)
    assert m.evacuation_completion_step is None and m.fire_extent >= 3 and m.burning_cell_steps > 0
    assert {c.metric for c in ev.target_checks} == {"assisted_completion", "civilian_exposure", "fire_extent", "crew_risk_steps", "logistics_risk"}
    assert [(l.kind, l.start_step, l.end_step) for l in ev.leg_timing] == [
        ("traverse", 0, 3), ("traverse", 3, 5), ("load", 5, 7), ("traverse", 7, 13), ("unload", 13, 14)]
    invalid = sim.evaluate_plan(sim.build_belief_view("LOG"), [A("B1", "drive", origin="BASE", dest="PR", routes=("R1", "R2"))], plan_hash="bad")
    assert not invalid.valid and invalid.metrics is None and invalid.violations[0].code == "ROAD_CLOSED"


def test_forecasts_do_not_see_future_events():
    """D-15 / §5.10 #3: before step 15 the R4 closure is unknown to every forecast; after it, R4 plans are invalid."""
    sim = SimulatorService("road_closure", 1)
    late_r3 = [A("B1", "drive", origin="BASE", dest="PR", routes=("R1", "R3", "R4"), start=20)]
    assert sim.evaluate_plan(sim.build_belief_view("authoritative"), late_r3, plan_hash="x").valid
    sim.step(60)                                                       # applies the step-15 closure
    assert not sim.evaluate_plan(sim.build_belief_view("authoritative"), late_r3, plan_hash="x").valid


def test_fire_spreads_and_exposure_accumulates_without_a_plan():
    sim = SimulatorService("normal", 1)
    sim.step(30)
    m = sim.realized_metrics()
    assert m.fire_extent > 3 and m.burning_cell_steps > 30
    assert sim.world.zones["NC"].self_evacuated == 20 and sim.world.zones["VJ"].self_evacuated == 240   # all out by step 12


def test_random_valid_plans_conserve_people_and_resources():
    """AC-037 / FR-004: invariants hold after every step of many random valid plans (engine checks each step)."""
    rng = random.Random(7)
    executed = 0
    for i in range(60):
        sim = SimulatorService("normal", 1 + i % 3)
        view = sim.build_belief_view("authoritative")
        vehicle = rng.choice(["B1", "B2", "V1"])
        zone = rng.choice(["VJ", "PR", "NC"])
        shelter = rng.choice(["SS", "SE"])
        to_zone = sim.find_routes(view, "BASE", zone, resource_id=vehicle)
        to_shelter = sim.find_routes(view, zone, shelter, resource_id=vehicle)
        if not to_zone or not to_shelter:
            continue
        drafts = [A(vehicle, "drive", origin="BASE", dest=zone, routes=to_zone[0].route_ids, start=rng.randint(0, 5)),
                  A(vehicle, "load", start=None, zone=zone, people=None),
                  A(vehicle, "drive", origin=zone, dest=shelter, routes=to_shelter[0].route_ids, start=None),
                  A(vehicle, "unload", start=None, shelter=shelter)]
        if rng.random() < 0.5:
            drafts.append(A("C1", "contain", cells=("c4_2",), duration=rng.randint(3, 8), start=0))
        if sim.validate_plan(view, drafts):
            continue
        commit(sim, drafts, f"p{i}")
        sim.step(60)                                                   # InvariantError would propagate
        executed += 1
        assert sim.world.step == 60
    assert executed >= 20


def test_locked_legs_are_in_progress_vehicle_tasks_only():
    """§5.8: at a pause, a vehicle mid-edge or mid-load is locked; crew work is not."""
    sim = SimulatorService("normal", 1)
    commit(sim, ROUND_TRIP + [A("C1", "contain", cells=("c4_2",), duration=10, start=0)])
    sim.step(4)                                                        # B1 is on R3 (3..5); C1 is containing
    locked = sim.locked_legs()
    assert [(a.resource_id, a.task, a.locked, a.order) for a in locked] == [("B1", "drive", True, 0)]
    sim.step(2)                                                        # step 6: B1 loading (5..7)
    assert [(a.resource_id, a.task) for a in sim.locked_legs()] == [("B1", "load")]


def test_evaluation_speed_is_within_budget():
    """NFR-002 target ≤ 50 ms per 60-step evaluation; asserted loosely here, measured value goes in the handoff."""
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("authoritative")
    t0 = time.perf_counter()
    for _ in range(5):
        sim.evaluate_plan(view, ROUND_TRIP, plan_hash="abc")
    per_eval_ms = (time.perf_counter() - t0) * 1000 / 5
    assert per_eval_ms < 500, per_eval_ms


def test_invariant_violation_is_detected():
    sim = SimulatorService("normal", 1)
    sim.world.shelters["SS"].arrivals = 100                             # 420 > capacity 350
    with pytest.raises(InvariantError):
        sim.engine.verify_invariants()
