"""Plan validation (PRD §7.1 violation codes, FR-010, AC-017–021).

Hard constraints are never waived by agents or humans (invariant 7). Validation runs on whichever world dict it is
given: an agent's belief view (tools, delivery services) or the authoritative world (commit gate, escalation).
Most codes fall out of expanding the plan (`plans.expand`); this module adds the structural ones (`LOCKED_LEG_CHANGED`)
and de-duplicates. `NO_CHANGE` is the router's (a counterproposal whose hash equals its parent).
"""

from __future__ import annotations

from typing import Any

from app.models import Assignment, AssignmentDraft, Violation
from app.sim.plans import Expansion, expand

LOCKED_FIELDS = ("resource_id", "task", "origin", "destination", "route_ids", "start_step", "people_count",
                 "zone_id", "shelter_id", "crew_id", "target_cells", "edge_id", "duration_steps")


def validate_plan(world: dict[str, Any], assignments: list[Assignment | AssignmentDraft], params: dict[str, float],
                  *, locked: list[Assignment] | None = None, current_step: int | None = None) -> list[Violation]:
    violations: list[Violation] = []
    if locked:
        violations.extend(_locked_changed(assignments, locked))
    expansion = expand(assignments, world, params, current_step=current_step)
    violations.extend(expansion.violations)
    return _dedupe(violations)


def validate_and_expand(world: dict[str, Any], assignments: list[Assignment | AssignmentDraft],
                        params: dict[str, float], *, locked: list[Assignment] | None = None,
                        current_step: int | None = None) -> tuple[list[Violation], Expansion]:
    expansion = expand(assignments, world, params, current_step=current_step)
    violations = list(expansion.violations)
    if locked:
        violations.extend(_locked_changed(assignments, locked))
    return _dedupe(violations), expansion


def _locked_changed(assignments: list[Assignment | AssignmentDraft], locked: list[Assignment]) -> list[Violation]:
    """§5.8: locked assignments are prefilled in every plan and agents cannot change them."""
    out: list[Violation] = []
    for i, want in enumerate(locked):
        got = assignments[i] if i < len(assignments) else None
        if got is None or any(getattr(got, f) != getattr(want, f) for f in LOCKED_FIELDS):
            out.append(Violation(code="LOCKED_LEG_CHANGED", assignment_order=i, resource_id=want.resource_id,
                                 road_id=None, detail=f"locked assignment {i} for {want.resource_id} was altered or removed"))
    return out


def _dedupe(violations: list[Violation]) -> list[Violation]:
    seen: set[tuple] = set()
    out: list[Violation] = []
    for v in violations:
        key = (v.code, v.assignment_order, v.resource_id, v.road_id)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out
