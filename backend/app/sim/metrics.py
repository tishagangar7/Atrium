"""Metric definitions (PRD §11.1, §5.6, §5.12) and target checks (§7.6).

    civilian_exposure          Σ_t Σ_z (unassisted_in_zone + assisted_waiting) · 1[h(z,t) ≥ exposure_hazard_min]
    assisted_completion        assisted_sheltered / assisted_demand; None when demand is 0 (reported N/A)
    evacuation_completion_step first t with no resident in any zone and no passenger aboard; None if not reached
    fire_extent                cells with state ≠ UNBURNED at the end; burning_cell_steps = Σ_t |BURNING|
    crew_risk_steps            Σ_t Σ_crews 1[hazard at the crew's node ≥ crew_risk_hazard_min]
    logistics_risk             vehicles ending with fuel < logistics_fuel_min and not at BASE
                               + shelters that exceeded shelter_risk_fraction of capacity at any step
                               + legs with wait_steps ≥ wait_risk_steps
Every number here is produced by the simulator (invariant 3); agents never author metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import AgentId, Metrics, Target, TargetCheck, WorldState
from app.sim.fire import fire_extent
from app.sim.world import assisted_waiting, cells_within, unassisted_in_zone, zone_hazard

BASE_NODE = "BASE"


@dataclass
class MetricsAccumulator:
    exposure: int = 0
    burning_cell_steps: int = 0
    crew_risk_steps: int = 0
    completion_step: int | None = None
    shelters_over: set[str] = field(default_factory=set)
    wait_risk_legs: int = 0
    invalid_attempted: int = 0
    invalid_executed: int = 0


def accumulate_step(acc: MetricsAccumulator, world: WorldState, *, step: int, grid: tuple[int, int],
                    params: dict[str, float], nodes: dict[str, str]) -> None:
    """§5.7 phase 6, after the fire phase of step `step`. `nodes` is the scenario's node → cell map (junctions such
    as FORK/BASE are nodes without a zone or shelter, and crews stand there)."""
    cells = {cid: c.model_dump() for cid, c in world.cells.items()}
    reach = int(params.get("hazard_reach", 1))
    exposure_min = int(params.get("exposure_hazard_min", 2))
    crew_min = int(params.get("crew_risk_hazard_min", 3))
    frac = params.get("shelter_risk_fraction", 0.95)

    for zone in world.zones.values():
        z = zone.model_dump()
        if zone_hazard(cells, zone.cell, reach, grid) >= exposure_min:
            acc.exposure += unassisted_in_zone(z) + assisted_waiting(z)
    acc.burning_cell_steps += sum(1 for c in world.cells.values() if c.state == "BURNING")
    for res in world.resources.values():
        if res.type == "crew" and res.node is not None:
            node_cell = nodes.get(res.node)
            if node_cell and zone_hazard(cells, node_cell, reach, grid) >= crew_min:
                acc.crew_risk_steps += 1
    for shelter in world.shelters.values():
        if shelter.background + shelter.arrivals > frac * shelter.capacity:
            acc.shelters_over.add(shelter.id)
    if acc.completion_step is None and _everyone_out(world):
        acc.completion_step = step


def finalize(acc: MetricsAccumulator, world: WorldState, *, params: dict[str, float]) -> Metrics:
    demand = sum(z.assisted_initial for z in world.zones.values())
    sheltered = sum(s.arrivals for s in world.shelters.values())
    fuel_min = int(params.get("logistics_fuel_min", 5))
    low_fuel_away = sum(
        1 for r in world.resources.values()
        if r.fuel_capacity is not None and (r.fuel_capacity - r.fuel_used) < fuel_min and r.node != BASE_NODE)
    return Metrics(
        civilian_exposure=acc.exposure,
        assisted_completion=None if demand == 0 else round(sheltered / demand, 4),
        assisted_sheltered=sheltered, assisted_demand=demand,
        evacuation_completion_step=acc.completion_step,
        fire_extent=fire_extent(world), burning_cell_steps=acc.burning_cell_steps,
        crew_risk_steps=acc.crew_risk_steps,
        logistics_risk=low_fuel_away + len(acc.shelters_over) + acc.wait_risk_legs,
        invalid_attempted=acc.invalid_attempted, invalid_executed=acc.invalid_executed,
    )


def target_checks(metrics: Metrics, targets: dict[AgentId, list[Target]]) -> list[TargetCheck]:
    """§7.6 `TargetCheck` for every agent target; `value` None when the metric is N/A (then nothing is met)."""
    out: list[TargetCheck] = []
    for agent, ts in targets.items():
        for t in ts:
            value = getattr(metrics, t.metric)
            if value is None:
                out.append(TargetCheck(agent_id=agent, metric=t.metric, value=None, meets_aspiration=False,
                                       meets_floor=False))
                continue
            if t.direction == "max":
                asp, floor = value >= t.aspiration, value >= t.floor
            else:
                asp, floor = value <= t.aspiration, value <= t.floor
            out.append(TargetCheck(agent_id=agent, metric=t.metric, value=float(value), meets_aspiration=asp,
                                   meets_floor=floor))
    return out


def _everyone_out(world: WorldState) -> bool:
    if any(unassisted_in_zone(z.model_dump()) > 0 or assisted_waiting(z.model_dump()) > 0 for z in world.zones.values()):
        return False
    return all(sum(r.aboard_people.values()) == 0 for r in world.resources.values())


def hazard_at_node(world: WorldState, node_cell: str, *, grid: tuple[int, int], reach: int = 1) -> int:
    cells = {cid: c.model_dump() for cid, c in world.cells.items()}
    return max((cells[c]["intensity"] for c in cells_within(node_cell, reach, grid) if c in cells), default=0)
