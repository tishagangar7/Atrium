"""Exogenous events (PRD §5.8, §5.11, FR-040, FR-042; D-10).

Kinds: `wind_change` (value "DIR:speed", applies from the fire phase of the step), `road_status` (closures block
entry, not travel in progress), `resource_status` (OUT_OF_SERVICE takes effect at the vehicle's next node arrival with
no passengers aboard — the engine honours the pending flag). Every applied event increments `state_version`
(invariant 6); the run controller voids acceptances and opens a new decision point.
"""

from __future__ import annotations

from typing import Any

from app.models import ScheduledEvent, Wind, WorldState

OUT_OF_SERVICE = "OUT_OF_SERVICE"


def parse_event(event: ScheduledEvent | dict[str, Any]) -> ScheduledEvent:
    return event if isinstance(event, ScheduledEvent) else ScheduledEvent.model_validate(event)


def apply_event(world: WorldState, event: ScheduledEvent | dict[str, Any], *,
                pending_out_of_service: set[str] | None = None) -> ScheduledEvent:
    """Mutates the authoritative world and bumps `state_version`. Returns the parsed event for logging."""
    ev = parse_event(event)
    if ev.kind == "wind_change":
        direction, _, speed = str(ev.value).partition(":")
        world.wind = Wind(direction=direction, speed=int(speed) if speed else world.wind.speed)  # type: ignore[arg-type]
    elif ev.kind == "road_status":
        if ev.target not in world.roads:
            raise KeyError(f"unknown road {ev.target!r}")
        world.roads[ev.target].status_override = str(ev.value)  # type: ignore[assignment]
    elif ev.kind == "resource_status":
        if ev.target not in world.resources:
            raise KeyError(f"unknown resource {ev.target!r}")
        res = world.resources[ev.target]
        if ev.value == OUT_OF_SERVICE:
            if res.node is not None and sum(res.aboard_people.values()) == 0:
                res.available = False
            elif pending_out_of_service is not None:
                pending_out_of_service.add(res.id)       # §5.8: at next node arrival without passengers
            else:
                res.available = False
        else:
            res.available = True
    else:
        raise ValueError(f"unknown event kind {ev.kind!r}")
    world.state_version += 1
    return ev


def events_at(scenario_events: list[ScheduledEvent], step: int) -> list[ScheduledEvent]:
    return [e for e in scenario_events if e.step == step]
