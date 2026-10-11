"""Typed simulator stub for WS-B development (PRD §12.2 "Independent start", §12.3 B1).

SIMULATOR STUB — placeholder numbers, not physics. Madhav's `app.sim` (WS-A) is the real implementation of the
`SimService` contract below (reset, step, apply_event, find_routes, validate_plan, evaluate_plan,
build_belief_view). This stub exists so actors, router and tests can be built before A3 lands; it is replaced at
G1 and must never be presented as live output. What it does model faithfully, because WS-B logic depends on it:

  * the §5.2 map (nodes, roads R1–R11, travel steps, capacity, engine capability, true initial status),
  * the §5.3 resources, §5.9 evidence items with holders, and belief-view masking of un-held statics
    (AC-024: Evacuation's `find_routes` sees R2 as OPEN while Logistics' does not),
  * structural validation codes a plan can trip without physics: UNKNOWN_RESOURCE, RESOURCE_UNAVAILABLE,
    ROAD_CLOSED, ROAD_NOT_ENGINE_CAPABLE, WRONG_LOCATION, RESOURCE_DOUBLE_BOOKED, SCHEDULE_OVERRUN,
  * leg timing from travel sums, and evaluation on a deep copy (AC-022: the authoritative world is never mutated).

What it does not model: fire, people, capacity waits, fuel, shelters. `Metrics` in a stub `Evaluation` are all
zero placeholders, `target_checks` is empty, and every stub evaluation carries `trace_ref=None`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from app.agents.contracts import (
    AgentId,
    Assignment,
    AssignmentDraft,
    Evaluation,
    Evidence,
    Leg,
    Metrics,
    Violation,
)

from app.sim.contract import HORIZON, BeliefView, Route, SimService, ViewAgent  # re-exported for WS-B importers

LABEL = "SIMULATOR STUB — placeholder numbers, not physics"
__all__ = ["HORIZON", "BeliefView", "Route", "SimService", "ViewAgent", "StubSim", "LABEL", "world_fingerprint"]

TASK_DURATION = {"load": 2, "unload": 1, "refuel": 3, "clear_road": 6, "hold": 0}

# §5.2 nodes -> cells; §5.2 roads; §5.3 resources; §5.9 evidence (true values vs public priors).
_NODES = {"NC": "c3_0", "PASS": "c2_1", "PR": "c3_2", "FORK": "c5_2", "BASE": "c7_2", "SE": "c9_2",
          "VJ": "c5_4", "SS": "c6_5"}
_ROADS = [  # id, a, b, travel_steps, capacity, engine_ok, initial_status
    ("R1", "BASE", "FORK", 3, 2, True, "OPEN"),
    ("R2", "FORK", "PR", 3, 1, True, "CLOSED_CLEARABLE"),
    ("R3", "FORK", "VJ", 2, 2, True, "OPEN"),
    ("R4", "VJ", "PR", 4, 1, True, "OPEN"),
    ("R5", "VJ", "SS", 3, 2, True, "OPEN"),
    ("R6", "FORK", "SE", 6, 2, True, "OPEN"),
    ("R7", "VJ", "SE", 5, 1, True, "OPEN"),
    ("R8", "PR", "PASS", 3, 1, False, "OPEN"),
    ("R9", "PASS", "NC", 3, 1, False, "OPEN"),
    ("R10", "NC", "FORK", 7, 1, True, "OPEN"),
    ("R11", "BASE", "SS", 4, 2, True, "OPEN"),
]
_RESOURCES = [  # id, type, node, capacity, fuel_capacity
    ("B1", "bus", "BASE", 30, 40), ("B2", "bus", "BASE", 30, 40), ("V1", "transport", "BASE", 10, 30),
    ("C1", "crew", "FORK", 0, None), ("C2", "crew", "FORK", 0, None), ("C3", "crew", "BASE", 0, None),
]
_ZONES = {"NC": ("North Camp", 20, 20), "PR": ("Pine Ridge", 90, 30), "VJ": ("Valley Junction", 240, 60)}
_SHELTERS = {"SE": ("Shelter East", 150, 40), "SS": ("Shelter South", 350, 320)}
_EVIDENCE = [  # id, holder, field_path, true, prior, summary
    ("E-EVAC-01", "EVAC", "zones.PR.assisted_initial", 30, 12, "Pine Ridge has 30 assisted residents, not 12"),
    ("E-EVAC-02", "EVAC", "zones.VJ.assisted_initial", 60, 30, "Valley Junction has 60 assisted residents, not 30"),
    ("E-EVAC-03", "EVAC", "zones.NC.assisted_initial", 20, 4, "North Camp has 20 assisted residents, not 4"),
    ("E-FIRE-01", "FIRE", "cells[c1_1, c2_1, c1_2, c2_2].fuel_initial", 0.9, 0.5, "Ridge cells carry heavy fuel"),
    ("E-FIRE-02", "FIRE", "cells.c2_1.firebreak_bonus", True, False, "Ridge Pass has a natural firebreak"),
    ("E-LOG-01", "LOG", "roads.R2.initial_status", "CLOSED_CLEARABLE", "OPEN",
     "R2 Fork-Pine Ridge blocked by downed trees; a crew can clear it in about 6 steps"),
    ("E-LOG-02", "LOG", "shelters.SS.background", 320, 290, "Shelter South already holds 320, not 290"),
]


def _build_world(run_id: str, scenario_id: str, seed: int) -> dict[str, Any]:
    return {
        "schema_version": "1", "run_id": run_id, "scenario_id": scenario_id, "seed": seed,
        "step": 0, "state_version": 0, "horizon": HORIZON, "paused": True,
        "label": "Synthetic simulation", "stub": LABEL,
        "nodes": dict(_NODES),
        "roads": {r[0]: {"id": r[0], "a": r[1], "b": r[2], "travel_steps": r[3], "capacity": r[4],
                         "engine_ok": r[5], "initial_status": r[6], "status_override": None, "clear_progress": 0}
                  for r in _ROADS},
        "zones": {z: {"id": z, "name": n, "cell": _NODES[z], "unassisted_initial": u, "assisted_initial": a,
                      "self_evacuated": 0, "assisted_picked_up": 0} for z, (n, u, a) in _ZONES.items()},
        "shelters": {s: {"id": s, "name": n, "cell": _NODES[s], "capacity": c, "background": b, "arrivals": 0}
                     for s, (n, c, b) in _SHELTERS.items()},
        "cells": {c: {"id": c, "fuel_initial": 0.9 if c in ("c1_1", "c2_1", "c1_2", "c2_2") else 0.7,
                      "firebreak_bonus": c == "c2_1"} for c in ("c1_1", "c2_1", "c1_2", "c2_2", "c3_2")},
        "resources": {r[0]: {"id": r[0], "type": r[1], "node": r[2], "edge": None, "edge_steps_left": 0,
                             "capacity": r[3], "fuel_capacity": r[4], "fuel_used": 0, "aboard_people": {},
                             "aboard_crew": None, "engine_node": r[2] if r[1] == "crew" else None,
                             "available": True} for r in _RESOURCES},
        "wind": {"direction": "E", "speed": 2},
        "committed_plan_hash": None, "active_legs": [],
    }


def _evidence_items() -> list[Evidence]:
    return [Evidence(evidence_id=e[0], holders={e[1]}, field_path=e[2], true_value=e[3], prior_value=e[4],
                     summary=e[5], observed_step=0, confidence="high") for e in _EVIDENCE]


class StubSim:
    label = LABEL

    def __init__(self, scenario_id: str = "normal", seed: int = 1, run_id: str = "run-stub-normal-s1"):
        self.reset(scenario_id, seed, run_id)

    # --- lifecycle --------------------------------------------------------------------------------------

    def reset(self, scenario_id: str, seed: int, run_id: str) -> dict[str, Any]:
        self.world = _build_world(run_id, scenario_id, seed)
        self.evidence = _evidence_items()
        return copy.deepcopy(self.world)

    def step(self, n: int = 1) -> dict[str, Any]:
        """Advance simulated time only. No fire, people or movement rules here (WS-A owns them)."""
        self.world["step"] += n
        return copy.deepcopy(self.world)

    def apply_event(self, event: dict[str, Any]) -> int:
        """Public exogenous event (§5.11 kinds). Increments state_version (invariant 6)."""
        kind, target, value = event["kind"], event.get("target"), event.get("value")
        if kind == "road_status":
            self.world["roads"][target]["status_override"] = value
        elif kind == "wind_change":
            direction, _, speed = str(value).partition(":")
            self.world["wind"] = {"direction": direction, "speed": int(speed or self.world["wind"]["speed"])}
        elif kind == "resource_status":
            self.world["resources"][target]["available"] = value != "OUT_OF_SERVICE"
        else:
            raise ValueError(f"unknown event kind {kind!r}")
        self.world["state_version"] += 1
        return self.world["state_version"]

    def apply_accepted_plan(self, assignments: list[Assignment], plan_hash: str) -> int:
        """Stub: records the commit and bumps the version. Leg expansion/execution is WS-A's (§5.7).
        Restored after the A1-A3 refactor moved the `SimService` contract out to
        `app/sim/contract.py` and dropped this implementation from `StubSim` -- it's in the
        Protocol there, and `CommitGate.__init__`'s default (`apply or sim.apply_accepted_plan`)
        plus every caller that doesn't pass an explicit `apply=` (WS-B's own `test_protocol.py`,
        Tisha's `negotiation_session.py`) depend on `StubSim` still implementing it until the G1
        swap to the real `SimulatorService` happens."""
        self.world["committed_plan_hash"] = plan_hash
        self.world["active_legs"] = []
        self.world["state_version"] += 1
        return self.world["state_version"]

    def disclose(self, evidence_id: str, to: AgentId) -> None:
        """Router hook: once disclosed, the recipient's view shows the true value (§4.3)."""
        for e in self.evidence:
            if e.evidence_id == evidence_id:
                e.holders.add(to)
                return
        raise KeyError(evidence_id)

    # --- belief views (§5.9) -----------------------------------------------------------------------------

    def build_belief_view(self, agent: ViewAgent) -> BeliefView:
        world = copy.deepcopy(self.world)
        held: list[Evidence] = []
        for e in self.evidence:
            if agent in ("authoritative", "union") or agent in e.holders:
                held.append(e.model_copy(deep=True))
            else:
                for path in _expand_field_path(e.field_path):
                    _set_path(world, path, e.prior_value)
        if agent == "authoritative":
            held = []
        return BeliefView(agent=agent, world=world, held_evidence=held,
                          state_version=world["state_version"], step=world["step"])

    # --- tools (§6.2), all computed on the caller's view ------------------------------------------------

    def find_routes(self, view: BeliefView, origin: str, destination: str, *, resource_id: str) -> list[Route]:
        world = view.world
        if origin not in world["nodes"] or destination not in world["nodes"]:
            raise ValueError(f"unknown node in {origin!r} -> {destination!r}")
        crew = world["resources"].get(resource_id, {}).get("type") == "crew"
        routes: list[Route] = []

        def dfs(node: str, visited: list[str], roads: list[str], travel: int) -> None:
            if node == destination:
                routes.append(Route(route_ids=list(roads), nodes=list(visited), travel_steps=travel))
                return
            for rid in sorted(world["roads"]):
                r = world["roads"][rid]
                if _status(r) != "OPEN" or (crew and not r["engine_ok"]):
                    continue
                nxt = r["b"] if r["a"] == node else r["a"] if r["b"] == node else None
                if nxt is None or nxt in visited:
                    continue
                dfs(nxt, [*visited, nxt], [*roads, rid], travel + r["travel_steps"])

        dfs(origin, [origin], [], 0)
        routes.sort(key=lambda rt: (rt.travel_steps, rt.route_ids))
        return routes[:3]

    def validate_plan(self, view: BeliefView, assignments: list[AssignmentDraft]) -> list[Violation]:
        violations, _, _ = self._schedule(view, assignments, HORIZON)
        return violations

    def plan_timing(self, view: BeliefView, assignments: list[AssignmentDraft], *,
                    current_step: int | None = None) -> list[dict[str, int]]:
        if current_step is not None and current_step != view.step:
            view = BeliefView(agent=view.agent, world=view.world, held_evidence=view.held_evidence,
                              state_version=view.state_version, step=current_step)
        _, _, timing = self._schedule(view, assignments, HORIZON)
        return timing

    def evaluate_plan(self, view: BeliefView, assignments: list[AssignmentDraft], *, plan_hash: str,
                      horizon: int = HORIZON, seed: int | None = None) -> Evaluation:
        """Runs on a deep copy of the view (§5.10 step 1). Metrics are zero placeholders — STUB."""
        scratch = BeliefView(agent=view.agent, world=copy.deepcopy(view.world), held_evidence=list(view.held_evidence),
                             state_version=view.state_version, step=view.step)
        violations, legs, _ = self._schedule(scratch, assignments, horizon)
        valid = not violations
        return Evaluation(
            evaluation_id=f"ev-{plan_hash[:12]}-{scratch.basis}-v{scratch.state_version}",
            plan_hash=plan_hash, basis=scratch.basis, kind="forecast",
            run_id=scratch.world["run_id"], state_version=scratch.state_version, from_step=scratch.step,
            horizon=horizon, seed=seed if seed is not None else scratch.world["seed"],
            valid=valid, violations=violations,
            metrics=Metrics(civilian_exposure=0, assisted_completion=None, assisted_sheltered=0, assisted_demand=0,
                            evacuation_completion_step=None, fire_extent=0, burning_cell_steps=0,
                            crew_risk_steps=0, logistics_risk=0, invalid_attempted=0,
                            invalid_executed=0) if valid else None,
            target_checks=[], leg_timing=legs, trace_ref=None, sim_ms=0,
        )

    # --- scheduling core (structural checks only) --------------------------------------------------------

    def _schedule(self, view: BeliefView, assignments: list[AssignmentDraft], horizon: int
                  ) -> tuple[list[Violation], list[Leg], list[dict[str, int]]]:
        world = view.world
        violations: list[Violation] = []
        legs: list[Leg] = []
        timing: list[dict[str, int]] = []
        last_end: dict[str, int] = {}
        location: dict[str, str | None] = {rid: r["node"] for rid, r in world["resources"].items()}

        for order, a in enumerate(assignments):
            res = world["resources"].get(a.resource_id)
            if res is None:
                violations.append(_v("UNKNOWN_RESOURCE", order, a.resource_id, None, f"no resource {a.resource_id!r}"))
                timing.append({"start_step": view.step, "end_step": view.step, "wait_steps": 0})
                continue
            if not res["available"]:
                violations.append(_v("RESOURCE_UNAVAILABLE", order, a.resource_id, None, "OUT_OF_SERVICE"))
            start = a.start_step if a.start_step is not None else max(last_end.get(a.resource_id, view.step), view.step)
            if start < last_end.get(a.resource_id, view.step):
                violations.append(_v("RESOURCE_DOUBLE_BOOKED", order, a.resource_id, None,
                                     f"start_step {start} before previous end {last_end[a.resource_id]}"))
                start = last_end[a.resource_id]

            if a.task in ("drive", "transfer_crew"):
                origin = a.origin or location.get(a.resource_id) or "?"
                t = start + (1 if a.task == "transfer_crew" else 0)
                node = origin
                crew = res["type"] == "crew"
                for rid in a.route_ids:
                    r = world["roads"].get(rid)
                    if r is None:
                        violations.append(_v("WRONG_LOCATION", order, a.resource_id, rid, f"unknown road {rid!r}"))
                        break
                    nxt = r["b"] if r["a"] == node else r["a"] if r["b"] == node else None
                    if nxt is None:
                        violations.append(_v("WRONG_LOCATION", order, a.resource_id, rid,
                                             f"{rid} does not touch {node}"))
                        break
                    if _status(r) != "OPEN":
                        violations.append(_v("ROAD_CLOSED", order, a.resource_id, rid, f"{rid} is {_status(r)}"))
                    if crew and not r["engine_ok"]:
                        violations.append(_v("ROAD_NOT_ENGINE_CAPABLE", order, a.resource_id, rid,
                                             f"{rid} is a narrow fire road"))
                    legs.append(Leg(resource_id=a.resource_id, kind="traverse", edge_id=rid, node=None,
                                    start_step=t, end_step=t + r["travel_steps"]))
                    t += r["travel_steps"]
                    node = nxt
                if a.destination and node != a.destination and not any(
                        v.assignment_order == order and v.code == "WRONG_LOCATION" for v in violations):
                    violations.append(_v("WRONG_LOCATION", order, a.resource_id, None,
                                         f"route ends at {node}, not {a.destination}"))
                end = t + (1 if a.task == "transfer_crew" else 0)
                location[a.resource_id] = node
            elif a.task == "contain":
                end = start + max(a.duration_steps or 0, 3)
                legs.append(Leg(resource_id=a.resource_id, kind="work", edge_id=None,
                                node=location.get(a.resource_id), start_step=start, end_step=end))
            else:
                end = start + TASK_DURATION.get(a.task, 0)
                kind = {"load": "load", "unload": "unload", "refuel": "refuel", "clear_road": "work"}.get(a.task)
                if kind:
                    legs.append(Leg(resource_id=a.resource_id, kind=kind, edge_id=None,
                                    node=location.get(a.resource_id), start_step=start, end_step=end))
            if end > horizon:
                violations.append(_v("SCHEDULE_OVERRUN", order, a.resource_id, None,
                                     f"ends at step {end} > horizon {horizon}"))
            last_end[a.resource_id] = end
            timing.append({"start_step": start, "end_step": end, "wait_steps": 0})   # stub: no capacity waits
        return violations, legs, timing


# --- helpers ---------------------------------------------------------------------------------------------

def _status(road: dict[str, Any]) -> str:
    return road["status_override"] or road["initial_status"]


def _v(code: str, order: int, resource_id: str | None, road_id: str | None, detail: str) -> Violation:
    return Violation(code=code, assignment_order=order, resource_id=resource_id, road_id=road_id, detail=detail)  # type: ignore[arg-type]


def _expand_field_path(path: str) -> list[list[str]]:
    """'cells[c1_1, c2_1].fuel_initial' -> [['cells','c1_1','fuel_initial'], ['cells','c2_1','fuel_initial']]."""
    m = re.fullmatch(r"(\w+)\[([^\]]+)\]\.(\w+)", path)
    if m:
        return [[m.group(1), key.strip(), m.group(3)] for key in m.group(2).split(",")]
    return [path.split(".")]


def _set_path(obj: dict[str, Any], path: list[str], value: Any) -> None:
    for key in path[:-1]:
        obj = obj[key]
    obj[path[-1]] = value


def world_fingerprint(world: dict[str, Any]) -> str:
    """Stable hash of a world dict, for AC-022 'unchanged before and after evaluation' assertions."""
    return hashlib.sha256(json.dumps(world, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
