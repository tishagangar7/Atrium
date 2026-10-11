"""Belief views and evidence masking on the real simulator (PRD §5.9, §4.3, FR-013, FR-015; AC-024, AC-025 slice)."""

from __future__ import annotations

import json

from app.sim.beliefs import expand_field_path, masked_world
from app.sim.service import SimulatorService


def views(sim):
    return {a: sim.build_belief_view(a) for a in ("EVAC", "FIRE", "LOG", "union", "authoritative")}


def test_unheld_statics_show_priors_and_held_show_truth():
    v = views(SimulatorService("normal", 1))
    assert v["EVAC"].world["roads"]["R2"]["initial_status"] == "OPEN"
    assert v["LOG"].world["roads"]["R2"]["initial_status"] == "CLOSED_CLEARABLE"
    assert v["LOG"].world["zones"]["PR"]["assisted_initial"] == 12 and v["EVAC"].world["zones"]["PR"]["assisted_initial"] == 30
    assert v["FIRE"].world["cells"]["c1_1"]["fuel_initial"] == 0.9 and v["EVAC"].world["cells"]["c1_1"]["fuel_initial"] == 0.5
    assert v["FIRE"].world["cells"]["c2_1"]["firebreak_bonus"] is True and v["LOG"].world["cells"]["c2_1"]["firebreak_bonus"] is False
    assert v["EVAC"].world["shelters"]["SS"]["background"] == 290 and v["LOG"].world["shelters"]["SS"]["background"] == 320
    assert {e.evidence_id for e in v["LOG"].held_evidence} == {"E-LOG-01", "E-LOG-02"}
    assert len(v["union"].held_evidence) == 7 and v["union"].world["roads"]["R2"]["initial_status"] == "CLOSED_CLEARABLE"
    assert v["authoritative"].held_evidence == [] and v["authoritative"].world["shelters"]["SS"]["background"] == 320
    assert v["EVAC"].basis == "view_EVAC" and v["union"].basis == "union" and v["authoritative"].basis == "authoritative"


def test_derived_values_follow_the_masked_statics():
    """§5.9: assisted waiting, road status, shelter remaining are recomputed from the belief, not copied."""
    v = views(SimulatorService("normal", 1))
    assert v["EVAC"].world["roads"]["R2"]["status"] == "OPEN" and v["LOG"].world["roads"]["R2"]["status"] == "CLOSED_CLEARABLE"
    assert v["LOG"].world["zones"]["PR"]["assisted_waiting"] == 12 and v["EVAC"].world["zones"]["PR"]["assisted_waiting"] == 30
    assert v["EVAC"].world["shelters"]["SS"]["remaining"] == 60 and v["LOG"].world["shelters"]["SS"]["remaining"] == 30
    assert v["FIRE"].world["cells"]["c1_1"]["fuel"] == 0.9 and v["EVAC"].world["cells"]["c1_1"]["fuel"] == 0.5


def test_public_override_is_visible_to_everyone():
    sim = SimulatorService("normal", 1)
    sim.apply_event({"event_id": "e1", "step": 0, "kind": "road_status", "target": "R3", "value": "CLOSED_HARD"})
    for agent, view in views(sim).items():
        assert view.world["roads"]["R3"]["status"] == "CLOSED_HARD", agent
        assert view.state_version == 1


def test_disclosure_changes_only_the_recipient():
    sim = SimulatorService("normal", 1)
    sim.disclose("E-LOG-01", "EVAC")
    assert sim.build_belief_view("EVAC").world["roads"]["R2"]["status"] == "CLOSED_CLEARABLE"
    assert sim.build_belief_view("FIRE").world["roads"]["R2"]["status"] == "OPEN"
    assert sim.evidence_holders()["E-LOG-01"] == ["EVAC", "LOG"]


def test_tools_use_the_callers_view():
    """AC-024 / FR-013: Evacuation's find_routes returns R2 while the closure is undisclosed; Logistics' does not."""
    sim = SimulatorService("normal", 1)
    evac = sim.find_routes(sim.build_belief_view("EVAC"), "BASE", "PR", resource_id="B1")
    log = sim.find_routes(sim.build_belief_view("LOG"), "BASE", "PR", resource_id="B1")
    assert evac[0].route_ids == ["R1", "R2"] and evac[0].travel_steps == 6
    assert all("R2" not in r.route_ids for r in log) and log[0].route_ids == ["R1", "R3", "R4"]
    assert sim.find_routes(sim.build_belief_view("FIRE"), "FORK", "PASS", resource_id="C1") == []   # engine roads only


def test_view_never_contains_unheld_ids_or_true_values():
    """AC-025 slice: a serialized view is safe to put in a prompt."""
    v = views(SimulatorService("normal", 1))
    evac = json.dumps(v["EVAC"].world) + json.dumps([e.model_dump(mode="json") for e in v["EVAC"].held_evidence])
    assert "E-LOG-01" not in evac and "CLOSED_CLEARABLE" not in evac and '"background": 320' not in evac
    assert "E-FIRE-02" not in evac and '"firebreak_bonus": true' not in evac
    log = v["LOG"].world["zones"]
    assert (log["PR"]["assisted_initial"], log["NC"]["assisted_initial"]) == (12, 4)   # EVAC's true 30 / 20 are masked
    assert "E-EVAC-01" not in json.dumps([e.model_dump(mode="json") for e in v["LOG"].held_evidence])


def test_masked_world_rebuilds_a_consistent_worldstate():
    sim = SimulatorService("normal", 1)
    w = masked_world(sim.build_belief_view("EVAC"))
    assert w.roads["R2"].initial_status == "OPEN" and w.zones["PR"].assisted_initial == 30
    assert w.state_version == 0 and sim.world.roads["R2"].initial_status == "CLOSED_CLEARABLE"   # the authority is untouched


def test_field_path_forms():
    assert expand_field_path("roads.R2.initial_status") == [["roads", "R2", "initial_status"]]
    assert expand_field_path("cells[c1_1, c2_1].fuel_initial") == [["cells", "c1_1", "fuel_initial"], ["cells", "c2_1", "fuel_initial"]]
