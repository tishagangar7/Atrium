"""Plan expansion: assignments → executable legs with deterministic timing (PRD §5.4, §5.7 road capacity, §7.6).

Works on a view's world dict (statics possibly masked, §5.9), so the same code gives each agent its own forecast and
the gate its authoritative one. It tracks, per resource, where it is, what is aboard and how much fuel it has used,
and schedules edge entries against road capacity with the §5.7 priority rule (earlier requested `start_step`, then
lower `resource_id`). Waiting never burns fuel. Hard-constraint problems found while expanding are reported as
`Violation`s (validate.py adds the structural ones). Runtime numbers (`end_step`, `wait_steps`) come from here (§7.6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models import Assignment, AssignmentDraft, Leg, Violation
from app.sim.routes import route_is_connected
from app.sim.world import cells_within, road_status

BASE_NODE = "BASE"
AnyAssignment = Assignment | AssignmentDraft


@dataclass
class ResourceState:
    node: str | None
    engine_node: str | None
    is_crew: bool
    kind: str                        # resource type: "bus" | "transport" | "crew"
    capacity: int
    fuel_capacity: int | None
    fuel_used: int
    aboard_people: int
    aboard_crew: str | None
    available: bool
    free_at: int                     # first step the resource is free for its next assignment

    @property
    def hand_crew(self) -> bool:
        return self.is_crew and self.engine_node is not None and self.node != self.engine_node


@dataclass
class Expansion:
    legs: list[Leg] = field(default_factory=list)
    timing: list[dict[str, int]] = field(default_factory=list)        # per assignment: start_step, end_step, wait_steps
    violations: list[Violation] = field(default_factory=list)
    shelter_use: dict[str, int] = field(default_factory=dict)         # planned arrivals per shelter
    wait_risk_legs: int = 0
    contain_targets: dict[int, list[str]] = field(default_factory=dict)  # assignment order -> target cells
    end_step: int = 0


def expand(assignments: list[AnyAssignment], world: dict[str, Any], params: dict[str, float], *,
           current_step: int | None = None) -> Expansion:
    step0 = world["step"] if current_step is None else current_step
    horizon = int(world.get("horizon", 60))
    grid = tuple(world.get("grid", (10, 6)))
    exp = Expansion()
    states = {rid: _initial_state(r, step0) for rid, r in world["resources"].items()}
    occupancy: dict[str, list[tuple[int, int]]] = {}                 # road id -> [(start, end)) traversals
    shelter_planned: dict[str, int] = {}
    seen_loads: set[int] = set()
    # Planned effects are tracked here, never written into `world`: validation/evaluation must not mutate its input
    # (invariant 4; a belief view handed to a tool must come back unchanged).
    pickups: dict[str, int] = {}                                     # zone id -> residents planned to board
    cleared: dict[str, int] = {}                                     # road id -> step its clear_road work ends

    # Scheduling order: assignments for one resource run in the order given (§5.4); across resources the next one
    # processed is the earliest effective start (max(requested, resource free)), ties by resource id then list index —
    # the §5.7 priority rule for competing edge entries.
    queues: dict[str, list[int]] = {}
    for i, a in enumerate(assignments):
        queues.setdefault(a.resource_id, []).append(i)
    timing: dict[int, dict[str, int]] = {}

    for _ in range(len(assignments)):
        candidates = []
        for rid, idxs in queues.items():
            if not idxs:
                continue
            nxt = assignments[idxs[0]]
            free = states[rid].free_at if rid in states else step0
            requested = nxt.start_step if nxt.start_step is not None else free
            candidates.append((max(requested, free, step0), rid, idxs[0]))
        _, rid, i = min(candidates)
        queues[rid].pop(0)
        a = assignments[i]
        st = states.get(a.resource_id)
        if st is None:
            exp.violations.append(_v("UNKNOWN_RESOURCE", i, a.resource_id, None, f"no resource {a.resource_id!r}"))
            timing[i] = {"start_step": step0, "end_step": step0, "wait_steps": 0}
            continue
        if not st.available:
            exp.violations.append(_v("RESOURCE_UNAVAILABLE", i, a.resource_id, None, "OUT_OF_SERVICE"))
        if getattr(a, "locked", False) and a.task == "drive" and st.node is None and len(a.route_ids) == 1:
            # §5.8 locked leg: the vehicle is already on this edge. It is not re-entered or re-checked for entry; it
            # arrives at `end_step` and the resource is busy until then (no false RESOURCE_DOUBLE_BOOKED).
            exp.legs.append(Leg(resource_id=a.resource_id, kind="traverse", edge_id=a.route_ids[0], node=None,
                                start_step=a.start_step, end_step=a.end_step))
            st.node, st.free_at = a.destination, max(st.free_at, a.end_step)
            timing[i] = {"start_step": a.start_step, "end_step": a.end_step, "wait_steps": 0}
            exp.end_step = max(exp.end_step, a.end_step)
            continue
        requested = a.start_step if a.start_step is not None else st.free_at
        if a.start_step is not None and a.start_step < st.free_at:
            exp.violations.append(_v("RESOURCE_DOUBLE_BOOKED", i, a.resource_id, None,
                                     f"start_step {a.start_step} before previous end {st.free_at}"))
        start = max(requested, st.free_at, step0)
        t, waits = start, 0

        if a.task in ("drive", "transfer_crew"):
            t, waits = _expand_drive(a, i, st, states, world, params, occupancy, exp, t, grid, cleared)
        elif a.task == "load":
            t = _expand_load(a, i, st, world, params, exp, t, pickups)
        elif a.task == "unload":
            t = _expand_unload(a, i, st, world, params, exp, shelter_planned, t)
        elif a.task == "contain":
            t = _expand_contain(a, i, st, world, params, exp, t, grid)
        elif a.task == "clear_road":
            t = _expand_clear_road(a, i, st, world, params, exp, t, cleared)
        elif a.task == "refuel":
            if st.node != BASE_NODE:
                exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, f"refuel only at {BASE_NODE}, resource at {st.node}"))
            end = t + int(params["refuel_steps"])
            exp.legs.append(Leg(resource_id=a.resource_id, kind="refuel", edge_id=None, node=st.node, start_step=t, end_step=end))
            st.fuel_used = 0
            t = end
        elif a.task == "hold":
            pass
        else:
            exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, f"unknown task {a.task!r}"))

        if t > horizon:
            exp.violations.append(_v("SCHEDULE_OVERRUN", i, a.resource_id, None, f"ends at step {t} > horizon {horizon}"))
        if waits >= int(params.get("wait_risk_steps", 3)):
            exp.wait_risk_legs += 1
        st.free_at = max(st.free_at, t)
        timing[i] = {"start_step": start, "end_step": t, "wait_steps": waits}
        exp.end_step = max(exp.end_step, t)

    exp.timing = [timing[i] for i in range(len(assignments))]
    exp.shelter_use = dict(shelter_planned)
    exp.legs.sort(key=lambda l: (l.start_step, l.resource_id, l.end_step))
    return exp


# --- per-task expansion ---------------------------------------------------------------------------------------------

def _expand_drive(a, i, st: ResourceState, states, world, params, occupancy, exp: Expansion, t: int,
                  grid, cleared: dict[str, int]) -> tuple[int, int]:
    origin = a.origin or st.node
    if origin is None:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, "resource is on an edge; no origin"))
        return t, 0
    if st.node is not None and origin != st.node:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, f"origin {origin} but resource is at {st.node}"))
    if a.task == "transfer_crew":
        if st.kind != "transport":   # §5.3: only V1-type transports carry a crew; buses and crews cannot
            exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, "only a transport can transfer a crew"))
        crew = states.get(a.crew_id or "")
        if crew is None:
            exp.violations.append(_v("UNKNOWN_RESOURCE", i, a.resource_id, None, f"no crew {a.crew_id!r}"))
        elif crew.node != origin:
            exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, f"crew {a.crew_id} is at {crew.node}, not {origin}"))
        if st.aboard_people > 0:
            exp.violations.append(_v("MIXED_PAYLOAD", i, a.resource_id, None, "civilians aboard while boarding a crew"))
        board_end = t + int(params["transfer_board_steps"])
        exp.legs.append(Leg(resource_id=a.resource_id, kind="board", edge_id=None, node=origin, start_step=t, end_step=board_end))
        t = board_end
        st.aboard_crew = a.crew_id

    ok, end_node, bad = route_is_connected(world, origin, a.route_ids)
    if not ok:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, bad, f"road {bad} does not continue from {end_node}"))
    if a.destination and ok and end_node != a.destination:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, f"route ends at {end_node}, not {a.destination}"))

    waits = 0
    node = origin
    travel_total = 0
    for rid in a.route_ids:
        r = world["roads"].get(rid)
        if r is None:
            break
        nxt = r["b"] if r["a"] == node else r["a"] if r["b"] == node else None
        if nxt is None:
            break
        if st.is_crew and not r["engine_ok"]:
            exp.violations.append(_v("ROAD_NOT_ENGINE_CAPABLE", i, a.resource_id, rid, f"{rid} is a narrow fire road"))
        entry, wait = _admit(occupancy, rid, int(r["capacity"]), t, int(r["travel_steps"]))
        # A CLOSED_CLEARABLE road becomes OPEN when a planned clear_road on it finishes (§5.4); entry after that is fine.
        opened = road_status(r) == "CLOSED_CLEARABLE" and rid in cleared and entry >= cleared[rid]
        if road_status(r) != "OPEN" and not opened:
            exp.violations.append(_v("ROAD_CLOSED", i, a.resource_id, rid, f"{rid} is {road_status(r)}"))
        waits += wait
        exp.legs.append(Leg(resource_id=a.resource_id, kind="traverse", edge_id=rid, node=None, start_step=entry,
                            end_step=entry + int(r["travel_steps"])))
        t = entry + int(r["travel_steps"])
        travel_total += int(r["travel_steps"])
        node = nxt
    if st.fuel_capacity is not None:
        st.fuel_used += travel_total
        if st.fuel_used > st.fuel_capacity:
            exp.violations.append(_v("FUEL_INSUFFICIENT", i, a.resource_id, None,
                                     f"needs {st.fuel_used} driving steps, capacity {st.fuel_capacity}"))
    with_engine = st.is_crew and st.engine_node is not None and st.engine_node == st.node
    st.node = node if ok else st.node
    if with_engine and ok:
        st.engine_node = st.node      # §5.3: a crew driving its own engine takes the engine with it
    if a.task == "transfer_crew":
        drop_end = t + int(params["transfer_drop_steps"])
        exp.legs.append(Leg(resource_id=a.resource_id, kind="drop", edge_id=None, node=node, start_step=t, end_step=drop_end))
        t = drop_end
        crew = states.get(a.crew_id or "")
        if crew is not None:
            crew.node = node
            crew.free_at = max(crew.free_at, t)
        st.aboard_crew = None
    return t, waits


def _expand_load(a, i, st: ResourceState, world, params, exp: Expansion, t: int, pickups: dict[str, int]) -> int:
    zone = world["zones"].get(a.zone_id or st.node or "")
    if zone is None or (st.node is not None and zone["id"] != st.node):
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None,
                                 f"load needs the vehicle at zone {a.zone_id!r}; it is at {st.node}"))
    if st.is_crew:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, "crews do not load civilians"))
    if st.aboard_crew:
        exp.violations.append(_v("MIXED_PAYLOAD", i, a.resource_id, None, "crew aboard while loading civilians"))
    free = st.capacity - st.aboard_people
    want = a.people_count if a.people_count is not None else free
    if want > free:
        exp.violations.append(_v("VEHICLE_OVER_CAPACITY", i, a.resource_id, None,
                                 f"{want} requested, {free} free seats of {st.capacity}"))
    waiting = (zone["assisted_waiting"] - pickups.get(zone["id"], 0)) if zone is not None else 0
    boarded = max(0, min(free, waiting, want))
    st.aboard_people += boarded
    if zone is not None:
        pickups[zone["id"]] = pickups.get(zone["id"], 0) + boarded   # later loads from the same zone see fewer
    end = t + int(params["load_steps"])
    exp.legs.append(Leg(resource_id=a.resource_id, kind="load", edge_id=None, node=st.node, start_step=t, end_step=end))
    return end


def _expand_unload(a, i, st: ResourceState, world, params, exp: Expansion, planned: dict[str, int], t: int) -> int:
    shelter = world["shelters"].get(a.shelter_id or st.node or "")
    if shelter is None or (st.node is not None and shelter["id"] != st.node):
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None,
                                 f"unload needs the vehicle at shelter {a.shelter_id!r}; it is at {st.node}"))
    else:
        remaining = shelter["capacity"] - shelter["background"] - shelter["arrivals"] - planned.get(shelter["id"], 0)
        if st.aboard_people > remaining:
            exp.violations.append(_v("SHELTER_OVER_CAPACITY", i, a.resource_id, None,
                                     f"{st.aboard_people} aboard, {remaining} places left at {shelter['id']}"))
        planned[shelter["id"]] = planned.get(shelter["id"], 0) + st.aboard_people
    st.aboard_people = 0
    end = t + int(params["unload_steps"])
    exp.legs.append(Leg(resource_id=a.resource_id, kind="unload", edge_id=None, node=st.node, start_step=t, end_step=end))
    return end


def _expand_contain(a, i, st: ResourceState, world, params, exp: Expansion, t: int, grid) -> int:
    if not st.is_crew:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, "only crews contain fire"))
    if st.node is None:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, "crew is on an edge"))
    node_cell = world["nodes"].get(st.node or "")
    reach = int(params.get("contain_reach", 1))
    targets = list(a.target_cells)
    if not targets or len(targets) > int(params.get("contain_max_targets", 3)):
        exp.violations.append(_v("TARGET_OUT_OF_REACH", i, a.resource_id, None,
                                 f"contain needs 1..{int(params.get('contain_max_targets', 3))} target cells"))
    allowed = set(cells_within(node_cell, reach, grid)) if node_cell else set()
    for c in targets:
        if c not in world["cells"] or c not in allowed:
            exp.violations.append(_v("TARGET_OUT_OF_REACH", i, a.resource_id, None, f"{c} is not within {reach} of {st.node}"))
        elif world["cells"][c]["intensity"] > int(params.get("contain_max_intensity_at_start", 3)):
            exp.violations.append(_v("TARGET_TOO_INTENSE", i, a.resource_id, None,
                                     f"{c} has intensity {world['cells'][c]['intensity']} at task start"))
    duration = a.duration_steps if a.duration_steps is not None else int(params["contain_min_steps"])
    if duration < int(params["contain_min_steps"]):
        exp.violations.append(_v("TARGET_OUT_OF_REACH", i, a.resource_id, None,
                                 f"contain duration {duration} < {int(params['contain_min_steps'])}"))
    end = t + max(duration, 0)
    exp.contain_targets[i] = targets
    exp.legs.append(Leg(resource_id=a.resource_id, kind="work", edge_id=None, node=st.node, start_step=t, end_step=end))
    return end


def _expand_clear_road(a, i, st: ResourceState, world, params, exp: Expansion, t: int,
                       cleared: dict[str, int]) -> int:
    road = world["roads"].get(a.edge_id or "")
    if not st.is_crew:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, None, "only crews clear roads"))
    if road is None:
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, a.edge_id, f"unknown road {a.edge_id!r}"))
        return t
    if st.node not in (road["a"], road["b"]):
        exp.violations.append(_v("WRONG_LOCATION", i, a.resource_id, road["id"],
                                 f"crew at {st.node}, not at an endpoint of {road['id']}"))
    if road_status(road) != "CLOSED_CLEARABLE":
        exp.violations.append(_v("ROAD_CLOSED", i, a.resource_id, road["id"],
                                 f"{road['id']} is {road_status(road)}; only CLOSED_CLEARABLE roads can be cleared"))
    remaining = max(0, int(params["clear_road_steps"]) - int(road.get("clear_progress", 0)))
    end = t + remaining
    if road_status(road) == "CLOSED_CLEARABLE":
        cleared[road["id"]] = min(cleared.get(road["id"], end), end)
    exp.legs.append(Leg(resource_id=a.resource_id, kind="work", edge_id=road["id"], node=st.node, start_step=t, end_step=end))
    return end


# --- helpers ----------------------------------------------------------------------------------------------------------

def _admit(occupancy: dict[str, list[tuple[int, int]]], road_id: str, capacity: int, t: int,
           travel: int) -> tuple[int, int]:
    """Earliest entry ≥ t such that every step of [entry, entry+travel) has < capacity vehicles on the edge."""
    intervals = occupancy.setdefault(road_id, [])
    entry = t
    while True:
        if all(sum(1 for s, e in intervals if s <= step < e) < capacity for step in range(entry, entry + travel)):
            intervals.append((entry, entry + travel))
            return entry, entry - t
        entry += 1


def _initial_state(r: dict[str, Any], step0: int) -> ResourceState:
    return ResourceState(node=r["node"], engine_node=r.get("engine_node"), is_crew=r["type"] == "crew", kind=r["type"],
                         capacity=int(r["capacity"]), fuel_capacity=r.get("fuel_capacity"), fuel_used=int(r.get("fuel_used", 0)),
                         aboard_people=sum(r.get("aboard_people", {}).values()), aboard_crew=r.get("aboard_crew"),
                         available=bool(r.get("available", True)),
                         free_at=step0 + int(r.get("edge_steps_left", 0) or 0))


def _v(code: str, order: int, resource_id: str | None, road_id: str | None, detail: str) -> Violation:
    return Violation(code=code, assignment_order=order, resource_id=resource_id, road_id=road_id, detail=detail)  # type: ignore[arg-type]
