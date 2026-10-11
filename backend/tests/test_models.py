"""PRD §7 data contracts: every model builds a JSON schema and the PRD's own worked
examples (§7.3, §7.5-§7.8) round-trip through the Pydantic models unchanged."""

import app.models as m
from pydantic import BaseModel


def _all_models() -> list[type[BaseModel]]:
    seen: list[type[BaseModel]] = []
    for value in vars(m).values():
        if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel:
            if value not in seen:
                seen.append(value)
    return seen


def test_every_model_builds_a_json_schema():
    for cls in _all_models():
        assert cls.model_json_schema()


def test_schema_version_field_defaults_to_one():
    for cls in _all_models():
        if "schema_version" in cls.model_fields:
            assert cls.model_fields["schema_version"].default == "1"


def test_evidence_example_from_prd_7_3():
    payload = {
        "evidence_id": "E-LOG-01",
        "holders": ["LOG"],
        "field_path": "roads.R2.initial_status",
        "true_value": "CLOSED_CLEARABLE",
        "prior_value": "OPEN",
        "summary": "R2 Fork-Pine Ridge blocked by downed trees; a crew can clear it in about 6 steps",
        "observed_step": 0,
        "confidence": "high",
    }
    evidence = m.Evidence.model_validate(payload)
    assert evidence.evidence_id == "E-LOG-01"
    assert evidence.holders == {"LOG"}


def test_agent_message_example_from_prd_7_5():
    payload = {
        "schema_version": "1", "message_id": "dp-1:r2:LOG:0", "sender": "LOG",
        "recipients": ["EVAC", "FIRE"], "run_id": "run-20261010T1830Z-normal-s1",
        "scenario_id": "normal", "dp_id": "dp-1", "state_version": 1, "round": 2,
        "ts": "2026-10-10T18:31:12.402Z", "step": 0, "message_type": "CHALLENGE",
        "plan": None, "parent_plan_id": None, "target_plan_id": "dp-1:P1",
        "target_plan_hash": "5c1e9a0b7d2f",
        "objection": {
            "kind": "infeasible", "metric": None, "evaluation_id": None,
            "proposed_amendment": "Route V1 via R3 and R4 instead of R2",
        },
        "evidence_ids": ["E-LOG-01"], "caused_by": [], "requested_evidence_id": None,
        "requested_topic": None, "shared_evidence_ids": [], "reason": None, "blocking": [],
        "rationale": "P1 sends V1 over R2, which is blocked (E-LOG-01). No valid arrival at Pine Ridge.",
        "proposal_id": None, "plan_hash": None, "status": "delivered", "drop_reason": None,
    }
    message = m.AgentMessage.model_validate(payload)
    assert message.message_id == "dp-1:r2:LOG:0"
    assert message.objection.kind == "infeasible"


def test_plan_example_from_prd_7_6():
    payload = {
        "schema_version": "1", "plan_id": "dp-1:P3", "plan_hash": "9f03c2d4e1aa",
        "proposer": "LOG", "parent_plan_id": "dp-1:P1", "run_id": "run-20261010T1830Z-normal-s1",
        "dp_id": "dp-1", "state_version": 1, "state": "EVALUATED",
        "assignments": [
            {
                "order": 0, "locked": False, "resource_id": "B1", "task": "drive",
                "origin": "BASE", "destination": "VJ", "route_ids": ["R1", "R3"],
                "start_step": 0, "end_step": 5, "wait_steps": 0, "people_count": None,
                "zone_id": None, "shelter_id": None, "crew_id": None, "target_cells": [],
                "edge_id": None, "duration_steps": None,
            },
        ],
        "evidence_ids": ["E-LOG-01", "E-LOG-02"],
        "evaluation_ids": ["ev-9f03c2d4e1aa-authoritative-v1"],
        "tradeoffs": [], "expected_shelter_use": {"SS": 30},
    }
    plan = m.Plan.model_validate(payload)
    assert plan.plan_id == "dp-1:P3"
    assert plan.assignments[0].resource_id == "B1"


def test_evaluation_example_from_prd_7_6():
    payload = {
        "schema_version": "1", "evaluation_id": "ev-5c1e9a0b7d2f-view_EVAC-v1",
        "plan_hash": "5c1e9a0b7d2f", "basis": "view_EVAC", "kind": "forecast",
        "run_id": "run-20261010T1830Z-normal-s1", "state_version": 1, "from_step": 0,
        "horizon": 60, "seed": 1, "valid": True, "violations": [],
        "metrics": {
            "civilian_exposure": 0, "assisted_completion": 0.0, "assisted_sheltered": 0,
            "assisted_demand": 110, "evacuation_completion_step": None, "fire_extent": 0,
            "burning_cell_steps": 0, "crew_risk_steps": 0, "logistics_risk": 0,
            "invalid_attempted": 0, "invalid_executed": 0,
        },
        "target_checks": [
            {"agent_id": "EVAC", "metric": "assisted_completion", "value": 0.0,
             "meets_aspiration": False, "meets_floor": False},
        ],
        "leg_timing": [
            {"resource_id": "B1", "kind": "traverse", "edge_id": "R1", "node": None,
             "start_step": 0, "end_step": 3},
        ],
        "trace_ref": "runs/run-20261010T1830Z-normal-s1/traces/ev-5c1e9a0b7d2f-view_EVAC-v1.json",
        "sim_ms": 0,
    }
    evaluation = m.Evaluation.model_validate(payload)
    assert evaluation.valid is True
    assert evaluation.metrics.assisted_demand == 110


def test_commit_example_from_prd_7_7():
    payload = {
        "schema_version": "1", "run_id": "run-20261010T1830Z-normal-s1", "dp_id": "dp-1",
        "plan_hash": "9f03c2d4e1aa", "plan_id": "dp-1:P3", "state_version_before": 1,
        "state_version_after": 2,
        "acceptances": [
            {"agent_id": "LOG", "plan_hash": "9f03c2d4e1aa", "dp_id": "dp-1", "state_version": 1,
             "via": "COUNTERPROPOSE", "message_id": "dp-1:r2:LOG:1", "round": 2, "revoked": False},
            {"agent_id": "EVAC", "plan_hash": "9f03c2d4e1aa", "dp_id": "dp-1", "state_version": 1,
             "via": "ACCEPT", "message_id": "dp-1:r3:EVAC:0", "round": 3, "revoked": False},
            {"agent_id": "FIRE", "plan_hash": "9f03c2d4e1aa", "dp_id": "dp-1", "state_version": 1,
             "via": "ACCEPT", "message_id": "dp-1:r3:FIRE:0", "round": 3, "revoked": False},
        ],
        "ordering_rule": "first_proposed_seq", "authority": "unanimous",
        "authoritative_evaluation_id": "ev-9f03c2d4e1aa-authoritative-v1",
        "ts": "2026-10-10T18:31:24.910Z", "step": 0,
    }
    commit = m.Commit.model_validate(payload)
    assert len(commit.acceptances) == 3
    assert commit.authority == "unanimous"


def test_error_object_example_from_prd_7_8():
    payload = {
        "code": "STATE_VERSION_MISMATCH",
        "message": "expected_state_version 1 but current is 2",
        "retryable": True, "run_id": "run-20261010T1830Z-normal-s1", "state_version": 2,
        "details": {},
    }
    error = m.ErrorObject.model_validate(payload)
    assert error.retryable is True
