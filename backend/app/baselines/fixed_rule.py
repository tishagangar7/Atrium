"""Fixed-rule baseline (PRD §11.2 "Fixed-rule policy", FR-060).

A disclosed, deterministic policy on the union view (all evidence that exists at the decision point, B§12
fairness). Same inputs always give the same plan. It never calls a model and never reads a forecast metric to
choose between options: it greedily follows the four rules below and keeps a step only if the simulator's own
validator accepts the plan with it (hard constraints stay authoritative).

1. Order zones by (hazard desc, assisted_waiting desc, zone_id).
2. Repeatedly give the earliest-free bus (then V1) an evacuation trip to the first zone with assisted residents
   waiting: shortest open route, load, nearest shelter with remaining capacity, unload; repeat until nobody waits
   or the horizon is reached. V1 always carries people, never crews.
3. Each crew contains the burning cells nearest the most-populated threatened zone it can reach on engine-capable
   roads; if a zone with assisted residents has no open route and an idle crew can reach a CLOSED_CLEARABLE road on
   its path, that crew clears it first.
4. Refuel any vehicle whose next trip exceeds its fuel.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from app.models import AssignmentDraft
from app.sim.contract import BeliefView, SimService
from app.sim.world import cell_xy, road_status

METHOD = "fixed_rule"
CONTAIN_TARGETS_MAX = 3          # §5.4: up to 3 target cells per contain task
CONTAIN_INTENSITY_MAX = 3        # §5.4: each target ≤ 3 at task start
CONTAIN_STEPS = 12               # policy choice: hold the line for 12 steps (≥ the §5.4 minimum of 3)
MAX_TRIPS = 20                   # safety bound on the greedy loop (each trip adds 4 assignments)


def _draft(resource: str, task: str, **kw: Any) -> AssignmentDraft:
    return AssignmentDraft(
        resource_id=resource, task=task, origin=kw.get("origin"), destination=kw.get("destination"),
        route_ids=list(kw.get("route_ids", [])), start_step=kw.get("start_step"),
        people_count=kw.get("people_count"), zone_id=kw.get("zone_id"), shelter_id=kw.get("shelter_id"),
        crew_id=kw.get("crew_id"), target_cells=list(kw.get("target_cells", [])), edge_id=kw.get("edge_id"),
        duration_steps=kw.get("duration_steps"))


@dataclass
class _Vehicle:
    id: str
    node: str
    capacity: int
    fuel: int | None           # remaining driving steps; None = not modelled
    free_at: int = 0
    done: bool = False


class FixedRulePlanner:
    """`plan(view)` returns assignment drafts; the caller normalizes/hashes/applies like any other plan."""

    def __init__(self, sim: SimService):
        self.sim = sim

    # --- public ---------------------------------------------------------------------------------------------------

    def plan(self, view: BeliefView, *, locked: list[AssignmentDraft] | None = None) -> list[AssignmentDraft]:
        world = view.world
        plan: list[AssignmentDraft] = list(locked or [])
        horizon = int(world.get("horizon", 60))
        zones = self._ordered_zones(world)
        # Read every count before any validation call: the validator is not guaranteed to leave its input untouched.
        waiting = {z: int(world["zones"][z]["assisted_waiting"]) for z in zones}
        remaining = {s: int(sh["remaining"]) for s, sh in world["shelters"].items()}
        vehicles = self._vehicles(world)

        plan = self._crews(view, plan, zones)                                   # rule 3 (clearing first)

        for _ in range(MAX_TRIPS):                                               # rule 2
            if not any(waiting.values()):
                break
            active = [v for v in vehicles if not v.done]
            if not active:
                break
            vehicle = min(active, key=lambda v: (v.free_at, v.id != "B1", v.id != "B2", v.id))
            zone = next((z for z in zones if waiting[z] > 0 and self._route(view, vehicle, vehicle.node, z)), None)
            if zone is None:
                vehicle.done = True
                continue
            trip = self._trip(view, vehicle, zone, waiting[zone], remaining)
            if trip is None:
                vehicle.done = True
                continue
            steps, people, shelter, travel = trip
            candidate = [*plan, *steps]
            timing = self._timing(view, candidate)
            if self.sim.validate_plan(view, candidate) or timing is None or timing[-1]["end_step"] > horizon:
                vehicle.done = True
                continue
            plan = candidate
            waiting[zone] -= people
            remaining[shelter] -= people
            vehicle.node = shelter
            vehicle.free_at = timing[-1]["end_step"]
            if vehicle.fuel is not None:
                vehicle.fuel = travel["fuel_after"]
        return plan

    # --- rule 1 ---------------------------------------------------------------------------------------------------

    @staticmethod
    def _ordered_zones(world: dict[str, Any]) -> list[str]:
        zones = world["zones"]
        return sorted(zones, key=lambda z: (-int(zones[z]["hazard"]), -int(zones[z]["assisted_waiting"]), z))

    # --- rule 2 + 4 -----------------------------------------------------------------------------------------------

    @staticmethod
    def _vehicles(world: dict[str, Any]) -> list[_Vehicle]:
        out = []
        for rid, r in sorted(world["resources"].items()):
            if r["type"] not in ("bus", "transport") or not r.get("available", True) or r.get("node") is None:
                continue
            out.append(_Vehicle(id=rid, node=r["node"], capacity=int(r["capacity"]), fuel=r.get("fuel_remaining")))
        return out

    def _route(self, view: BeliefView, vehicle: _Vehicle, origin: str, destination: str):
        found = self.sim.find_routes(view, origin, destination, resource_id=vehicle.id)
        return found[0] if found else None

    def _trip(self, view: BeliefView, v: _Vehicle, zone: str, waiting: int, remaining: dict[str, int]):
        people = min(v.capacity, waiting)
        out = self._route(view, v, v.node, zone)
        if out is None or people <= 0:
            return None
        shelters = []
        for s, room in remaining.items():
            if room < people:
                continue
            back = self._route(view, v, zone, s)
            if back is not None:
                shelters.append((back.travel_steps, s, back))
        if not shelters:
            return None
        _, shelter, back = min(shelters)
        steps: list[AssignmentDraft] = []
        need = out.travel_steps + back.travel_steps
        fuel = v.fuel
        start = v.node
        if fuel is not None and need > fuel:                                     # rule 4
            if start != "BASE":
                to_base = self._route(view, v, start, "BASE")
                if to_base is None or to_base.travel_steps > fuel:
                    return None
                steps.append(_draft(v.id, "drive", origin=start, destination="BASE", route_ids=to_base.route_ids))
                start = "BASE"
            steps.append(_draft(v.id, "refuel", origin="BASE", destination="BASE"))
            fuel = int(view.world["resources"][v.id]["fuel_capacity"])
            out = self._route(view, v, start, zone)
            if out is None or out.travel_steps + back.travel_steps > fuel:
                return None
            need = out.travel_steps + back.travel_steps
        if start != zone:
            steps.append(_draft(v.id, "drive", origin=start, destination=zone, route_ids=out.route_ids))
        steps.append(_draft(v.id, "load", origin=zone, destination=zone, people_count=people, zone_id=zone))
        steps.append(_draft(v.id, "drive", origin=zone, destination=shelter, route_ids=back.route_ids))
        steps.append(_draft(v.id, "unload", origin=shelter, destination=shelter, shelter_id=shelter))
        return steps, people, shelter, {"fuel_after": None if fuel is None else fuel - need}

    def _timing(self, view: BeliefView, plan: list[AssignmentDraft]):
        try:
            return self.sim.plan_timing(view, plan)
        except Exception:                                                         # unexpandable → reject the step
            return None

    # --- rule 3 ---------------------------------------------------------------------------------------------------

    def _crews(self, view: BeliefView, plan: list[AssignmentDraft], zones: list[str]) -> list[AssignmentDraft]:
        world = view.world
        crews = [rid for rid, r in sorted(world["resources"].items())
                 if r["type"] == "crew" and r.get("available", True) and r.get("node")]
        busy: set[str] = set()

        # Clearing first: a zone with assisted residents and no open bus route whose path a clearable road would open.
        for zone in zones:
            if int(world["zones"][zone]["assisted_waiting"]) <= 0:
                continue
            if self.sim.find_routes(view, "BASE", zone, resource_id=self._any_bus(world) or crews[0]):
                continue
            road = self._clearable_on_path(view, zone)
            if road is None:
                continue
            for crew in crews:
                if crew in busy:
                    continue
                candidate = self._crew_to(view, plan, crew, [world["roads"][road]["a"], world["roads"][road]["b"]],
                                          _draft(crew, "clear_road", edge_id=road))
                if candidate is not None:
                    plan, busy = candidate, busy | {crew}
                    break

        # Containment: burning cells nearest the most-populated threatened zone, reachable on engine roads.
        threatened = [z for z in zones if int(world["zones"][z]["hazard"]) > 0] or zones
        target_zone = max(threatened, key=lambda z: (int(world["zones"][z]["unassisted_in_zone"])
                                                     + int(world["zones"][z]["assisted_waiting"]), z))
        zx, zy = cell_xy(world["zones"][target_zone]["cell"])
        burning = [cid for cid, c in sorted(world["cells"].items())
                   if c["state"] == "BURNING" and int(c["intensity"]) <= CONTAIN_INTENSITY_MAX]
        claimed: set[str] = set()
        for crew in crews:
            if crew in busy:
                continue
            options = []
            for node, ncell in sorted(world["nodes"].items()):
                nx, ny = cell_xy(ncell)
                near = [c for c in burning if c not in claimed
                        and max(abs(cell_xy(c)[0] - nx), abs(cell_xy(c)[1] - ny)) <= 1]
                if not near:
                    continue
                near.sort(key=lambda c: (max(abs(cell_xy(c)[0] - zx), abs(cell_xy(c)[1] - zy)), c))
                cells = near[:CONTAIN_TARGETS_MAX]
                dist = min(max(abs(cell_xy(c)[0] - zx), abs(cell_xy(c)[1] - zy)) for c in cells)
                options.append((dist, node, cells))
            for _, node, cells in sorted(options):
                candidate = self._crew_to(view, plan, crew, [node],
                                          _draft(crew, "contain", target_cells=cells, duration_steps=CONTAIN_STEPS))
                if candidate is not None:
                    plan, busy = candidate, busy | {crew}
                    claimed |= set(cells)
                    break
        return plan

    def _crew_to(self, view: BeliefView, plan: list[AssignmentDraft], crew: str, nodes: list[str],
                 task: AssignmentDraft) -> list[AssignmentDraft] | None:
        here = view.world["resources"][crew]["node"]
        for node in nodes:
            steps: list[AssignmentDraft] = []
            if here != node:
                found = self.sim.find_routes(view, here, node, resource_id=crew)
                if not found:
                    continue
                steps.append(_draft(crew, "drive", origin=here, destination=node, route_ids=found[0].route_ids))
            candidate = [*plan, *steps, task]
            timing = self._timing(view, candidate)
            if not self.sim.validate_plan(view, candidate) and timing is not None \
                    and timing[-1]["end_step"] <= int(view.world.get("horizon", 60)):
                return candidate
        return None

    @staticmethod
    def _any_bus(world: dict[str, Any]) -> str | None:
        return next((rid for rid, r in sorted(world["resources"].items()) if r["type"] == "bus"), None)

    def _clearable_on_path(self, view: BeliefView, zone: str) -> str | None:
        """A CLOSED_CLEARABLE road on the shortest path BASE → zone if clearable roads were open."""
        world = copy.deepcopy(view.world)
        clearable = [rid for rid, r in world["roads"].items() if road_status(r) == "CLOSED_CLEARABLE"]
        for rid in clearable:
            world["roads"][rid]["status_override"] = "OPEN"
        bus = self._any_bus(world)
        if bus is None:
            return None
        trial = BeliefView(agent=view.agent, world=world, held_evidence=view.held_evidence,
                           state_version=view.state_version, step=view.step)
        found = self.sim.find_routes(trial, "BASE", zone, resource_id=bus)
        if not found:
            return None
        return next((rid for rid in found[0].route_ids if rid in clearable), None)
