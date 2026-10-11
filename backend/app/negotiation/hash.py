"""Canonical plan serialization and hash (PRD §6.7 steps 2–4, D-08).

Two agents proposing identical assignments produce the same hash; wording, proposer, plan id, evaluations and
the runtime-computed `end_step`/`wait_steps` are **not** covered, so they never create a "new" plan. One
`start_step` difference does (AC-027: near-identical plans never merge into a commit).

    hash_input = JSON(keys sorted, separators ',' and ':', UTF-8, integers only) of
      {"assignments": [covered fields of each assignment, sorted by (start_step, resource_id, order)],
       "run_id": ..., "scenario_id": ..., "state_version": ...}
    plan_hash  = sha256(hash_input).hexdigest()        # UI shows the first 12 characters
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.agents.contracts import Assignment, AssignmentDraft

# Exactly the keys of the §6.7 example. `order`, `end_step`, `wait_steps` are derived and excluded.
COVERED_FIELDS: tuple[str, ...] = (
    "crew_id", "destination", "duration_steps", "edge_id", "locked", "origin", "people_count",
    "resource_id", "route_ids", "shelter_id", "start_step", "target_cells", "task", "zone_id",
)
SHORT_LEN = 12


class HashInputError(ValueError):
    """The plan is not normalized (missing start_step/route) and so cannot be hashed yet (§6.7 step 1)."""


def canonical_assignment(assignment: Assignment | AssignmentDraft | dict[str, Any]) -> dict[str, Any]:
    data = assignment if isinstance(assignment, dict) else assignment.model_dump(mode="json")
    out = {k: data.get(k) for k in COVERED_FIELDS}
    out["locked"] = bool(out["locked"]) if out["locked"] is not None else False
    if not isinstance(out["start_step"], int) or isinstance(out["start_step"], bool):
        raise HashInputError(f"assignment for {out['resource_id']!r} has no integer start_step")
    out["route_ids"] = list(out["route_ids"] or [])
    out["target_cells"] = list(out["target_cells"] or [])
    for key in ("people_count", "duration_steps"):
        if out[key] is not None and not isinstance(out[key], int):
            raise HashInputError(f"{key} must be an integer or null, got {out[key]!r}")
    return out


def hash_input(run_id: str, scenario_id: str, state_version: int,
               assignments: list[Assignment | AssignmentDraft | dict[str, Any]]) -> str:
    items = [canonical_assignment(a) for a in assignments]
    ordered = sorted(range(len(items)), key=lambda i: (items[i]["start_step"], items[i]["resource_id"], i))
    payload = {
        "assignments": [items[i] for i in ordered],
        "run_id": run_id,
        "scenario_id": scenario_id,
        "state_version": int(state_version),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def plan_hash(run_id: str, scenario_id: str, state_version: int,
              assignments: list[Assignment | AssignmentDraft | dict[str, Any]]) -> str:
    return hashlib.sha256(hash_input(run_id, scenario_id, state_version, assignments).encode("utf-8")).hexdigest()


def short(h: str) -> str:
    return h[:SHORT_LEN]
