"""The deterministic step engine (PRD §5.4–§5.7; FR-002, FR-003, FR-004, AC-037).

Executes a plan's legs (already timed by `plans.expand`, so waits are baked in) over a `WorldState` in the §5.7 order:

  1. exogenous events for this step (the caller passes them; counterfactual evaluations pass none, D-15)
  2. resource progress in ascending resource id: traverse / load / unload / board / drop / work / refuel
  3. completions: roads cleared this step open, contain reductions apply
  4. self-evacuation outflow (20 per step per zone with an open adjacent road)
  5. fire phase: ignition from start-of-phase intensities, then growth and burnout
  6. hazard and metrics
  7. invariant checks; t ← t + 1

The engine knows nothing about agents, plans' authors or metrics' meaning; it only moves the world forward.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import Leg, Scenario, ScheduledEvent, WorldState
from app.sim import fire
from app.sim.events import apply_event
from app.sim.metrics import MetricsAccumulator, accumulate_step
from app.sim.world import assisted_waiting, road_status, unassisted_in_zone


class InvariantError(AssertionError):
    """§5.6 conservation broken: the run pauses and refuses further steps until reset (§10.1)."""


@dataclass
class LegInfo:
    """Plan parameters a `Leg` does not carry (§7.6 `Leg` is the executable unit; these come from the assignment)."""

    people_count: int | None = None
    zone_id: str | None = None
    shelter_id: str | None = None
    crew_id: str | None = None
    target_cells: list[str] = field(default_factory=list)


LegKey = tuple[str, str, int]   # (resource_id, kind, start_step)


@dataclass
class StepReport:
    step: int
    events: list[dict[str, Any]] = field(default_factory=list)       # SimulationEvent-shaped {kind, data}
    applied_events: list[ScheduledEvent] = field(default_factory=list)


class Engine:
    def __init__(self, scenario: Scenario, world: WorldState, legs: list[Leg], *, seed: int,
                 leg_info: dict[LegKey, LegInfo] | None = None, check_invariants: bool = True):
        self.scenario, self.world, self.seed = scenario, world, seed
        self.params = scenario.fire_params
        self.grid = scenario.grid
        self.legs = sorted(legs, key=lambda l: (l.start_step, l.resource_id, l.end_step))
        self.leg_info = leg_info or {}
        self.check_invariants = check_invariants
        self.metrics = MetricsAccumulator()
        self.pending_out_of_service: set[str] = set()
        self.skipped: set[LegKey] = set()
        self._work_active_steps: dict[LegKey, int] = {}
        self._initial = {z.id: (z.unassisted_initial, z.assisted_initial) for z in world.zones.values()}

    # --- one step ------------------------------------------------------------------------------------------------------

    def step(self, events: list[ScheduledEvent] | None = None) -> StepReport:
        w = self.world
        t = w.step
        report = StepReport(step=t)

        for ev in events or []:                                                     # phase 1
            report.applied_events.append(apply_event(w, ev, pending_out_of_service=self.pending_out_of_service))
            report.events.append({"kind": "event.applied", "data": ev.model_dump(mode="json")})

        suppression: dict[str, float] = {}
        reductions: dict[str, int] = {}
        cleared: list[str] = []
        for leg in self._active_legs(t):                                            # phase 2
            self._progress(leg, t, suppression, reductions, cleared, report)

        for rid in cleared:                                                         # phase 3
            road = w.roads[rid]
            if road.clear_progress >= int(self.params["clear_road_steps"]) and road_status(road) == "CLOSED_CLEARABLE":
                road.status_override = "OPEN"
                report.events.append({"kind": "road.opened", "data": {"road_id": rid, "step": t}})
        for cid in fire.apply_reductions(w, reductions).extinguished:
            report.events.append({"kind": "cell.extinguished", "data": {"cell_id": cid, "step": t}})

        self._self_evacuate(t)                                                      # phase 4

        fe = fire.fire_phase(w, step=t, seed=self.seed, grid=self.grid, params=self.params,
                             suppression_by_cell=suppression)                       # phase 5
        report.events += [{"kind": "cell.ignited", "data": {"cell_id": c, "step": t}} for c in fe.ignited]
        report.events += [{"kind": "cell.extinguished", "data": {"cell_id": c, "step": t}} for c in fe.extinguished]

        accumulate_step(self.metrics, w, step=t, grid=self.grid, params=self.params, nodes=self.scenario.nodes)  # 6
        if self.check_invariants:                                                   # phase 7
            self.verify_invariants()
        w.step = t + 1
        return report

    def run_to(self, horizon: int, *, events_by_step: dict[int, list[ScheduledEvent]] | None = None,
               stop_on_event: bool = False) -> list[StepReport]:
        reports: list[StepReport] = []
        while self.world.step < horizon:
            evs = (events_by_step or {}).get(self.world.step, [])
            if evs and stop_on_event and reports:
                break
            reports.append(self.step(evs))
        return reports

    # --- resource progress (§5.4) ----------------------------------------------------------------------------------------

    def _active_legs(self, t: int) -> list[Leg]:
        return [l for l in self.legs if l.start_step <= t < l.end_step or (l.start_step == l.end_step == t)]

    def _progress(self, leg: Leg, t: int, suppression: dict[str, float], reductions: dict[str, int],
                  cleared: list[str], report: StepReport) -> None:
        w = self.world
        res = w.resources[leg.resource_id]
        key: LegKey = (leg.resource_id, leg.kind, leg.start_step)
        info = self.leg_info.get(key, LegInfo())
        if not res.available or key in self.skipped:
            return
        first, last = t == leg.start_step, t == leg.end_step - 1

        if leg.kind == "traverse":
            road = w.roads[leg.edge_id]  # type: ignore[index]
            if first:
                if road_status(road) != "OPEN":                   # closure blocks entry, not travel in progress (D-10)
                    self.skipped.add(key)
                    report.events.append({"kind": "task.skipped_unsafe", "data": {"resource_id": res.id, "road_id": road.id,
                                                                                   "reason": "ROAD_CLOSED", "step": t}})
                    return
                self._entry_nodes[res.id] = res.node or road.a
                res.node, res.edge, res.edge_steps_left = None, road.id, leg.end_step - leg.start_step
                report.events.append({"kind": "leg.started", "data": {"resource_id": res.id, "edge_id": road.id, "step": t}})
            if res.fuel_capacity is not None:
                res.fuel_used += 1                                 # driving steps burn fuel; waiting does not
            res.edge_steps_left = max(0, res.edge_steps_left - 1)
            if last:
                self._arrive(res, road, t, report)
        elif leg.kind == "load" and last:
            zone = w.zones.get(info.zone_id or leg.node or "")
            if zone is not None and res.aboard_crew is None:
                free = res.capacity - sum(res.aboard_people.values())
                want = info.people_count if info.people_count is not None else free
                boarded = max(0, min(free, zone.assisted_initial - zone.assisted_picked_up, want))
                zone.assisted_picked_up += boarded
                res.aboard_people[zone.id] = res.aboard_people.get(zone.id, 0) + boarded
                report.events.append({"kind": "leg.completed", "data": {"resource_id": res.id, "kind": "load",
                                                                        "zone_id": zone.id, "people": boarded, "step": t}})
        elif leg.kind == "unload" and last:
            shelter = w.shelters.get(info.shelter_id or leg.node or "")
            if shelter is not None:
                aboard = sum(res.aboard_people.values())
                room = shelter.capacity - shelter.background - shelter.arrivals
                moved = min(aboard, room)
                if moved < aboard:                                 # never exceed capacity (§5.6); the rest stays aboard
                    report.events.append({"kind": "task.skipped_unsafe", "data": {"resource_id": res.id, "shelter_id": shelter.id,
                                                                                   "reason": "SHELTER_FULL", "step": t}})
                shelter.arrivals += moved
                self._remove_aboard(res, moved)
                # §5.8: a vehicle failing with passengers aboard goes out of service after its next completed unload.
                if res.id in self.pending_out_of_service and sum(res.aboard_people.values()) == 0:
                    res.available = False
                    self.pending_out_of_service.discard(res.id)
                report.events.append({"kind": "people.sheltered", "data": {"resource_id": res.id, "shelter_id": shelter.id,
                                                                           "people": moved, "step": t}})
        elif leg.kind == "board" and last:
            crew = w.resources.get(info.crew_id or "")
            if crew is not None and crew.node == res.node and sum(res.aboard_people.values()) == 0:
                res.aboard_crew = crew.id
        elif leg.kind == "drop" and last:
            crew = w.resources.get(res.aboard_crew or info.crew_id or "")
            if crew is not None:
                crew.node = res.node
                res.aboard_crew = None
        elif leg.kind == "work":
            if leg.edge_id is not None:                            # clear_road
                w.roads[leg.edge_id].clear_progress = min(int(self.params["clear_road_steps"]),
                                                          w.roads[leg.edge_id].clear_progress + 1)
                cleared.append(leg.edge_id)
            else:                                                  # contain
                targets = info.target_cells
                if first and any(w.cells[c].intensity >= int(self.params["max_intensity"]) for c in targets if c in w.cells):
                    self.skipped.add(key)                          # §5.5 crew safety guard: hold, do not reroute
                    report.events.append({"kind": "task.skipped_unsafe", "data": {"resource_id": res.id, "cells": targets,
                                                                                   "reason": "TARGET_TOO_INTENSE", "step": t}})
                    return
                hand = res.engine_node is not None and res.node != res.engine_node
                active = self._work_active_steps.get(key, 0) + 1
                self._work_active_steps[key] = active
                for c in targets:
                    cell = w.cells.get(c)
                    if cell is None:
                        continue
                    s = fire.suppression(cell, [(res.id, hand)], self.params)
                    suppression[c] = max(suppression.get(c, 0.0), s)
                    if active % int(self.params["reduce_every"]) == 0:
                        reductions[c] = reductions.get(c, 0) + 1
        elif leg.kind == "refuel" and last:
            res.fuel_used = 0

    def _arrive(self, res, road, t: int, report: StepReport) -> None:
        entry = self._entry_nodes.get(res.id, road.a)
        far = road.b if entry == road.a else road.a
        if res.type == "crew" and res.engine_node is not None and res.engine_node == entry:
            res.engine_node = far        # §5.3: a crew driving its own engine takes the engine with it
        res.node, res.edge, res.edge_steps_left = far, None, 0
        if res.aboard_crew:
            crew = self.world.resources.get(res.aboard_crew)
            if crew is not None:
                crew.node = far
        if res.id in self.pending_out_of_service and sum(res.aboard_people.values()) == 0:
            res.available = False
            self.pending_out_of_service.discard(res.id)
        report.events.append({"kind": "leg.completed", "data": {"resource_id": res.id, "edge_id": road.id, "node": far, "step": t}})

    @property
    def _entry_nodes(self) -> dict[str, str]:
        """Node each resource entered its current edge from, so arrival resolves the far end deterministically."""
        d = getattr(self, "_entry_nodes_store", None)
        if d is None:
            d = self._entry_nodes_store = {}
        return d

    def _remove_aboard(self, res, count: int) -> None:
        for zone_id in sorted(res.aboard_people):
            take = min(count, res.aboard_people[zone_id])
            res.aboard_people[zone_id] -= take
            count -= take
            if res.aboard_people[zone_id] == 0:
                del res.aboard_people[zone_id]
            if count == 0:
                break

    # --- phases 4 and 7 ---------------------------------------------------------------------------------------------------

    def _self_evacuate(self, t: int) -> None:
        w = self.world
        per_step = int(self.params["self_evac_per_step"])
        for zone in w.zones.values():
            has_open_road = any(road_status(r) == "OPEN" and zone.id in (r.a, r.b) for r in w.roads.values())
            if not has_open_road:
                continue
            remaining = zone.unassisted_initial - zone.self_evacuated
            zone.self_evacuated += min(per_step, remaining)

    def verify_invariants(self) -> None:
        """§5.6 conservation, checked after every step (FR-004)."""
        w = self.world
        aboard_from: dict[str, int] = {}
        for r in w.resources.values():
            for z, n in r.aboard_people.items():
                aboard_from[z] = aboard_from.get(z, 0) + n
            total = sum(r.aboard_people.values())
            if not (0 <= total <= r.capacity):
                raise InvariantError(f"{r.id} aboard {total} outside [0, {r.capacity}]")
            if r.fuel_capacity is not None and r.fuel_used > r.fuel_capacity:
                raise InvariantError(f"{r.id} fuel below zero")
            if total > 0 and r.aboard_crew:
                raise InvariantError(f"{r.id} carries civilians and a crew")
            if (r.node is None) == (r.edge is None):
                raise InvariantError(f"{r.id} must be at exactly one of node/edge (node={r.node}, edge={r.edge})")
        sheltered_total = sum(s.arrivals for s in w.shelters.values())
        picked_total = sum(z.assisted_picked_up for z in w.zones.values())
        if picked_total != sheltered_total + sum(aboard_from.values()):
            raise InvariantError(f"assisted picked up {picked_total} != sheltered {sheltered_total} + aboard {sum(aboard_from.values())}")
        for z in w.zones.values():
            u0, a0 = self._initial[z.id]
            if unassisted_in_zone(z.model_dump()) + z.self_evacuated != u0 or z.self_evacuated < 0:
                raise InvariantError(f"zone {z.id} unassisted conservation broken")
            if assisted_waiting(z.model_dump()) < 0 or z.assisted_picked_up > a0:
                raise InvariantError(f"zone {z.id} assisted conservation broken")
        for s in w.shelters.values():
            if s.background + s.arrivals > s.capacity:
                raise InvariantError(f"shelter {s.id} over capacity")


def leg_info_from_assignments(assignments: list[Any], legs: list[Leg]) -> dict[LegKey, LegInfo]:
    """Attach assignment parameters to the legs `plans.expand` produced for them (matched by resource + kind + start)."""
    info: dict[LegKey, LegInfo] = {}
    by_resource: dict[str, list[Any]] = {}
    for a in assignments:
        by_resource.setdefault(a.resource_id, []).append(a)
    for leg in legs:
        if leg.kind not in ("load", "unload", "board", "drop", "work"):
            continue
        for a in by_resource.get(leg.resource_id, []):
            matches = ((leg.kind == "load" and a.task == "load") or (leg.kind == "unload" and a.task == "unload")
                       or (leg.kind in ("board", "drop") and a.task == "transfer_crew")
                       or (leg.kind == "work" and a.task in ("contain", "clear_road")))
            if matches and (leg.resource_id, leg.kind, leg.start_step) not in info and _leg_belongs(a, leg):
                info[(leg.resource_id, leg.kind, leg.start_step)] = LegInfo(
                    people_count=a.people_count, zone_id=a.zone_id, shelter_id=a.shelter_id, crew_id=a.crew_id,
                    target_cells=list(a.target_cells))
                break
    return info


def _leg_belongs(a: Any, leg: Leg) -> bool:
    start = getattr(a, "start_step", None)
    end = getattr(a, "end_step", None)
    if start is None or end is None:
        return True
    return start <= leg.start_step < max(end, start + 1)
