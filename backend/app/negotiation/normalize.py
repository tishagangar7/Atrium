"""Plan normalization at delivery (PRD §6.7 step 1, §5.8 locked legs).

The router normalizes a proposer's drafts on the **proposer's** belief view before anything else sees them:

  1. prepend the decision point's locked assignments unchanged (`locked=True`, agents cannot alter them);
  2. fill empty `route_ids` on `drive`/`transfer_crew` with the shortest open route in the proposer's view
     (`sim.find_routes` orders by travel steps, then road ids — a deterministic tie-break);
  3. let the simulator resolve `start_step` (previous end of that resource, or the current step) and compute
     `end_step`/`wait_steps` via `sim.plan_timing` — the runtime never re-implements travel rules (§12.1).

The normalized plan is what every recipient sees and what the hash covers. Because routes are filled on the
proposer's view, private evidence changes the plan itself: Evacuation's BASE→PR drive becomes R1,R2 while
Logistics' becomes R1,R3,R4 (R2 is closed in Logistics' knowledge).
"""

from __future__ import annotations

from app.agents.contracts import Assignment, AssignmentDraft
from app.agents.sim_stub import BeliefView, SimService


class NormalizeError(ValueError):
    """The draft cannot be normalized on the proposer's view (no open route, missing destination)."""


def normalize(drafts: list[AssignmentDraft], *, view: BeliefView, sim: SimService,
              locked: list[Assignment] | None = None, current_step: int | None = None) -> list[Assignment]:
    locked = locked or []
    step = view.step if current_step is None else current_step
    resources = view.world.get("resources", {})

    filled: list[AssignmentDraft] = []
    last_node: dict[str, str | None] = {rid: r.get("node") for rid, r in resources.items()}
    for a in locked:
        if a.destination:
            last_node[a.resource_id] = a.destination
    for d in drafts:
        data = d.model_dump()
        if d.task in ("drive", "transfer_crew"):
            origin = d.origin or last_node.get(d.resource_id)
            if not d.destination:
                raise NormalizeError(f"{d.task} for {d.resource_id!r} has no destination")
            if not origin:
                raise NormalizeError(f"{d.task} for {d.resource_id!r} has no origin and the resource has no known node")
            data["origin"] = origin
            if not d.route_ids:
                if d.resource_id not in resources:
                    raise NormalizeError(f"UNKNOWN_RESOURCE {d.resource_id!r}")
                routes = sim.find_routes(view, origin, d.destination, resource_id=d.resource_id)
                if not routes:
                    raise NormalizeError(f"no open route {origin}->{d.destination} for {d.resource_id!r} in your view")
                data["route_ids"] = routes[0].route_ids
            last_node[d.resource_id] = d.destination
        filled.append(AssignmentDraft.model_validate(data))

    timing = sim.plan_timing(view, [*locked, *filled], current_step=step)
    out: list[Assignment] = []
    for i, a in enumerate(locked):
        out.append(a.model_copy(update={"order": i, "locked": True}))
    for j, (d, t) in enumerate(zip(filled, timing[len(locked):]), start=len(locked)):
        out.append(Assignment.model_validate({**d.model_dump(), "order": j, "locked": False,
                                              "start_step": t["start_step"], "end_step": t["end_step"],
                                              "wait_steps": t["wait_steps"]}))
    return out
