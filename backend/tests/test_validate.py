"""Plan validation and timing (PRD §5.4, §5.7, §7.1, FR-010; AC-017, AC-018, AC-019, AC-020, AC-021).

One minimal plan per violation code, capacity waits following the priority rule, waits never burning fuel.
"""

from __future__ import annotations

import pytest

from app.models import Assignment, AssignmentDraft
from app.sim.plans import expand
from app.sim.scenario import load_scenario
from app.sim.validate import validate_plan
from app.sim.world import build_world, world_dict


@pytest.fixture
def ctx():
    sc = load_scenario("normal")
    w = build_world(sc, "run-t", 1)
    return sc, world_dict(w, sc)


def A(resource, task, *, origin=None, dest=None, routes=(), start=0, people=None, zone=None, shelter=None, crew=None,
      cells=(), edge=None, duration=None):
    return AssignmentDraft(resource_id=resource, task=task, origin=origin, destination=dest, route_ids=list(routes),
                           start_step=start, people_count=people, zone_id=zone, shelter_id=shelter, crew_id=crew,
                           target_cells=list(cells), edge_id=edge, duration_steps=duration)


def codes(ctx, plan, **kw):
    sc, world = ctx
    return [v.code for v in validate_plan(world, plan, sc.fire_params, **kw)]


def test_valid_bus_round_trip_has_no_violations_and_expected_timing(ctx):
    sc, world = ctx
    plan = [A("B1", "drive", origin="BASE", dest="VJ", routes=("R1", "R3")),
            A("B1", "load", start=None, zone="VJ", people=30),
            A("B1", "drive", origin="VJ", dest="SS", routes=("R5",), start=None),
            A("B1", "unload", start=None, shelter="SS")]
    assert codes(ctx, plan) == []
    exp = expand(plan, world, sc.fire_params)
    assert exp.timing == [{"start_step": 0, "end_step": 5, "wait_steps": 0}, {"start_step": 5, "end_step": 7, "wait_steps": 0},
                          {"start_step": 7, "end_step": 13, "wait_steps": 0}, {"start_step": 13, "end_step": 14, "wait_steps": 0}]
    assert [(l.kind, l.edge_id, l.start_step, l.end_step) for l in exp.legs] == [
        ("traverse", "R1", 0, 3), ("traverse", "R3", 3, 5), ("load", None, 5, 7), ("traverse", "R5", 7, 13), ("unload", None, 13, 14)]
    assert exp.shelter_use == {"SS": 30}


@pytest.mark.parametrize("plan,code", [
    ([A("B9", "drive", origin="BASE", dest="VJ", routes=("R1", "R3"))], "UNKNOWN_RESOURCE"),                     # AC-020
    ([A("B1", "drive", origin="BASE", dest="PR", routes=("R1", "R2"))], "ROAD_CLOSED"),                         # AC-018
    ([A("C1", "drive", origin="FORK", dest="PASS", routes=("R2", "R8"))], "ROAD_NOT_ENGINE_CAPABLE"),           # AC-018
    ([A("B1", "drive", origin="BASE", dest="VJ", routes=("R1", "R3")), A("B1", "load", start=3, zone="VJ", people=10)],
     "RESOURCE_DOUBLE_BOOKED"),                                                                                # AC-017
    ([A("B1", "drive", origin="BASE", dest="VJ", routes=("R1", "R3")), A("B1", "load", start=None, zone="VJ", people=31)],
     "VEHICLE_OVER_CAPACITY"),                                                                                 # AC-019
    ([A("B1", "drive", origin="BASE", dest="VJ", routes=("R1", "R3")), A("B1", "load", start=None, zone="VJ", people=30),
      A("B2", "drive", origin="BASE", dest="VJ", routes=("R1", "R3")), A("B2", "load", start=None, zone="VJ", people=30),
      A("B1", "drive", origin="VJ", dest="SS", routes=("R5",), start=None), A("B1", "unload", start=None, shelter="SS"),
      A("B2", "drive", origin="VJ", dest="SS", routes=("R5",), start=None), A("B2", "unload", start=None, shelter="SS")],
     "SHELTER_OVER_CAPACITY"),                                                                                 # AC-019: SS has 30 places
    ([A("V1", "drive", origin="BASE", dest="SE", routes=("R1", "R6")), A("V1", "drive", origin="SE", dest="FORK", routes=("R6",), start=None),
      A("V1", "drive", origin="FORK", dest="SE", routes=("R6",), start=None), A("V1", "drive", origin="SE", dest="FORK", routes=("R6",), start=None),
      A("V1", "drive", origin="FORK", dest="SE", routes=("R6",), start=None)], "FUEL_INSUFFICIENT"),            # 33 > 30
    ([A("B1", "unload", shelter="SS")], "WRONG_LOCATION"),
    ([A("B1", "drive", origin="BASE", dest="PR", routes=("R3",))], "WRONG_LOCATION"),
    ([A("C1", "contain", cells=("c5_1",), duration=3)], "TARGET_TOO_INTENSE"),
    ([A("C1", "contain", cells=("c0_2",), duration=3)], "TARGET_OUT_OF_REACH"),
    ([A("V1", "drive", origin="BASE", dest="FORK", routes=("R1",)), A("V1", "transfer_crew", origin="FORK", dest="BASE",
      routes=("R1",), crew="C1", start=None)], "MIXED_PAYLOAD"),
    ([A("B1", "drive", origin="BASE", dest="VJ", routes=("R1", "R3"), start=58)], "SCHEDULE_OVERRUN"),           # AC-021
])
def test_each_violation_code_from_a_minimal_plan(ctx, plan, code):
    sc, world = ctx
    if code == "TARGET_TOO_INTENSE":
        world["cells"]["c5_1"]["intensity"] = 4                      # next to FORK (c5_2), too intense to start
    if code == "MIXED_PAYLOAD":
        world["resources"]["V1"]["aboard_people"] = {"VJ": 5}         # civilians already aboard
    found = [v.code for v in validate_plan(world, plan, sc.fire_params)]
    assert code in found, found


def test_locked_leg_changed(ctx):
    sc, world = ctx
    locked = [Assignment(order=0, locked=True, resource_id="V1", task="drive", origin="BASE", destination="FORK",
                         route_ids=["R1"], start_step=0, end_step=3, wait_steps=0, people_count=None, zone_id=None,
                         shelter_id=None, crew_id=None, target_cells=[], edge_id=None, duration_steps=None)]
    same = [A("V1", "drive", origin="BASE", dest="FORK", routes=("R1",))]
    altered = [A("V1", "drive", origin="BASE", dest="SS", routes=("R11",))]
    assert "LOCKED_LEG_CHANGED" not in codes(ctx, same, locked=locked)
    assert "LOCKED_LEG_CHANGED" in codes(ctx, altered, locked=locked)
    assert "LOCKED_LEG_CHANGED" in codes(ctx, [], locked=locked)


def test_capacity_waits_follow_priority_and_never_burn_fuel(ctx):
    """§5.7: R4 (capacity 1) — the earlier requested start enters first; the other waits at the node."""
    sc, world = ctx
    world["resources"]["B1"]["node"] = world["resources"]["B2"]["node"] = "VJ"
    plan = [A("B2", "drive", origin="VJ", dest="PR", routes=("R4",), start=0),
            A("B1", "drive", origin="VJ", dest="PR", routes=("R4",), start=0)]
    exp = expand(plan, world, sc.fire_params)
    assert exp.violations == []
    assert exp.timing[1] == {"start_step": 0, "end_step": 8, "wait_steps": 0}      # B1: lower id wins the tie
    assert exp.timing[0] == {"start_step": 0, "end_step": 16, "wait_steps": 8}     # B2 waits 8 then travels 8
    legs = {l.resource_id: l for l in exp.legs}
    assert (legs["B1"].start_step, legs["B2"].start_step) == (0, 8)
    assert exp.wait_risk_legs == 1                                                    # wait ≥ 3 counts as logistics risk
    later = [A("B1", "drive", origin="VJ", dest="PR", routes=("R4",), start=2),
             A("B2", "drive", origin="VJ", dest="PR", routes=("R4",), start=0)]
    exp2 = expand(later, world, sc.fire_params)
    assert exp2.timing[1]["wait_steps"] == 0 and exp2.timing[0]["wait_steps"] == 6  # earlier start wins over id
    # Waits do not burn fuel: B2's fuel use equals the travel steps only.
    fuel_plan = [A("B1", "drive", origin="VJ", dest="PR", routes=("R4",), start=0),
                 A("B2", "drive", origin="VJ", dest="PR", routes=("R4",), start=0)] + [
                 A("B2", "drive", origin="PR", dest="VJ", routes=("R4",), start=None)] * 4
    exp3 = expand(fuel_plan, world, sc.fire_params)
    assert "FUEL_INSUFFICIENT" not in [v.code for v in exp3.violations]              # 5 × 8 = 40 = capacity, waits free


def test_two_roads_capacity_two_admit_both(ctx):
    sc, world = ctx
    plan = [A("B1", "drive", origin="BASE", dest="FORK", routes=("R1",)), A("B2", "drive", origin="BASE", dest="FORK", routes=("R1",))]
    exp = expand(plan, world, sc.fire_params)
    assert [t["wait_steps"] for t in exp.timing] == [0, 0]


def test_clear_road_and_contain_timing(ctx):
    sc, world = ctx
    plan = [A("C1", "clear_road", edge="R2", start=0), A("C2", "contain", cells=("c4_2", "c5_1"), duration=5, start=2)]
    assert codes(ctx, plan) == []
    exp = expand(plan, world, sc.fire_params)
    assert exp.timing == [{"start_step": 0, "end_step": 6, "wait_steps": 0}, {"start_step": 2, "end_step": 7, "wait_steps": 0}]
    assert exp.contain_targets[1] == ["c4_2", "c5_1"]
    world["roads"]["R2"]["clear_progress"] = 4
    assert expand(plan, world, sc.fire_params).timing[0]["end_step"] == 2                # progress is kept (§5.8)
    assert "ROAD_CLOSED" in codes(ctx, [A("C1", "clear_road", edge="R1")])              # only CLOSED_CLEARABLE roads


def test_transfer_crew_moves_the_crew_and_makes_it_a_hand_crew(ctx):
    sc, world = ctx
    plan = [A("V1", "drive", origin="BASE", dest="FORK", routes=("R1",)),
            A("V1", "transfer_crew", origin="FORK", dest="PR", routes=("R2",), crew="C1", start=None)]
    world["roads"]["R2"]["status_override"] = "OPEN"
    exp = expand(plan, world, sc.fire_params)
    assert exp.violations == []
    assert [l.kind for l in exp.legs] == ["traverse", "board", "traverse", "drop"]
    assert exp.timing[1] == {"start_step": 3, "end_step": 8, "wait_steps": 0}       # 1 board + 3 travel + 1 drop


def test_masked_view_validates_differently(ctx):
    """FR-013 / AC-024: on a view where R2 is OPEN (public prior), the same plan is valid."""
    sc, world = ctx
    plan = [A("B1", "drive", origin="BASE", dest="PR", routes=("R1", "R2"))]
    assert "ROAD_CLOSED" in codes(ctx, plan)
    world["roads"]["R2"]["initial_status"] = "OPEN"
    assert codes(ctx, plan) == []
