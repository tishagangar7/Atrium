"""Simulator stub used by WS-B until app.sim lands: belief masking, structural validation, no mutation.

Pins AC-024 (tools use the caller's belief view), AC-022 (evaluation is mutation-free) and the violation codes
the stub can produce (AC-017, AC-018, AC-020, AC-021). Physics is Madhav's and is not tested here.
"""

from __future__ import annotations

from app.agents.contracts import AssignmentDraft
from app.agents.sim_stub import LABEL, StubSim, world_fingerprint


def drive(resource: str, origin: str, dest: str, roads: list[str], start: int | None = 0) -> AssignmentDraft:
    return AssignmentDraft(resource_id=resource, task="drive", origin=origin, destination=dest, route_ids=roads,
                           start_step=start, people_count=None, zone_id=None, shelter_id=None, crew_id=None,
                           target_cells=[], edge_id=None, duration_steps=None)


def task(resource: str, kind: str, start: int | None, **kw) -> AssignmentDraft:
    base = dict(resource_id=resource, task=kind, origin=None, destination=None, route_ids=[], start_step=start,
                people_count=None, zone_id=None, shelter_id=None, crew_id=None, target_cells=[], edge_id=None,
                duration_steps=None)
    base.update(kw)
    return AssignmentDraft(**base)


def test_stub_is_labeled():
    assert "STUB" in LABEL and StubSim().label == LABEL


def test_belief_view_masks_unheld_statics_and_keeps_held():
    """§5.9: un-held items show the public prior; held items show the truth; no hint that a mask exists."""
    sim = StubSim()
    evac, log, fire = (sim.build_belief_view(a) for a in ("EVAC", "LOG", "FIRE"))
    assert evac.world["roads"]["R2"]["initial_status"] == "OPEN"
    assert log.world["roads"]["R2"]["initial_status"] == "CLOSED_CLEARABLE"
    assert evac.world["zones"]["PR"]["assisted_initial"] == 30 and log.world["zones"]["PR"]["assisted_initial"] == 12
    assert fire.world["cells"]["c1_1"]["fuel_initial"] == 0.9 and evac.world["cells"]["c1_1"]["fuel_initial"] == 0.5
    assert fire.world["cells"]["c2_1"]["firebreak_bonus"] is True and log.world["cells"]["c2_1"]["firebreak_bonus"] is False
    assert {e.evidence_id for e in log.held_evidence} == {"E-LOG-01", "E-LOG-02"}
    assert len(sim.build_belief_view("union").held_evidence) == 7   # baselines see everything (§5.9)
    assert sim.build_belief_view("authoritative").world["roads"]["R2"]["initial_status"] == "CLOSED_CLEARABLE"


def test_find_routes_uses_callers_view():
    """AC-024 / FR-013: Evacuation's find_routes returns R2 while its closure is undisclosed; Logistics' does not."""
    sim = StubSim()
    evac_routes = sim.find_routes(sim.build_belief_view("EVAC"), "BASE", "PR", resource_id="B1")
    log_routes = sim.find_routes(sim.build_belief_view("LOG"), "BASE", "PR", resource_id="B1")
    assert evac_routes[0].route_ids == ["R1", "R2"] and evac_routes[0].travel_steps == 6
    assert all("R2" not in r.route_ids for r in log_routes)
    assert log_routes[0].route_ids == ["R1", "R3", "R4"] and log_routes[0].travel_steps == 9
    assert len(evac_routes) <= 3


def test_disclosure_updates_recipient_view():
    """§4.3: once LOG cites E-LOG-01 to EVAC, Evacuation's view shows R2 closed."""
    sim = StubSim()
    sim.disclose("E-LOG-01", "EVAC")
    assert sim.build_belief_view("EVAC").world["roads"]["R2"]["initial_status"] == "CLOSED_CLEARABLE"
    assert sim.build_belief_view("FIRE").world["roads"]["R2"]["initial_status"] == "OPEN"


def test_crews_cannot_route_over_fire_roads():
    sim = StubSim()
    view = sim.build_belief_view("FIRE")
    assert sim.find_routes(view, "FORK", "PASS", resource_id="C1") == []       # R8/R9 not engine-capable
    assert sim.find_routes(view, "FORK", "PASS", resource_id="V1")[0].route_ids == ["R2", "R8"]


def test_validation_codes():
    sim = StubSim()
    log = sim.build_belief_view("LOG")
    codes = lambda plan, view=log: [v.code for v in sim.validate_plan(view, plan)]  # noqa: E731

    assert codes([drive("B1", "BASE", "VJ", ["R1", "R3"])]) == []
    assert "UNKNOWN_RESOURCE" in codes([drive("B9", "BASE", "VJ", ["R1", "R3"])])                  # AC-020
    assert "ROAD_CLOSED" in codes([drive("B1", "BASE", "PR", ["R1", "R2"])])                       # AC-018
    assert "ROAD_CLOSED" not in codes([drive("B1", "BASE", "PR", ["R1", "R2"])], sim.build_belief_view("EVAC"))
    assert "ROAD_NOT_ENGINE_CAPABLE" in codes([drive("C1", "FORK", "PASS", ["R2", "R8"])])         # AC-018
    assert "WRONG_LOCATION" in codes([drive("B1", "BASE", "PR", ["R3"])])
    assert "RESOURCE_DOUBLE_BOOKED" in codes([drive("B1", "BASE", "VJ", ["R1", "R3"], 0),           # AC-017
                                              task("B1", "load", 3, zone_id="VJ", people_count=30)])
    assert "SCHEDULE_OVERRUN" in codes([drive("B1", "BASE", "VJ", ["R1", "R3"], 58)])              # AC-021


def test_closure_event_increments_version_and_is_public():
    """FR-040 / invariant 6: an event bumps state_version; the override is visible on every view."""
    sim = StubSim()
    v = sim.apply_event({"event_id": "ev-1", "step": 15, "kind": "road_status", "target": "R3", "value": "CLOSED_HARD"})
    assert v == 1
    for agent in ("EVAC", "FIRE", "LOG"):
        assert sim.build_belief_view(agent).world["roads"]["R3"]["status_override"] == "CLOSED_HARD"
    assert "ROAD_CLOSED" in [x.code for x in sim.validate_plan(sim.build_belief_view("EVAC"),
                                                               [drive("B1", "BASE", "VJ", ["R1", "R3"])])]


def test_evaluate_plan_does_not_mutate_world_or_view():
    """AC-022 / FR-011: 50 evaluations leave the authoritative world and the caller's view byte-identical."""
    sim = StubSim()
    before = world_fingerprint(sim.world)
    view = sim.build_belief_view("LOG")
    view_before = world_fingerprint(view.world)
    plan = [drive("B1", "BASE", "VJ", ["R1", "R3"]), task("B1", "load", 5, zone_id="VJ", people_count=30),
            drive("B1", "VJ", "SS", ["R5"], 7), task("B1", "unload", 10, shelter_id="SS")]
    for _ in range(50):
        ev = sim.evaluate_plan(view, plan, plan_hash="9f03c2d4e1aa0000")
    assert world_fingerprint(sim.world) == before and world_fingerprint(view.world) == view_before
    assert ev.valid and ev.basis == "view_LOG" and ev.evaluation_id == "ev-9f03c2d4e1aa-view_LOG-v0"
    assert ev.metrics is not None and ev.metrics.civilian_exposure == 0 and ev.trace_ref is None
    assert [(l.kind, l.start_step, l.end_step) for l in ev.leg_timing] == [
        ("traverse", 0, 3), ("traverse", 3, 5), ("load", 5, 7), ("traverse", 7, 10), ("unload", 10, 11)]


def test_invalid_evaluation_has_no_metrics():
    """§7.6: `metrics` is None when invalid — no numbers from an impossible plan."""
    sim = StubSim()
    ev = sim.evaluate_plan(sim.build_belief_view("LOG"), [drive("B1", "BASE", "PR", ["R1", "R2"])], plan_hash="abc")
    assert not ev.valid and ev.metrics is None and ev.violations[0].code == "ROAD_CLOSED"
