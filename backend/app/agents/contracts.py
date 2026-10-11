"""WS-B view of the shared contracts (PRD §7).

`backend/app/models.py` (WS-C, Tisha) is the single source of truth; this module re-exports the names WS-B code
uses plus a few WS-B-only helpers, so `agents/` and `negotiation/` import one stable module. Field names, types
and defaults are defined in `app.models` only; after G0 any change goes through a `[contract]` PR (AGENTS.md §2).

Conventions (PRD §7): optional fields are `None`, never missing; every top-level object has
`schema_version: "1"`; `ts` is wall clock, `step` is simulated — never interchangeable.

Bounds such as `rationale` ≤ 280 and `proposed_amendment` ≤ 200 are Pydantic `max_length` constraints in
`app.models`; the model-facing schema in `schema.py` strips them (strict mode forbids `maxLength`) and
`parse_turn` surfaces them as validation errors for the one repair attempt (§3.5, §10.1).
"""

from __future__ import annotations

from typing import Literal

from app.models import (
    Acceptance,
    AgentId,
    AgentMessage,
    AgentTurn,
    Assignment,
    AssignmentDraft,
    Commit,
    EscalationPackage,
    EvalBasis,
    Evaluation,
    Evidence,
    Leg,
    MessageType,
    Metrics,
    Objection,
    Observation,
    Plan,
    PlanState,
    ResourceType,
    RoadStatus,
    ScheduledEvent,
    Target,
    TargetCheck,
    TargetRevision,
    TaskType,
    TurnMessage,
    Violation,
    ViolationCode,
)

SCHEMA_VERSION = "1"

# The five target metrics of §5.12 / §7.3 (the `Target.metric` literal), named for use in validators and prompts.
MetricName = Literal["assisted_completion", "civilian_exposure", "fire_extent", "crew_risk_steps", "logistics_risk"]

# Canonical delivery order (§6.4): Evacuation, Fire Ops, Logistics.
AGENT_IDS: tuple[AgentId, ...] = ("EVAC", "FIRE", "LOG")

__all__ = [
    "AGENT_IDS", "SCHEMA_VERSION", "MetricName",
    "Acceptance", "AgentId", "AgentMessage", "AgentTurn", "Assignment", "AssignmentDraft", "Commit",
    "EscalationPackage", "EvalBasis", "Evaluation", "Evidence", "Leg", "MessageType", "Metrics", "Objection",
    "Observation", "Plan", "PlanState", "ResourceType", "RoadStatus", "ScheduledEvent", "Target", "TargetCheck",
    "TargetRevision", "TaskType", "TurnMessage", "Violation", "ViolationCode",
]
