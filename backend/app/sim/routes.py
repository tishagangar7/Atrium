"""Route finding on a (possibly masked) world dict (PRD §6.2 `find_routes`, FR-013, AC-024).

Up to three simple paths between two nodes over roads whose *effective* status is OPEN in the caller's view, using
only engine-capable roads for crew units (§5.3). Ordered by total travel steps, then road ids — a deterministic
tie-break that §6.7 normalization relies on when it fills empty routes with `routes[0]`.
"""

from __future__ import annotations

from typing import Any

from app.sim.contract import Route
from app.sim.world import road_status

MAX_ROUTES = 3


def find_routes(world: dict[str, Any], origin: str, destination: str, *, resource_id: str,
                max_routes: int = MAX_ROUTES) -> list[Route]:
    nodes = world["nodes"]
    if origin not in nodes or destination not in nodes:
        raise ValueError(f"unknown node in {origin!r} -> {destination!r}")
    resource = world["resources"].get(resource_id)
    if resource is None:
        raise ValueError(f"UNKNOWN_RESOURCE {resource_id!r}")
    crew = resource["type"] == "crew"
    roads = world["roads"]
    found: list[Route] = []

    def dfs(node: str, visited: list[str], used: list[str], travel: int) -> None:
        if node == destination:
            found.append(Route(route_ids=list(used), nodes=list(visited), travel_steps=travel))
            return
        for rid in sorted(roads, key=_road_sort_key):
            r = roads[rid]
            if road_status(r) != "OPEN" or (crew and not r["engine_ok"]):
                continue
            nxt = r["b"] if r["a"] == node else r["a"] if r["b"] == node else None
            if nxt is None or nxt in visited:
                continue
            dfs(nxt, [*visited, nxt], [*used, rid], travel + r["travel_steps"])

    if origin == destination:
        return [Route(route_ids=[], nodes=[origin], travel_steps=0)]
    dfs(origin, [origin], [], 0)
    found.sort(key=lambda rt: (rt.travel_steps, rt.route_ids))
    return found[:max_routes]


def route_is_connected(world: dict[str, Any], origin: str, route_ids: list[str]) -> tuple[bool, str, str | None]:
    """Walk a route from `origin`; returns (ok, end_node, offending_road)."""
    node = origin
    for rid in route_ids:
        r = world["roads"].get(rid)
        if r is None:
            return False, node, rid
        nxt = r["b"] if r["a"] == node else r["a"] if r["b"] == node else None
        if nxt is None:
            return False, node, rid
        node = nxt
    return True, node, None


def _road_sort_key(rid: str) -> tuple[int, str]:
    """Numeric-aware ordering so R10 sorts after R9 (deterministic, human-readable)."""
    digits = "".join(ch for ch in rid if ch.isdigit())
    return (int(digits) if digits else 0, rid)
