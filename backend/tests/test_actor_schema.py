"""Model-facing AgentTurn schema, sentinel parsing and semantic validation (PRD §7.5, §6.5, D-17, AC-029, FR-026)."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.agents.contracts import Target
from app.agents.schema import (
    INT_SENTINEL,
    RATIONALE_MAX,
    TurnContext,
    parse_turn,
    turn_output_schema,
    validate_turn,
    validation_error_lines,
)

# The §7.5 CHALLENGE example, in the sentinel form a model would emit.
CHALLENGE_SENTINEL = {
    "message_type": "CHALLENGE",
    "recipients": ["EVAC", "FIRE"],
    "plan": [],
    "parent_plan_id": "",
    "target_plan_id": "dp-1:P1",
    "target_plan_hash": "5c1e9a0b7d2f",
    "objection": {"kind": "infeasible", "metric": "", "evaluation_id": "",
                  "proposed_amendment": "Route V1 via R3 and R4 instead of R2"},
    "evidence_ids": ["E-LOG-01"],
    "caused_by": [],
    "requested_evidence_id": "",
    "requested_topic": "",
    "shared_evidence_ids": [],
    "reason": "",
    "blocking": [],
    "rationale": "P1 sends V1 over R2, which is blocked (E-LOG-01). No valid arrival at Pine Ridge.",
}
NO_REVISION = {"metric": "", "old_aspiration": 0, "new_aspiration": 0, "reason": ""}
ASSIGNMENT_SENTINEL = {
    "resource_id": "B1", "task": "drive", "origin": "BASE", "destination": "VJ", "route_ids": ["R1", "R3"],
    "start_step": 0, "people_count": INT_SENTINEL, "zone_id": "", "shelter_id": "", "crew_id": "",
    "target_cells": [], "edge_id": "", "duration_steps": INT_SENTINEL,
}


def message(**overrides: Any) -> dict[str, Any]:
    m = copy.deepcopy(CHALLENGE_SENTINEL)
    m.update(overrides)
    return m


def turn(*messages: dict[str, Any], revision: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"messages": list(messages), "target_revision": revision or NO_REVISION}


def ctx(**overrides: Any) -> TurnContext:
    base = dict(
        agent_id="LOG", round=2, step=0, horizon=60,
        held_evidence_ids={"E-LOG-01", "E-LOG-02"},
        known_plan_ids={"dp-1:P1", "dp-1:P2"},
        current_plan_hashes={"5c1e9a0b7d2f", "9f03c2d4e1aa"},
        own_targets=[Target(metric="logistics_risk", direction="min", aspiration=1, floor=3)],
    )
    base.update(overrides)
    return TurnContext(**base)


# --- schema shape --------------------------------------------------------------------------------------

def _walk(node: Any, path: str = "$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def test_schema_is_strict_mode_compatible():
    """D-17 / Appendix B: no nulls, no unions, no numeric bounds or length limits, every property required."""
    schema = turn_output_schema()
    json.dumps(schema)  # serializable
    for path, node in _walk(schema):
        assert "anyOf" not in node and "oneOf" not in node and "$ref" not in node, path
        assert node.get("type") != "null", path
        for banned in ("minimum", "maximum", "maxLength", "minLength", "default"):
            assert banned not in node, f"{banned} at {path}"
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False, path
            assert set(node["required"]) == set(node["properties"]), path


def test_schema_has_no_metric_fields():
    """FR-012 / invariant 3: agent output carries no outcome numbers."""
    names = {k for _, n in _walk(turn_output_schema()) for k in n.get("properties", {})}
    for metric in ("civilian_exposure", "assisted_completion", "fire_extent", "crew_risk_steps", "logistics_risk",
                   "metrics", "value"):
        assert metric not in names


def test_schema_objection_has_none_kind_and_revision_is_model_facing():
    schema = turn_output_schema()
    objection = schema["properties"]["messages"]["items"]["properties"]["objection"]
    assert objection["properties"]["kind"]["enum"][0] == "none"
    revision = schema["properties"]["target_revision"]
    assert set(revision["properties"]) == {"metric", "old_aspiration", "new_aspiration", "reason"}


# --- sentinel round trip -------------------------------------------------------------------------------

def test_parse_turn_maps_sentinels_to_none():
    t = parse_turn(turn(CHALLENGE_SENTINEL), agent_id="LOG", dp_id="dp-1")
    m = t.messages[0]
    assert m.plan is None and m.parent_plan_id is None and m.reason is None
    assert m.objection is not None and m.objection.metric is None and m.objection.evaluation_id is None
    assert m.target_plan_id == "dp-1:P1" and m.evidence_ids == ["E-LOG-01"]
    assert t.target_revision is None


def test_parse_turn_objection_none_and_plan_sentinels():
    propose = message(message_type="PROPOSE", target_plan_id="", target_plan_hash="",
                      objection={"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""},
                      plan=[ASSIGNMENT_SENTINEL], evidence_ids=[])
    t = parse_turn(turn(propose), agent_id="LOG", dp_id="dp-1")
    m = t.messages[0]
    assert m.objection is None
    assert m.plan is not None and m.plan[0].people_count is None and m.plan[0].zone_id is None
    assert m.plan[0].start_step == 0 and m.plan[0].route_ids == ["R1", "R3"]


def test_parse_turn_fills_revision_envelope():
    rev = {"metric": "logistics_risk", "old_aspiration": 1, "new_aspiration": 2, "reason": "R2 closure"}
    t = parse_turn(turn(revision=rev), agent_id="LOG", dp_id="dp-1")
    assert t.target_revision is not None
    assert t.target_revision.by == "LOG" and t.target_revision.dp_id == "dp-1"


def test_parse_turn_rejects_malformed_shape():
    """AC-029: malformed output is an error for the repair path, never silently accepted."""
    with pytest.raises(ValidationError) as ei:
        parse_turn(turn(message(message_type="SHOUT")), agent_id="LOG", dp_id="dp-1")
    assert any("message_type" in line for line in validation_error_lines(ei.value))
    with pytest.raises((ValidationError, ValueError)):
        parse_turn({"messages": "nope"}, agent_id="LOG", dp_id="dp-1")


def test_silence_is_a_valid_turn():
    t = parse_turn({"messages": [], "target_revision": NO_REVISION}, agent_id="LOG", dp_id="dp-1")
    assert t.messages == [] and validate_turn(t, ctx()) == []


# --- semantic validation -------------------------------------------------------------------------------

def _errors(raw_turn: dict[str, Any], context: TurnContext | None = None) -> list[str]:
    return validate_turn(parse_turn(raw_turn, agent_id="LOG", dp_id="dp-1"), context or ctx())


def test_valid_challenge_passes():
    assert _errors(turn(CHALLENGE_SENTINEL)) == []


def test_too_many_messages():
    errs = _errors(turn(*[CHALLENGE_SENTINEL] * 4))
    assert any("at most 3" in e for e in errs)


def test_two_new_plans_rejected():
    propose = message(message_type="PROPOSE", target_plan_id="", target_plan_hash="",
                      objection={"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""},
                      plan=[ASSIGNMENT_SENTINEL], evidence_ids=[])
    errs = _errors(turn(propose, propose))
    assert any("at most one PROPOSE" in e for e in errs)


def test_rationale_bound_enforced_after_parse():
    """§3.5: strict schemas cannot express maxLength, so the bound is enforced after parsing — by Pydantic's
    `max_length` in app.models at `parse_turn` (and again in validate_turn), feeding the one repair attempt."""
    with pytest.raises(ValidationError) as ei:
        parse_turn(turn(message(rationale="x" * (RATIONALE_MAX + 1))), agent_id="LOG", dp_id="dp-1")
    assert any("rationale" in line and "280" in line for line in validation_error_lines(ei.value))


def test_citing_unheld_evidence_is_unknown_evidence():
    """§6.10 UNKNOWN_EVIDENCE: an agent cannot cite what it does not hold (isolation in code, §4.4)."""
    errs = _errors(turn(message(evidence_ids=["E-EVAC-01"])))
    assert any("UNKNOWN_EVIDENCE" in e and "E-EVAC-01" in e for e in errs)


def test_counterpropose_requires_caused_by_and_parent():
    """FR-026 / AC-004."""
    cp = message(message_type="COUNTERPROPOSE", plan=[ASSIGNMENT_SENTINEL], parent_plan_id="dp-1:P1",
                 target_plan_id="", target_plan_hash="", evidence_ids=[],
                 objection={"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""})
    assert any("caused_by" in e for e in _errors(turn(cp)))
    cp["caused_by"] = ["dp-1:r1:EVAC:0"]
    assert _errors(turn(cp)) == []
    cp["parent_plan_id"] = "dp-9:P9"
    assert any("INVALID_REFERENCE" in e for e in _errors(turn(cp)))


def test_accept_requires_current_hash():
    """AC-006 / §6.10 INVALID_REFERENCE."""
    acc = message(message_type="ACCEPT", target_plan_id="", evidence_ids=[],
                  objection={"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""})
    assert _errors(turn(acc)) == []
    acc["target_plan_hash"] = ""
    assert any("requires target_plan_hash" in e for e in _errors(turn(acc)))
    acc["target_plan_hash"] = "deadbeef0000"
    assert any("INVALID_REFERENCE" in e for e in _errors(turn(acc)))


def test_round_one_only_allows_opening_moves():
    assert any("round 2" in e for e in _errors(turn(CHALLENGE_SENTINEL), ctx(round=1)))


def test_start_step_range():
    late = dict(ASSIGNMENT_SENTINEL, start_step=61)
    propose = message(message_type="PROPOSE", target_plan_id="", target_plan_hash="", plan=[late], evidence_ids=[],
                      objection={"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""})
    assert any("start_step 61 outside" in e for e in _errors(turn(propose)))


def test_target_revision_floor_rules():
    """FR-035 / AC-031: toward the floor only, never past it."""
    ok = {"metric": "logistics_risk", "old_aspiration": 1, "new_aspiration": 2, "reason": "R2 closed"}
    assert _errors(turn(revision=ok)) == []
    past = dict(ok, new_aspiration=4)
    assert any("TARGET_BELOW_FLOOR" in e for e in _errors(turn(revision=past)))
    tighten = dict(ok, new_aspiration=0)
    assert any("toward the floor" in e for e in _errors(turn(revision=tighten)))
    other = dict(ok, metric="fire_extent")
    assert any("not one of your targets" in e for e in _errors(turn(revision=other)))
