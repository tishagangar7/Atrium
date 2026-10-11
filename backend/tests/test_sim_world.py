"""Scenario presets and world construction (PRD §5.2, §5.3, §5.9, §5.11, §5.12, §7.2; FR-001, FR-042, AC-014)."""

from __future__ import annotations

import json

from app.models import Scenario
from app.sim.scenario import PRESETS, available_scenarios, load_scenario, scenario_path
from app.sim.world import build_world, world_dict


def test_all_presets_load_and_match_the_prd_tables():
    assert set(PRESETS) <= set(available_scenarios())
    for preset in PRESETS:
        sc = load_scenario(preset)
        assert isinstance(sc, Scenario) and sc.label == "Synthetic simulation" and sc.horizon == 60
        assert sc.grid == (10, 6) and len(sc.cells) == 60
        assert [r.id for r in sc.roads] == [f"R{i}" for i in range(1, 12)]
        assert {r.id for r in sc.roads if not r.engine_ok} == {"R8", "R9"}
        assert next(r for r in sc.roads if r.id == "R2").initial_status == "CLOSED_CLEARABLE"
        assert {z.id: (z.unassisted_initial, z.assisted_initial) for z in sc.zones} == {
            "NC": (20, 20), "PR": (90, 30), "VJ": (240, 60)}
        assert {s.id: (s.capacity, s.background) for s in sc.shelters} == {"SE": (150, 40), "SS": (350, 320)}
        assert {r.id: r.node for r in sc.resources} == {"B1": "BASE", "B2": "BASE", "V1": "BASE", "C1": "FORK",
                                                       "C2": "FORK", "C3": "BASE"}
        assert [e.evidence_id for e in sc.evidence] == ["E-EVAC-01", "E-EVAC-02", "E-EVAC-03", "E-FIRE-01",
                                                        "E-FIRE-02", "E-LOG-01", "E-LOG-02"]
        assert sc.wind.direction == "E" and sc.wind.speed == 2
        assert {m.metric for ts in sc.targets.values() for m in ts} == {
            "assisted_completion", "civilian_exposure", "fire_extent", "crew_risk_steps", "logistics_risk"}


def test_initial_fire_and_fuel_follow_section_5_2():
    sc = load_scenario("normal")
    cells = {c.id: c for c in sc.cells}
    assert {(cid, c.intensity) for cid, c in cells.items() if c.state == "BURNING"} == {("c0_2", 2), ("c0_3", 2), ("c1_3", 1)}
    assert all(cells[c].fuel_initial == 0.9 for c in ("c1_1", "c2_1", "c1_2", "c2_2"))
    assert all(cells[sc.nodes[n]].fuel_initial == 0.2 for n in ("BASE", "SE", "SS"))
    assert cells["c2_1"].firebreak_bonus is True and cells["c3_2"].fuel_initial == 0.7


def test_preset_events_fire_at_step_15():
    """FR-042 / §5.11."""
    expect = {"normal": [], "wind_shift": [("wind_change", None, "SE:3")],
              "road_closure": [("road_status", "R3", "CLOSED_HARD")],
              "compound_failure": [("wind_change", None, "SE:3"), ("road_status", "R3", "CLOSED_HARD"),
                                   ("road_status", "R5", "CLOSED_HARD"), ("resource_status", "B2", "OUT_OF_SERVICE")]}
    for preset, events in expect.items():
        sc = load_scenario(preset)
        assert [(e.kind, e.target, e.value) for e in sc.events] == events
        assert all(e.step == 15 and e.public for e in sc.events)


def test_world_build_is_deterministic_and_dict_has_derived_values():
    """AC-014: same scenario + seed → identical WorldState JSON; derived values recomputed from statics (§5.9)."""
    sc = load_scenario("normal")
    a, b = build_world(sc, "run-x", 1), build_world(sc, "run-x", 1)
    assert a.model_dump_json() == b.model_dump_json()
    assert a.state_version == 0 and a.step == 0 and a.paused and a.metrics_so_far.assisted_demand == 110
    d = world_dict(a, sc)
    assert d["nodes"]["PR"] == "c3_2" and d["horizon"] == 60 and d["grid"] == [10, 6]
    assert d["roads"]["R2"]["status"] == "CLOSED_CLEARABLE" and d["roads"]["R1"]["status"] == "OPEN"
    assert d["zones"]["PR"]["assisted_waiting"] == 30 and d["zones"]["VJ"]["unassisted_in_zone"] == 240
    assert d["shelters"]["SS"]["remaining"] == 30 and d["resources"]["B1"]["fuel_remaining"] == 40
    assert d["zones"]["PR"]["hazard"] == 0 and d["cells"]["c0_2"]["fuel"] == 0.7
    assert d["targets"]["LOG"][0]["metric"] == "logistics_risk"


def test_json_files_are_the_source_of_truth():
    """AGENTS.md §7: numbers live in scenarios/*.json; the generator only reproduces them."""
    raw = json.loads(scenario_path("normal").read_text())
    assert raw["fire_params"]["k"] == 0.06 and raw["fire_params"]["growth_every"] == 4
    assert raw["fire_params"]["self_evac_per_step"] == 20 and raw["fire_params"]["clear_road_steps"] == 6
