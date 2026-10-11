"""Regressions for the C7 audit findings in WS-A (PRD §5.3, §5.4, §5.8, invariant 4)."""

from __future__ import annotations

import copy

from app.models import AssignmentDraft
from app.sim.plans import expand
from app.sim.service import SimulatorService


def A(resource, task, *, origin=None, dest=None, routes=(), start=None, people=None, zone=None, shelter=None,
      crew=None, cells=(), edge=None, duration=None):
    return AssignmentDraft(resource_id=resource, task=task, origin=origin, destination=dest, route_ids=list(routes),
                           start_step=start, people_count=people, zone_id=zone, shelter_id=shelter, crew_id=crew,
                           target_cells=list(cells), edge_id=edge, duration_steps=duration)


TRIP = [A("B1", "drive", origin="BASE", dest="VJ", routes=("R1", "R3"), start=0),
        A("B1", "load", zone="VJ", people=30),
        A("B1", "drive", origin="VJ", dest="SS", routes=("R5",)),
        A("B1", "unload", shelter="SS")]


def test_validate_and_evaluate_never_mutate_the_view():
    """Invariant 4: a tool call must hand the caller's view back unchanged."""
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("union")
    before = copy.deepcopy(view.world)
    assert sim.validate_plan(view, TRIP) == []
    sim.plan_timing(view, TRIP)
    sim.evaluate_plan(view, TRIP, plan_hash="h")
    assert view.world == before


def test_second_load_from_the_same_zone_still_sees_planned_pickups():
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("authoritative")
    plan = [*TRIP, A("B2", "drive", origin="BASE", dest="VJ", routes=("R1", "R3"), start=0),
            A("B2", "load", zone="VJ", people=30), A("B2", "drive", origin="VJ", dest="SS", routes=("R5",)),
            A("B2", "unload", shelter="SS")]
    exp = expand(plan, view.world, sim.scenario.fire_params)
    # VJ has 60 assisted; both buses can board 30 each, and SS (30 places) overflows on the second unload.
    assert [v.code for v in exp.violations] == ["SHELTER_OVER_CAPACITY"]


def test_road_cleared_earlier_in_the_plan_can_be_driven_after_clearing():
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("authoritative")             # R2 is CLOSED_CLEARABLE in truth
    plan = [A("C1", "clear_road", edge="R2", start=0),
            A("B1", "drive", origin="BASE", dest="FORK", routes=("R1",), start=0),
            A("B1", "drive", origin="FORK", dest="PR", routes=("R2",), start=6)]
    assert sim.validate_plan(view, plan) == []
    too_early = [plan[0], plan[1], A("B1", "drive", origin="FORK", dest="PR", routes=("R2",), start=3)]
    assert "ROAD_CLOSED" in [v.code for v in sim.validate_plan(view, too_early)]


def test_only_a_transport_can_transfer_a_crew():
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("authoritative")
    bus = [A("B1", "drive", origin="BASE", dest="FORK", routes=("R1",), start=0),
           A("B1", "transfer_crew", origin="FORK", dest="VJ", routes=("R3",), crew="C1")]
    assert "WRONG_LOCATION" in [v.code for v in sim.validate_plan(view, bus)]
    v1 = [A("V1", "drive", origin="BASE", dest="FORK", routes=("R1",), start=0),
          A("V1", "transfer_crew", origin="FORK", dest="VJ", routes=("R3",), crew="C1")]
    assert sim.validate_plan(view, v1) == []


def test_crew_driving_its_engine_takes_the_engine_along():
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("authoritative")
    plan = [A("C1", "drive", origin="FORK", dest="VJ", routes=("R3",), start=0),
            A("C1", "contain", cells=("c5_4",), duration=3)]
    assert sim.validate_plan(view, plan) == []
    sim.apply_accepted_plan([*_normalized(sim, view, plan)], "h")
    sim.step(2)
    c1 = sim.world.resources["C1"]
    assert c1.node == "VJ" and c1.engine_node == "VJ"          # an engine crew, not a hand crew


def test_vehicle_failing_with_passengers_goes_out_of_service_after_unloading():
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("authoritative")
    sim.apply_accepted_plan(_normalized(sim, view, TRIP), "h")
    sim.step(8)                                                    # loaded at VJ, on R5 to SS with 30 aboard
    sim.apply_event({"event_id": "EV-OOS", "step": 8, "kind": "resource_status", "target": "B1",
                     "value": "OUT_OF_SERVICE", "public": True})
    assert sim.world.resources["B1"].available                     # passengers aboard: not yet
    sim.step(6)
    assert sim.world.shelters["SS"].arrivals == 30
    assert not sim.world.resources["B1"].available


def test_locked_leg_is_only_the_edge_in_progress():
    """§5.8 / D-10: a vehicle mid-way through a two-edge drive locks only the edge it is on."""
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("authoritative")
    sim.apply_accepted_plan(_normalized(sim, view, TRIP), "h")
    sim.step(2)                                                    # B1 on R1 (steps 0-3)
    locked = sim.locked_legs()
    assert len(locked) == 1
    assert locked[0].route_ids == ["R1"] and locked[0].origin == "BASE" and locked[0].destination == "FORK"
    assert sim.validate_plan(sim.build_belief_view("authoritative"), locked) == []


def _normalized(sim, view, drafts):
    from app.models import Assignment
    timing = sim.plan_timing(view, drafts)
    return [Assignment(**d.model_dump() | {"order": i, "locked": False, "start_step": t["start_step"],
                                            "end_step": t["end_step"], "wait_steps": t["wait_steps"]})
            for i, (d, t) in enumerate(zip(drafts, timing))]
