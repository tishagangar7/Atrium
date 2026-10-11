"""Fixed-rule baseline (PRD §11.2 policy, FR-060): deterministic, valid on the authority, V1 never carries crews,
rule-1 zone order, rule-4 refuel. No model calls and no forecast-based choice."""

from __future__ import annotations

import pytest

from app.baselines.fixed_rule import FixedRulePlanner
from app.sim.service import SimulatorService

PRESETS = ["normal", "wind_shift", "road_closure", "compound_failure"]


def plan_for(preset: str, seed: int = 1):
    """Returns the world as it was *before* planning (the validator may mutate its input; see sim fixes)."""
    sim = SimulatorService(preset, seed)
    view = sim.build_belief_view("union")
    before = sim.build_belief_view("union")
    return sim, before, FixedRulePlanner(sim).plan(view)


@pytest.mark.parametrize("preset", PRESETS)
def test_plan_is_valid_on_the_authoritative_world(preset):
    sim, _, plan = plan_for(preset)
    assert plan, "the policy always evacuates someone at step 0"
    assert sim.validate_plan(sim.build_belief_view("authoritative"), plan) == []


@pytest.mark.parametrize("preset", PRESETS)
def test_same_inputs_give_the_same_plan(preset):
    _, _, first = plan_for(preset)
    _, _, second = plan_for(preset)
    assert [a.model_dump() for a in first] == [a.model_dump() for a in second]


def test_v1_always_carries_people_never_crews():
    _, _, plan = plan_for("normal")
    v1 = [a for a in plan if a.resource_id == "V1"]
    assert v1 and all(a.task != "transfer_crew" for a in v1)
    assert any(a.task == "load" for a in v1)


def test_first_trip_goes_to_the_first_zone_in_rule_one_order():
    sim, view, plan = plan_for("normal")
    zones = view.world["zones"]
    order = sorted(zones, key=lambda z: (-zones[z]["hazard"], -zones[z]["assisted_waiting"], z))
    first_load = next(a for a in plan if a.task == "load")
    assert first_load.zone_id == order[0]


def test_loads_never_exceed_vehicle_capacity_or_waiting_residents():
    _, view, plan = plan_for("normal")
    picked: dict[str, int] = {}
    for a in plan:
        if a.task == "load":
            assert a.people_count <= view.world["resources"][a.resource_id]["capacity"]
            picked[a.zone_id] = picked.get(a.zone_id, 0) + a.people_count
    for zone, n in picked.items():
        assert n <= view.world["zones"][zone]["assisted_waiting"]


def test_refuels_when_the_next_trip_exceeds_fuel():
    sim = SimulatorService("normal", 1)
    view = sim.build_belief_view("union")
    view.world["resources"]["B1"]["fuel_remaining"] = 2        # not enough for BASE → VJ → shelter
    view.world["resources"]["B1"]["fuel_used"] = view.world["resources"]["B1"]["fuel_capacity"] - 2
    plan = FixedRulePlanner(sim).plan(view)
    b1 = [a.task for a in plan if a.resource_id == "B1"]
    assert b1[0] == "refuel"
