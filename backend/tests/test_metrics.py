"""Metric definitions on hand-built states (PRD §11.1, FR-063), including N/A demand and unfinished evacuation."""

from __future__ import annotations

from app.models import Target
from app.sim.metrics import MetricsAccumulator, accumulate_step, finalize, target_checks
from app.sim.scenario import load_scenario
from app.sim.world import build_world


def fresh():
    sc = load_scenario("normal")
    w = build_world(sc, "run-t", 1)
    for c in w.cells.values():
        c.state, c.intensity, c.ignited_step = "UNBURNED", 0, None
    return sc, w


def step(acc, sc, w, n):
    accumulate_step(acc, w, step=n, grid=sc.grid, params=sc.fire_params, nodes=sc.nodes)


def test_exposure_counts_people_in_hazardous_zones_only():
    sc, w = fresh()
    acc = MetricsAccumulator()
    step(acc, sc, w, 0)
    assert acc.exposure == 0
    w.cells["c2_3"].intensity, w.cells["c2_3"].state = 2, "BURNING"     # within reach of PR (c3_2) only
    step(acc, sc, w, 1)
    assert acc.exposure == 90 + 30                                       # PR unassisted + assisted waiting
    w.zones["PR"].self_evacuated, w.zones["PR"].assisted_picked_up = 40, 10
    step(acc, sc, w, 2)
    assert acc.exposure == 120 + (50 + 20)
    assert acc.burning_cell_steps == 2


def test_assisted_completion_and_na_when_demand_is_zero():
    sc, w = fresh()
    w.shelters["SS"].arrivals = 55
    m = finalize(MetricsAccumulator(), w, params=sc.fire_params)
    assert m.assisted_demand == 110 and m.assisted_sheltered == 55 and m.assisted_completion == 0.5
    for z in w.zones.values():
        z.assisted_initial = 0
    w.shelters["SS"].arrivals = 0
    m = finalize(MetricsAccumulator(), w, params=sc.fire_params)
    assert m.assisted_demand == 0 and m.assisted_completion is None


def test_completion_step_none_when_unfinished_and_set_when_everyone_is_out():
    sc, w = fresh()
    acc = MetricsAccumulator()
    step(acc, sc, w, 0)
    assert acc.completion_step is None
    for z in w.zones.values():
        z.self_evacuated, z.assisted_picked_up = z.unassisted_initial, z.assisted_initial
    w.resources["B1"].aboard_people = {"PR": 5}
    step(acc, sc, w, 7)
    assert acc.completion_step is None                                   # passengers still aboard
    w.resources["B1"].aboard_people = {}
    step(acc, sc, w, 8)
    step(acc, sc, w, 9)
    assert acc.completion_step == 8                                      # first step, not overwritten


def test_crew_risk_and_logistics_risk_components():
    sc, w = fresh()
    acc = MetricsAccumulator()
    w.cells["c4_2"].intensity, w.cells["c4_2"].state = 3, "BURNING"     # next to FORK's cell c5_2 only → C1, C2 at risk
    step(acc, sc, w, 0)
    assert acc.crew_risk_steps == 2
    w.shelters["SS"].arrivals = 20                                       # 340 / 350 > 95%
    step(acc, sc, w, 1)
    w.resources["B1"].fuel_used, w.resources["B1"].node = 38, "VJ"       # 2 fuel left, away from BASE
    acc.wait_risk_legs = 1
    m = finalize(acc, w, params=sc.fire_params)
    assert m.crew_risk_steps == 4 and m.logistics_risk == 1 + 1 + 1 and m.fire_extent == 1


def test_target_checks_directions_and_na():
    sc, w = fresh()
    w.shelters["SS"].arrivals = 100
    m = finalize(MetricsAccumulator(exposure=700), w, params=sc.fire_params)
    checks = {(c.agent_id, c.metric): c for c in target_checks(m, sc.targets)}
    evac_done = checks[("EVAC", "assisted_completion")]
    assert evac_done.value == round(100 / 110, 4) and evac_done.meets_aspiration and evac_done.meets_floor
    exposure = checks[("EVAC", "civilian_exposure")]
    assert exposure.value == 700 and not exposure.meets_aspiration and exposure.meets_floor
    assert checks[("FIRE", "fire_extent")].meets_aspiration and checks[("LOG", "logistics_risk")].meets_aspiration
    na = target_checks(m.model_copy(update={"assisted_completion": None}),
                       {"EVAC": [Target(metric="assisted_completion", direction="max", aspiration=0.9, floor=0.75)]})[0]
    assert na.value is None and not na.meets_aspiration and not na.meets_floor
