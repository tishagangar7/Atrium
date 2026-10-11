"""World construction and derived values (PRD §5.2, §5.6, §5.9, §7.2).

`WorldState` stores statics and counters only; everything else is derived here so beliefs stay consistent when a
static is masked (§5.9): assisted waiting = initial − picked up, road status = initial unless a public override,
fuel remaining = capacity − used, zone hazard = max intensity within reach of the zone's cell.
"""

from __future__ import annotations

from typing import Any

from app.models import Cell, Metrics, Road, Scenario, WorldState

RoadStatus = str


def build_world(scenario: Scenario, run_id: str, seed: int) -> WorldState:
    return WorldState(
        run_id=run_id, scenario_id=scenario.scenario_id, seed=seed, step=0, state_version=0,
        roads={r.id: r.model_copy(deep=True) for r in scenario.roads},
        zones={z.id: z.model_copy(deep=True) for z in scenario.zones},
        shelters={s.id: s.model_copy(deep=True) for s in scenario.shelters},
        cells={c.id: c.model_copy(deep=True) for c in scenario.cells},
        resources={r.id: r.model_copy(deep=True) for r in scenario.resources},
        wind=scenario.wind.model_copy(),
        committed_plan_hash=None, active_legs=[],
        metrics_so_far=empty_metrics(sum(z.assisted_initial for z in scenario.zones)),
        paused=True,
    )


def empty_metrics(assisted_demand: int) -> Metrics:
    return Metrics(civilian_exposure=0, assisted_completion=None if assisted_demand == 0 else 0.0,
                   assisted_sheltered=0, assisted_demand=assisted_demand, evacuation_completion_step=None,
                   fire_extent=0, burning_cell_steps=0, crew_risk_steps=0, logistics_risk=0,
                   invalid_attempted=0, invalid_executed=0)


# --- derived values (work on WorldState or on the serialized dict) ---------------------------------------------------

def road_status(road: Road | dict[str, Any]) -> RoadStatus:
    override = road["status_override"] if isinstance(road, dict) else road.status_override
    initial = road["initial_status"] if isinstance(road, dict) else road.initial_status
    return override or initial


def assisted_waiting(zone: dict[str, Any]) -> int:
    return zone["assisted_initial"] - zone["assisted_picked_up"]


def unassisted_in_zone(zone: dict[str, Any]) -> int:
    return zone["unassisted_initial"] - zone["self_evacuated"]


def fuel_remaining(resource: dict[str, Any]) -> int | None:
    cap = resource["fuel_capacity"]
    return None if cap is None else cap - resource["fuel_used"]


def fuel_left(cell: Cell | dict[str, Any]) -> float:
    if isinstance(cell, dict):
        return max(0.0, cell["fuel_initial"] - cell["fuel_burned"])
    return max(0.0, cell.fuel_initial - cell.fuel_burned)


def cell_xy(cell_id: str) -> tuple[int, int]:
    x, y = cell_id[1:].split("_")
    return int(x), int(y)


def cells_within(cell_id: str, reach: int, grid: tuple[int, int]) -> list[str]:
    """Chebyshev neighbourhood (including the cell itself), row-major order."""
    x0, y0 = cell_xy(cell_id)
    w, h = grid
    return [f"c{x}_{y}" for y in range(max(0, y0 - reach), min(h, y0 + reach + 1))
            for x in range(max(0, x0 - reach), min(w, x0 + reach + 1))]


def zone_hazard(cells: dict[str, Any], zone_cell: str, reach: int, grid: tuple[int, int]) -> int:
    """§5.6: maximum intensity over cells within `reach` of the zone's cell."""
    return max((_intensity(cells[c]) for c in cells_within(zone_cell, reach, grid) if c in cells), default=0)


def _intensity(cell: Cell | dict[str, Any]) -> int:
    return cell["intensity"] if isinstance(cell, dict) else cell.intensity


def world_dict(world: WorldState, scenario: Scenario) -> dict[str, Any]:
    """The serialized world a belief view carries: `WorldState` fields plus the scenario statics the agents' tools
    need (`nodes`, `horizon`, `grid`, `targets`) and derived per-entity values."""
    d = world.model_dump(mode="json")
    d.update(nodes=dict(scenario.nodes), horizon=scenario.horizon, step_minutes=scenario.step_minutes,
             grid=list(scenario.grid), label=scenario.label,
             targets={a: [t.model_dump(mode="json") for t in ts] for a, ts in scenario.targets.items()})
    reach = int(scenario.fire_params.get("hazard_reach", 1))
    for road in d["roads"].values():
        road["status"] = road_status(road)
    for zone in d["zones"].values():
        zone["assisted_waiting"] = assisted_waiting(zone)
        zone["unassisted_in_zone"] = unassisted_in_zone(zone)
        zone["hazard"] = zone_hazard(d["cells"], zone["cell"], reach, scenario.grid)
    for shelter in d["shelters"].values():
        shelter["occupancy"] = shelter["background"] + shelter["arrivals"]
        shelter["remaining"] = shelter["capacity"] - shelter["occupancy"]
    for resource in d["resources"].values():
        resource["fuel_remaining"] = fuel_remaining(resource)
    for cell in d["cells"].values():
        cell["fuel"] = round(fuel_left(cell), 4)
    return d
