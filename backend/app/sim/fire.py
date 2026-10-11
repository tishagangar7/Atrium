"""Fire rules (PRD §5.5): ignition with common random numbers, growth, burnout, suppression, crew effect.

All coefficients come from `scenario.fire_params` (k, p_max, diag_weight, wind_factor, wind_floor, growth_every,
growth_fuel_min, max_intensity, burn_rate, burnout_fuel, s_engine, s_hand, firebreak_bonus, s_cap). Fire never closes
roads by itself (§5.5 "What fire does not do"). Cells reduced to 0 by crews become EXTINGUISHED and never re-ignite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from app.models import Cell, Wind, WorldState
from app.sim.rng import draw
from app.sim.world import cell_xy, fuel_left

# Direction the wind blows TOWARD, as (dx, dy) with y growing south (§5.2 grid, §5.5).
WIND_VECTORS: dict[str, tuple[int, int]] = {
    "N": (0, -1), "NE": (1, -1), "E": (1, 0), "SE": (1, 1), "S": (0, 1), "SW": (-1, 1), "W": (-1, 0), "NW": (-1, -1),
}


@dataclass
class FireEvents:
    """What happened in one fire phase, for `SimulationEvent`s and metrics."""

    ignited: list[str] = field(default_factory=list)
    burned_out: list[str] = field(default_factory=list)
    extinguished: list[str] = field(default_factory=list)
    grew: list[str] = field(default_factory=list)


# --- suppression (§5.5 crew effect) ------------------------------------------------------------------------------

def suppression(cell: Cell, crews: list[tuple[str, bool]], params: dict[str, float]) -> float:
    """s(c) for one step: max over crews working the cell of (engine 0.7 | hand 0.5) + firebreak bonus, capped.
    `crews` holds `(crew_id, is_hand_crew)`."""
    if not crews:
        return 0.0
    best = max(params["s_hand"] if hand else params["s_engine"] for _, hand in crews)
    if cell.firebreak_bonus:
        best += params["firebreak_bonus"]
    return min(params["s_cap"], best)


def apply_reductions(world: WorldState, reductions: dict[str, int]) -> FireEvents:
    """§5.7 phase 3: every `reduce_every` active steps a burning target cell loses 1 intensity per crew working it.
    A cell reduced to 0 becomes EXTINGUISHED and cannot re-ignite this horizon."""
    events = FireEvents()
    for cell_id, points in reductions.items():
        cell = world.cells[cell_id]
        if cell.state != "BURNING" or points <= 0:
            continue
        cell.intensity = max(0, cell.intensity - points)
        if cell.intensity == 0:
            cell.state = "EXTINGUISHED"
            events.extinguished.append(cell_id)
    return events


# --- ignition, growth, burnout (§5.7 phase 5) ------------------------------------------------------------------

def wind_weight(from_cell: str, to_cell: str, wind: Wind, params: dict[str, float]) -> float:
    """w(n→c) = max(wind_floor, 1 + wind_factor · speed · cos(angle between (c − n) and the wind direction))."""
    (x0, y0), (x1, y1) = cell_xy(from_cell), cell_xy(to_cell)
    vx, vy = x1 - x0, y1 - y0
    wx, wy = WIND_VECTORS[wind.direction]
    cos = (vx * wx + vy * wy) / (math.hypot(vx, vy) * math.hypot(wx, wy))
    return max(params["wind_floor"], 1.0 + params["wind_factor"] * wind.speed * cos)


def ignition_pressure(world: WorldState, cell_id: str, grid: tuple[int, int], params: dict[str, float]) -> float:
    """P(c) = Σ over burning 8-neighbours n of I(n) · w(n→c) · g(n,c), g = 1 for sides, diag_weight for diagonals."""
    x, y = cell_xy(cell_id)
    w, h = grid
    total = 0.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h):
                continue
            n = world.cells.get(f"c{nx}_{ny}")
            if n is None or n.state != "BURNING" or n.intensity <= 0:
                continue
            g = 1.0 if dx == 0 or dy == 0 else params["diag_weight"]
            total += n.intensity * wind_weight(n.id, cell_id, world.wind, params) * g
    return total


def ignition_probability(world: WorldState, cell: Cell, grid: tuple[int, int], params: dict[str, float],
                         s: float) -> float:
    """p(c) = min(p_max, k · P(c) · fuel(c) · (1 − s(c)))."""
    pressure = ignition_pressure(world, cell.id, grid, params)
    if pressure <= 0.0:
        return 0.0
    return min(params["p_max"], params["k"] * pressure * fuel_left(cell) * (1.0 - s))


def fire_phase(world: WorldState, *, step: int, seed: int, grid: tuple[int, int], params: dict[str, float],
               suppression_by_cell: dict[str, float] | None = None) -> FireEvents:
    """One fire phase (§5.5, §5.7 phase 5): ignition from the intensities at the start of the phase, then growth and
    burnout for every burning cell. Deterministic given (seed, step) and the world."""
    s_by_cell = suppression_by_cell or {}
    events = FireEvents()

    # Ignition is simultaneous: decide from a snapshot of which cells burn now, then mutate.
    to_ignite: list[Cell] = []
    for cell in world.cells.values():
        if cell.state != "UNBURNED" or fuel_left(cell) <= 0.0:
            continue
        p = ignition_probability(world, cell, grid, params, s_by_cell.get(cell.id, 0.0))
        if p > 0.0 and draw(seed, step, cell.id) < p:
            to_ignite.append(cell)
    for cell in to_ignite:
        cell.state, cell.intensity, cell.ignited_step = "BURNING", 1, step
        events.ignited.append(cell.id)

    # Growth and burnout for cells that were already burning before this phase.
    growth_every = int(params["growth_every"])
    for cell in world.cells.values():
        if cell.state != "BURNING" or cell.id in events.ignited:
            continue
        since = step - (cell.ignited_step if cell.ignited_step is not None else step)
        if (since > 0 and since % growth_every == 0 and cell.intensity < int(params["max_intensity"])
                and fuel_left(cell) >= params["growth_fuel_min"]):
            cell.intensity += 1
            events.grew.append(cell.id)
        cell.fuel_burned = min(cell.fuel_initial, cell.fuel_burned + params["burn_rate"] * cell.intensity)
        if fuel_left(cell) < params["burnout_fuel"]:
            cell.intensity, cell.state = 0, "BURNED_OUT"
            events.burned_out.append(cell.id)
    return events


def burning_cells(world: WorldState) -> list[str]:
    return [c.id for c in world.cells.values() if c.state == "BURNING"]


def fire_extent(world: WorldState) -> int:
    """§11.1: cells with state ≠ UNBURNED (states never revert, so this equals 'cells ever ignited')."""
    return sum(1 for c in world.cells.values() if c.state != "UNBURNED")


def summarize(events: FireEvents) -> dict[str, Any]:
    return {"ignited": events.ignited, "grew": events.grew, "burned_out": events.burned_out,
            "extinguished": events.extinguished}
