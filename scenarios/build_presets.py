"""Generate the four benchmark presets from the PRD §5 tables (run: `python scenarios/build_presets.py`).

The JSON files are the source of truth at runtime (AGENTS.md §7: scenario numbers live in `scenarios/*.json`); this
script exists so the 60-cell grid and the §5.2/§5.3/§5.9/§5.11/§5.12 tables are transcribed once, reproducibly, and
so tuning changes (§5.13) are diffs to one file. Record tuning changes in `scenarios/CHANGELOG.md`.

Everything is synthetic: a fictional ~8-node region on a 10 x 6 grid (PRD §1.6, §5.2). Values are PROPOSED defaults.
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRID_W, GRID_H = 10, 6
HORIZON = 60
STEP_MINUTES = 2

# §5.2 nodes -> cells
NODES = {"NC": "c3_0", "PASS": "c2_1", "PR": "c3_2", "FORK": "c5_2", "BASE": "c7_2", "SE": "c9_2", "VJ": "c5_4", "SS": "c6_5"}

# §5.2 roads: id, a, b, travel_steps, capacity, engine_ok, true initial status
ROADS = [
    ("R1", "BASE", "FORK", 3, 2, True, "OPEN"),
    ("R2", "FORK", "PR", 3, 1, True, "CLOSED_CLEARABLE"),
    ("R3", "FORK", "VJ", 2, 2, True, "OPEN"),
    ("R4", "VJ", "PR", 8, 1, True, "OPEN"),
    ("R5", "VJ", "SS", 6, 2, True, "OPEN"),
    ("R6", "FORK", "SE", 6, 2, True, "OPEN"),
    ("R7", "VJ", "SE", 9, 1, True, "OPEN"),
    ("R8", "PR", "PASS", 3, 1, False, "OPEN"),
    ("R9", "PASS", "NC", 3, 1, False, "OPEN"),
    ("R10", "NC", "FORK", 7, 1, True, "OPEN"),
    ("R11", "BASE", "SS", 4, 2, True, "OPEN"),
]

# §5.2 zones: id, name, total people, assisted (true)  -> unassisted_initial = total - assisted
ZONES = [("NC", "North Camp", 40, 20), ("PR", "Pine Ridge", 120, 30), ("VJ", "Valley Junction", 300, 60)]
# §5.2 shelters: id, name, capacity, true background occupancy
SHELTERS = [("SE", "Shelter East", 150, 40), ("SS", "Shelter South", 350, 320)]

# §5.2 fire cells and fuel
INITIAL_FIRE = {"c0_2": 2, "c0_3": 2, "c1_3": 1}
RIDGE_CELLS = ("c1_1", "c2_1", "c1_2", "c2_2")        # 0.9 true fuel, public prior 0.5 (E-FIRE-01)
CLEARED_NODES = ("BASE", "SE", "SS")                    # 0.2 fuel on their cells
FIREBREAK_CELL = "c2_1"                                 # true, prior false (E-FIRE-02)
FUEL_DEFAULT, FUEL_RIDGE, FUEL_CLEARED = 0.7, 0.9, 0.2

# §5.3 resources: id, type, start node, capacity, fuel capacity
RESOURCES = [("B1", "bus", "BASE", 30, 40), ("B2", "bus", "BASE", 30, 40), ("V1", "transport", "BASE", 10, 30),
             ("C1", "crew", "FORK", 0, None), ("C2", "crew", "FORK", 0, None), ("C3", "crew", "BASE", 0, None)]

# §5.9 evidence: id, holder, field_path, true, prior, summary (<= 160 chars)
EVIDENCE = [
    ("E-EVAC-01", "EVAC", "zones.PR.assisted_initial", 30, 12, "Pine Ridge has 30 assisted residents waiting, not the 12 in the public estimate."),
    ("E-EVAC-02", "EVAC", "zones.VJ.assisted_initial", 60, 30, "Valley Junction has 60 assisted residents waiting, not the 30 in the public estimate."),
    ("E-EVAC-03", "EVAC", "zones.NC.assisted_initial", 20, 4, "North Camp has 20 assisted residents waiting, not the 4 in the public estimate."),
    ("E-FIRE-01", "FIRE", "cells[c1_1, c2_1, c1_2, c2_2].fuel_initial", 0.9, 0.5, "Ridge cells carry heavy fuel (0.9); fire will intensify toward Ridge Pass."),
    ("E-FIRE-02", "FIRE", "cells.c2_1.firebreak_bonus", True, False, "Ridge Pass has a natural firebreak; containment there is more effective."),
    ("E-LOG-01", "LOG", "roads.R2.initial_status", "CLOSED_CLEARABLE", "OPEN", "R2 Fork-Pine Ridge blocked by downed trees; a crew can clear it in about 6 steps"),
    ("E-LOG-02", "LOG", "shelters.SS.background", 320, 290, "Shelter South already holds 320 people, not 290; only 30 beds remain."),
]

# §5.12 targets
TARGETS = {
    "EVAC": [{"metric": "assisted_completion", "direction": "max", "aspiration": 0.90, "floor": 0.75},
             {"metric": "civilian_exposure", "direction": "min", "aspiration": 600, "floor": 1200}],
    "FIRE": [{"metric": "fire_extent", "direction": "min", "aspiration": 45, "floor": 60},
             {"metric": "crew_risk_steps", "direction": "min", "aspiration": 0, "floor": 4}],
    "LOG": [{"metric": "logistics_risk", "direction": "min", "aspiration": 1, "floor": 3}],
}

# §5.4, §5.5, §5.6, §11.1 rule parameters (floats; the engine reads these, never code constants)
FIRE_PARAMS = {
    "k": 0.06, "p_max": 0.9, "diag_weight": 0.7, "wind_factor": 0.25, "wind_floor": 0.25,
    "growth_every": 4, "growth_fuel_min": 0.3, "max_intensity": 4, "burn_rate": 0.04, "burnout_fuel": 0.05,
    "s_engine": 0.7, "s_hand": 0.5, "firebreak_bonus": 0.15, "s_cap": 0.9, "reduce_every": 3,
    "contain_reach": 1, "contain_max_targets": 3, "contain_max_intensity_at_start": 3, "contain_min_steps": 3,
    "hazard_reach": 1, "exposure_hazard_min": 2, "crew_risk_hazard_min": 3,
    "self_evac_per_step": 20,
    "load_steps": 2, "unload_steps": 1, "refuel_steps": 3, "clear_road_steps": 6,
    "transfer_board_steps": 1, "transfer_drop_steps": 1,
    "logistics_fuel_min": 5, "shelter_risk_fraction": 0.95, "wait_risk_steps": 3,
}

# §5.11 presets: scheduled events, all at step 15 in benchmarks
EVENT_STEP = 15
PRESETS = {
    "normal": [],
    "wind_shift": [("wind_change", None, "SE:3")],
    "road_closure": [("road_status", "R3", "CLOSED_HARD")],
    "compound_failure": [("wind_change", None, "SE:3"), ("road_status", "R3", "CLOSED_HARD"),
                         ("road_status", "R5", "CLOSED_HARD"), ("resource_status", "B2", "OUT_OF_SERVICE")],
}
TITLES = {"normal": "Normal scarcity", "wind_shift": "Wind shift toward SE", "road_closure": "R3 closed",
          "compound_failure": "Compound failure: wind, R3 and R5 closed, B2 out of service"}


def cells() -> list[dict]:
    cleared = {NODES[n] for n in CLEARED_NODES}
    out = []
    for y in range(GRID_H):
        for x in range(GRID_W):
            cid = f"c{x}_{y}"
            fuel = FUEL_RIDGE if cid in RIDGE_CELLS else FUEL_CLEARED if cid in cleared else FUEL_DEFAULT
            intensity = INITIAL_FIRE.get(cid, 0)
            out.append({"id": cid, "x": x, "y": y, "fuel_initial": fuel, "fuel_burned": 0.0,
                        "firebreak_bonus": cid == FIREBREAK_CELL,
                        "state": "BURNING" if intensity else "UNBURNED", "intensity": intensity,
                        "ignited_step": 0 if intensity else None})
    return out


def scenario(preset: str) -> dict:
    return {
        "schema_version": "1", "scenario_id": preset, "title": TITLES[preset],
        "horizon": HORIZON, "step_minutes": STEP_MINUTES, "grid": [GRID_W, GRID_H],
        "nodes": NODES,
        "roads": [{"id": r, "a": a, "b": b, "travel_steps": t, "capacity": c, "engine_ok": e, "initial_status": s,
                   "status_override": None, "clear_progress": 0} for r, a, b, t, c, e, s in ROADS],
        "zones": [{"id": z, "name": n, "cell": NODES[z], "unassisted_initial": total - assisted,
                   "assisted_initial": assisted, "self_evacuated": 0, "assisted_picked_up": 0}
                  for z, n, total, assisted in ZONES],
        "shelters": [{"id": s, "name": n, "cell": NODES[s], "capacity": cap, "background": bg, "arrivals": 0}
                     for s, n, cap, bg in SHELTERS],
        "cells": cells(),
        "resources": [{"id": r, "type": t, "node": node, "edge": None, "edge_steps_left": 0, "capacity": cap,
                       "fuel_capacity": fuel, "fuel_used": 0, "aboard_people": {}, "aboard_crew": None,
                       "engine_node": node if t == "crew" else None, "available": True}
                      for r, t, node, cap, fuel in RESOURCES],
        "wind": {"direction": "E", "speed": 2},
        "fire_params": FIRE_PARAMS,
        "evidence": [{"evidence_id": i, "holders": [h], "field_path": p, "true_value": tv, "prior_value": pv,
                      "summary": s, "observed_step": 0, "confidence": "high"} for i, h, p, tv, pv, s in EVIDENCE],
        "events": [{"event_id": f"{preset}-e{n + 1}", "step": EVENT_STEP, "kind": kind, "target": target,
                    "value": value, "public": True} for n, (kind, target, value) in enumerate(PRESETS[preset])],
        "targets": TARGETS,
        "label": "Synthetic simulation",
    }


def main() -> None:
    for preset in PRESETS:
        path = HERE / f"{preset}.json"
        path.write_text(json.dumps(scenario(preset), indent=1) + "\n")
        print(f"wrote {path.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
