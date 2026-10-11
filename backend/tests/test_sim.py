"""Fire rules and common random numbers (PRD §5.5, §5.6, FR-014, D-13; §11.5 invariant tests)."""

from __future__ import annotations

from app.models import Wind
from app.sim.fire import (
    apply_reductions,
    fire_phase,
    ignition_probability,
    suppression,
    wind_weight,
)
from app.sim.rng import draw
from app.sim.scenario import load_scenario
from app.sim.world import build_world, fuel_left, zone_hazard


def world(preset="normal", seed=1):
    sc = load_scenario(preset)
    return sc, build_world(sc, "run-t", seed)


def quiet(w):
    """Put the fire out so single-cell rules can be tested in isolation."""
    for c in w.cells.values():
        c.state, c.intensity, c.ignited_step, c.fuel_burned = "UNBURNED", 0, None, 0.0


# --- common random numbers (FR-014) --------------------------------------------------------------------------------

def test_draw_is_deterministic_and_keyed_by_seed_step_cell():
    assert draw(1, 3, "c2_2") == draw(1, 3, "c2_2") and 0.0 <= draw(1, 3, "c2_2") < 1.0
    assert draw(1, 3, "c2_2") != draw(2, 3, "c2_2") != draw(1, 4, "c2_2") != draw(1, 3, "c2_3")
    # §5.5 formula: first 8 bytes of SHA-256("seed:step:cell") / 2^64
    import hashlib
    assert draw(7, 15, "c0_0") == int.from_bytes(hashlib.sha256(b"7:15:c0_0").digest()[:8], "big") / 2**64


def test_two_plans_that_never_touch_a_cell_see_identical_draws():
    """FR-014: the world (and thus any plan) is not an input to the draw."""
    sc, w1 = world()
    _, w2 = world()
    w2.cells["c5_5"].fuel_burned = 0.5    # a different world
    p = sc.fire_params
    assert draw(w1.seed, 10, "c1_2") == draw(w2.seed, 10, "c1_2")


# --- ignition (§5.5) -----------------------------------------------------------------------------------------------

def test_wind_weight_favours_downwind_and_is_floored():
    sc, _ = world()
    p = sc.fire_params
    east = Wind(direction="E", speed=2)
    assert wind_weight("c1_1", "c2_1", east, p) == 1.5           # downwind: 1 + 0.25·2·1
    assert wind_weight("c2_1", "c1_1", east, p) == 0.5           # upwind: 1 − 0.5
    assert wind_weight("c1_1", "c1_2", east, p) == 1.0           # crosswind
    assert wind_weight("c2_1", "c1_1", Wind(direction="E", speed=3), p) == 0.25   # floor at wind_floor


def test_ignition_probability_formula_and_cap():
    sc, w = world()
    p = sc.fire_params
    quiet(w)
    w.cells["c1_1"].state, w.cells["c1_1"].intensity, w.cells["c1_1"].ignited_step = "BURNING", 4, 0
    target = w.cells["c2_1"]           # east neighbour, fuel 0.9
    prob = ignition_probability(w, target, sc.grid, p, s=0.0)
    assert abs(prob - min(0.9, p["k"] * (4 * 1.5 * 1.0) * 0.9)) < 1e-12
    assert ignition_probability(w, target, sc.grid, p, s=0.9) < prob            # suppression lowers it
    assert ignition_probability(w, w.cells["c0_1"], sc.grid, p, s=0.0) < prob    # upwind neighbour less likely
    assert ignition_probability(w, w.cells["c5_5"], sc.grid, p, s=0.0) == 0.0    # no burning neighbour
    for c in ("c1_0", "c2_0", "c1_2", "c2_2"):                                   # push the sum above the cap
        w.cells[c].state, w.cells[c].intensity, w.cells[c].ignited_step = "BURNING", 4, 0
    hot = {**p, "k": 0.2}                      # the cap must hold whatever k the scenario is tuned to
    assert ignition_probability(w, target, sc.grid, hot, s=0.0) == p["p_max"]


def test_fire_phase_ignites_iff_draw_below_probability():
    sc, w = world()
    p = sc.fire_params
    quiet(w)
    w.cells["c1_1"].state, w.cells["c1_1"].intensity, w.cells["c1_1"].ignited_step = "BURNING", 4, 0
    # Deterministic search for a seed under which at least one neighbour ignites at step 5 (CRN makes this stable).
    seed, expected = next((s, e) for s in range(1, 200) if (e := {
        c.id for c in w.cells.values() if c.state == "UNBURNED"
        and draw(s, 5, c.id) < ignition_probability(w, c, sc.grid, p, 0.0)}))
    events = fire_phase(w, step=5, seed=seed, grid=sc.grid, params=p)
    assert set(events.ignited) == expected
    for cid in events.ignited:
        c = w.cells[cid]
        assert c.state == "BURNING" and c.intensity == 1 and c.ignited_step == 5


def test_ignition_is_simultaneous_from_start_of_phase_intensities():
    """A cell ignited this phase must not ignite its neighbours in the same phase."""
    sc, w = world()
    quiet(w)
    w.cells["c0_0"].state, w.cells["c0_0"].intensity, w.cells["c0_0"].ignited_step = "BURNING", 4, 0
    events = fire_phase(w, step=1, seed=3, grid=sc.grid, params=sc.fire_params)
    for cid in events.ignited:
        x, y = int(cid[1:].split("_")[0]), int(cid[1:].split("_")[1])
        assert max(abs(x - 0), abs(y - 0)) == 1       # only direct neighbours of the original fire


# --- growth, burnout, extinguished (§5.5) ------------------------------------------------------------------------

def test_growth_every_four_steps_up_to_four_while_fuel_allows():
    sc, w = world()
    p = sc.fire_params
    quiet(w)
    c = w.cells["c5_1"]
    c.state, c.intensity, c.ignited_step, c.fuel_initial = "BURNING", 1, 0, 5.0   # ample fuel: isolate the schedule
    seen = []
    for step in range(1, 17):
        fire_phase(w, step=step, seed=99, grid=sc.grid, params=p)
        seen.append(c.intensity)
    assert seen[:4] == [1, 1, 1, 2] and seen[7] == 3 and seen[11] == 4 and max(seen) == 4
    # With the real 0.7 fuel a cell burns out before reaching intensity 4: 0.04·I per step (§5.5).
    quiet(w)
    c = w.cells["c5_1"]
    c.state, c.intensity, c.ignited_step, c.fuel_initial = "BURNING", 1, 0, 0.7
    history = []
    for step in range(1, 20):
        fire_phase(w, step=step, seed=99, grid=sc.grid, params=p)
        history.append((c.state, c.intensity))
    assert max(i for _, i in history) <= 3 and history[-1] == ("BURNED_OUT", 0)
    c2 = w.cells["c8_0"]
    c2.state, c2.intensity, c2.ignited_step, c2.fuel_burned = "BURNING", 1, 20, 0.5   # fuel left 0.2 < 0.3
    fire_phase(w, step=24, seed=99, grid=sc.grid, params=p)
    assert c2.intensity == 1                                                           # no growth below growth_fuel_min


def test_fuel_burns_at_rate_times_intensity_and_burns_out():
    sc, w = world()
    p = sc.fire_params
    quiet(w)
    c = w.cells["c5_1"]
    c.state, c.intensity, c.ignited_step = "BURNING", 3, 0
    fire_phase(w, step=1, seed=1, grid=sc.grid, params=p)
    assert abs(c.fuel_burned - 0.12) < 1e-9                        # 0.04 · 3
    c.fuel_burned = c.fuel_initial - 0.06                           # just above burnout, then burns 0.12
    fire_phase(w, step=2, seed=1, grid=sc.grid, params=p)
    assert c.state == "BURNED_OUT" and c.intensity == 0 and fuel_left(c) < p["burnout_fuel"]


def test_suppression_values_and_cap():
    sc, w = world()
    p = sc.fire_params
    plain, firebreak = w.cells["c5_1"], w.cells["c2_1"]
    assert suppression(plain, [], p) == 0.0
    assert suppression(plain, [("C1", False)], p) == 0.7
    assert suppression(plain, [("C1", True)], p) == 0.5
    assert suppression(plain, [("C1", True), ("C2", False)], p) == 0.7          # max over crews
    assert abs(suppression(firebreak, [("C1", False)], p) - 0.85) < 1e-9        # +0.15 firebreak
    assert suppression(firebreak, [("C1", False), ("C2", False)], p) <= p["s_cap"]


def test_reductions_extinguish_and_extinguished_never_reignite():
    sc, w = world()
    p = sc.fire_params
    quiet(w)
    c = w.cells["c5_1"]
    c.state, c.intensity, c.ignited_step = "BURNING", 1, 0
    ev = apply_reductions(w, {"c5_1": 1})
    assert ev.extinguished == ["c5_1"] and c.state == "EXTINGUISHED" and c.intensity == 0
    for n in ("c4_1", "c6_1", "c5_0", "c5_2"):
        w.cells[n].state, w.cells[n].intensity, w.cells[n].ignited_step = "BURNING", 4, 0
    for step in range(1, 30):
        fire_phase(w, step=step, seed=1, grid=sc.grid, params=p)
    assert c.state == "EXTINGUISHED"
    assert apply_reductions(w, {"c5_1": 1}).extinguished == []                 # no-op on non-burning cells


# --- hazard (§5.6) ---------------------------------------------------------------------------------------------------

def test_zone_hazard_is_max_intensity_within_one_cell():
    sc, w = world()
    quiet(w)
    cells = {cid: c.model_dump() for cid, c in w.cells.items()}
    assert zone_hazard(cells, "c3_2", 1, sc.grid) == 0
    cells["c4_3"]["intensity"] = 3            # diagonal neighbour of PR's cell c3_2
    cells["c3_0"]["intensity"] = 4            # two rows away: outside reach
    assert zone_hazard(cells, "c3_2", 1, sc.grid) == 3
