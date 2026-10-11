"""Model-facing schema for `AgentTurn`, sentinel conversion and semantic validation (PRD §7.5, §6.5, D-17).

Why sentinels: Anthropic strict schemas allow at most 16 union-typed parameters and no numeric bounds or
`maxLength`; OpenAI strict mode requires every property to be present. `AgentTurn` has ~21 nullable fields, so
the JSON Schema sent to the model has **no nulls and no unions**:

    absent string  -> ""          absent integer -> -1        absent list -> []
    absent objection -> {"kind": "none", ...}                absent target revision -> {"metric": "", ...}

`parse_turn()` converts sentinels back to `None` and yields the Pydantic `AgentTurn` from contracts.py.
All bounds (rationale length, counts, step ranges, held evidence) are enforced by `validate_turn()` after
parsing, which feeds the single repair attempt (§3.5, §10.2).
"""

from __future__ import annotations

import copy
import types
import typing
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.agents.contracts import (
    AgentId,
    AgentTurn,
    AssignmentDraft,
    Objection,
    Target,
    TargetRevision,
    TurnMessage,
)

STR_SENTINEL = ""
INT_SENTINEL = -1
RATIONALE_MAX = 280
AMENDMENT_MAX = 200
MESSAGES_MAX = 3
OBJECTION_NONE_KIND = "none"

# §6.11: the agent supplies only these; `by` and `dp_id` are filled by the runtime.
_MODEL_FACING_REVISION_FIELDS = ("metric", "old_aspiration", "new_aspiration", "reason")


# --- schema generation ---------------------------------------------------------------------------------

def turn_output_schema() -> dict[str, Any]:
    """JSON Schema for the model's structured output: AgentTurn with sentinels, strict-mode compatible."""
    raw = AgentTurn.model_json_schema()
    defs = raw.pop("$defs", {})
    schema = _strictify(raw, defs)

    msg_props = schema["properties"]["messages"]["items"]["properties"]
    objection = msg_props["objection"]
    objection["properties"]["kind"]["enum"] = [OBJECTION_NONE_KIND, *objection["properties"]["kind"]["enum"]]
    objection["description"] = f'Objection for CHALLENGE only; otherwise {{"kind": "{OBJECTION_NONE_KIND}"}} with other fields "" .'

    revision = schema["properties"]["target_revision"]
    revision["properties"] = {k: revision["properties"][k] for k in _MODEL_FACING_REVISION_FIELDS}
    revision["required"] = list(_MODEL_FACING_REVISION_FIELDS)
    revision["description"] = (
        'Relax one of YOUR aspirations toward (never past) its floor. If none this turn: {"metric": "", '
        '"old_aspiration": 0, "new_aspiration": 0, "reason": ""}.'
    )
    schema["description"] = (
        f"One negotiation turn: 0-{MESSAGES_MAX} messages (0 = deliberate silence), at most one PROPOSE or "
        f'COUNTERPROPOSE. Absent values use sentinels: "" for strings, {INT_SENTINEL} for integers, [] for lists.'
    )
    return schema


def _strictify(node: Any, defs: dict[str, Any]) -> Any:
    """Inline $refs, strip nulls from unions, require every property, forbid extras, drop unsupported keywords."""
    if isinstance(node, list):
        return [_strictify(n, defs) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target = defs[node["$ref"].rsplit("/", 1)[-1]]
        merged = {**copy.deepcopy(target), **{k: v for k, v in node.items() if k != "$ref"}}
        return _strictify(merged, defs)
    if "anyOf" in node:
        options = [o for o in node["anyOf"] if o.get("type") != "null"]
        if len(options) != 1:
            raise ValueError(f"unsupported union in model-facing schema: {node}")
        merged = {**options[0], **{k: v for k, v in node.items() if k != "anyOf"}}
        return _strictify(merged, defs)

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key in ("default", "title", "minimum", "maximum", "maxLength", "minLength", "uniqueItems", "format"):
            continue
        out[key] = _strictify(value, defs)
    if out.get("type") == "object" and "properties" in out:
        out["required"] = list(out["properties"].keys())
        out["additionalProperties"] = False
    return out


# --- sentinel -> None -------------------------------------------------------------------------------------

def parse_turn(raw: dict[str, Any], *, agent_id: AgentId, dp_id: str) -> AgentTurn:
    """Convert a sentinel-form model output into `AgentTurn`. Raises `pydantic.ValidationError` on bad shape."""
    if not isinstance(raw, dict):
        raise ValueError("turn output must be a JSON object")
    data = copy.deepcopy(raw)
    messages = data.get("messages", [])
    if not isinstance(messages, list):
        raise ValueError("'messages' must be a list")
    data["messages"] = [_desentinel_message(m) for m in messages]

    revision = data.get("target_revision")
    if not isinstance(revision, dict) or revision.get("metric", STR_SENTINEL) == STR_SENTINEL:
        data["target_revision"] = None
    else:
        data["target_revision"] = {
            "by": agent_id,
            "dp_id": dp_id,
            **{k: revision.get(k) for k in _MODEL_FACING_REVISION_FIELDS},
        }
    return AgentTurn.model_validate(data)


def parse_assignment_drafts(raw: Any) -> list[AssignmentDraft]:
    """Sentinel-form assignment list (a tool argument or a message plan) -> typed drafts. Raises on bad shape."""
    if not isinstance(raw, list):
        raise ValueError("plan must be a list of assignments")
    return [AssignmentDraft.model_validate(_desentinel_fields(a, AssignmentDraft) if isinstance(a, dict) else a)
            for a in raw]


def _desentinel_message(msg: Any) -> Any:
    if not isinstance(msg, dict):
        return msg
    out = _desentinel_fields(msg, TurnMessage)
    objection = out.get("objection")
    if isinstance(objection, dict):
        if objection.get("kind") == OBJECTION_NONE_KIND:
            out["objection"] = None
        else:
            out["objection"] = _desentinel_fields(objection, Objection)
    plan = out.get("plan")
    if isinstance(plan, list):
        out["plan"] = [_desentinel_fields(a, AssignmentDraft) if isinstance(a, dict) else a for a in plan] or None
    return out


def _desentinel_fields(data: dict[str, Any], model: type) -> dict[str, Any]:
    """For each `X | None` field of `model`, map the sentinel of X back to None."""
    out = dict(data)
    for name, info in model.model_fields.items():
        if name not in out:
            continue
        inner = _optional_inner(info.annotation)
        if inner is None:
            continue
        value = out[name]
        if inner is str and value == STR_SENTINEL:
            out[name] = None
        elif inner is int and value == INT_SENTINEL:
            out[name] = None
    return out


def _optional_inner(annotation: Any) -> Any | None:
    """Return X for `X | None` annotations, else None."""
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1 and len(typing.get_args(annotation)) == 2:
            return args[0]
    return None


def validation_error_lines(err: ValidationError) -> list[str]:
    """Compact error list for the repair prompt (§10.1: 'one repair call with the error list')."""
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors()]


# --- semantic validation (§7.5 last paragraph, §6.5, §6.11) -------------------------------------------

@dataclass
class TurnContext:
    """What the validator may know about the caller's situation. Built by the actor from held state only."""

    agent_id: AgentId
    round: int
    step: int
    horizon: int
    held_evidence_ids: set[str] = field(default_factory=set)
    known_plan_ids: set[str] = field(default_factory=set)
    current_plan_hashes: set[str] = field(default_factory=set)
    own_targets: list[Target] = field(default_factory=list)
    known_resource_ids: set[str] = field(default_factory=set)

    @property
    def peers(self) -> set[str]:
        return {"EVAC", "FIRE", "LOG"} - {self.agent_id}


def validate_turn(turn: AgentTurn, ctx: TurnContext) -> list[str]:
    """Return semantic errors (empty = valid). Each error names the message index and the rule."""
    errors: list[str] = []
    if len(turn.messages) > MESSAGES_MAX:
        errors.append(f"messages: at most {MESSAGES_MAX} per turn, got {len(turn.messages)}")
    new_plans = [m for m in turn.messages if m.message_type in ("PROPOSE", "COUNTERPROPOSE")]
    if len(new_plans) > 1:
        errors.append("messages: at most one PROPOSE or COUNTERPROPOSE per turn")

    for i, m in enumerate(turn.messages):
        errors.extend(f"messages[{i}]: {e}" for e in _validate_message(m, ctx))

    if turn.target_revision is not None:
        errors.extend(f"target_revision: {e}" for e in _validate_revision(turn.target_revision, ctx))
    return errors


def _validate_message(m: TurnMessage, ctx: TurnContext) -> list[str]:
    errs: list[str] = []
    if len(m.rationale) > RATIONALE_MAX:
        errs.append(f"rationale exceeds {RATIONALE_MAX} characters ({len(m.rationale)})")
    bad_recipients = set(m.recipients) - ctx.peers
    if bad_recipients:
        errs.append(f"recipients must be peers, not {sorted(bad_recipients)}")
    unheld = [e for e in [*m.evidence_ids, *m.shared_evidence_ids] if e not in ctx.held_evidence_ids]
    if unheld:
        errs.append(f"UNKNOWN_EVIDENCE: you do not hold {unheld}")

    t = m.message_type
    if t in ("COUNTERPROPOSE", "CHALLENGE", "ACCEPT", "WITHDRAW", "ESCALATE") and ctx.round < 2:
        errs.append(f"{t} is allowed from round 2 (§6.5)")

    if t in ("PROPOSE", "COUNTERPROPOSE"):
        if not m.plan:
            errs.append(f"{t} requires a non-empty plan")
        else:
            errs.extend(_validate_plan_drafts(m.plan, ctx))
    if t == "COUNTERPROPOSE":
        if not m.parent_plan_id:
            errs.append("COUNTERPROPOSE requires parent_plan_id")
        elif ctx.known_plan_ids and m.parent_plan_id not in ctx.known_plan_ids:
            errs.append(f"INVALID_REFERENCE: unknown parent_plan_id {m.parent_plan_id!r}")
        if not m.caused_by:
            errs.append("COUNTERPROPOSE requires caused_by (message or evidence IDs behind the revision, FR-026)")
    if t == "CHALLENGE":
        if not m.target_plan_id:
            errs.append("CHALLENGE requires target_plan_id")
        elif ctx.known_plan_ids and m.target_plan_id not in ctx.known_plan_ids:
            errs.append(f"INVALID_REFERENCE: unknown target_plan_id {m.target_plan_id!r}")
        if m.objection is None:
            errs.append("CHALLENGE requires an objection")
        elif m.objection.proposed_amendment and len(m.objection.proposed_amendment) > AMENDMENT_MAX:
            errs.append(f"objection.proposed_amendment exceeds {AMENDMENT_MAX} characters")
    if t == "REQUEST_EVIDENCE":
        if not (m.requested_evidence_id or m.requested_topic):
            errs.append("REQUEST_EVIDENCE requires requested_evidence_id or requested_topic")
        if not m.recipients:
            errs.append("REQUEST_EVIDENCE requires a named recipient (the holder)")
    if t == "SHARE_EVIDENCE" and not m.shared_evidence_ids:
        errs.append("SHARE_EVIDENCE requires shared_evidence_ids")
    if t in ("ACCEPT", "WITHDRAW"):
        if not m.target_plan_hash:
            errs.append(f"{t} requires target_plan_hash")
        elif ctx.current_plan_hashes and m.target_plan_hash not in ctx.current_plan_hashes:
            errs.append(f"INVALID_REFERENCE: {m.target_plan_hash!r} is not a current plan hash")
    if t == "ESCALATE" and not m.reason:
        errs.append("ESCALATE requires reason")
    return errs


def _validate_plan_drafts(plan: list[AssignmentDraft], ctx: TurnContext) -> list[str]:
    errs: list[str] = []
    for j, a in enumerate(plan):
        if a.start_step is not None and not (ctx.step <= a.start_step <= ctx.horizon):
            errs.append(f"plan[{j}].start_step {a.start_step} outside [{ctx.step}, {ctx.horizon}]")
        if ctx.known_resource_ids and a.resource_id not in ctx.known_resource_ids:
            errs.append(f"plan[{j}].resource_id {a.resource_id!r}: UNKNOWN_RESOURCE")
    return errs


def _validate_revision(rev: TargetRevision, ctx: TurnContext) -> list[str]:
    """§6.11: only the agent's own aspiration, only toward its floor, never past it (TARGET_BELOW_FLOOR)."""
    target = next((t for t in ctx.own_targets if t.metric == rev.metric), None)
    if target is None:
        return [f"metric {rev.metric!r} is not one of your targets"]
    if not target.revisable_by_agent:
        return [f"metric {rev.metric!r} is not revisable by agents"]
    if target.direction == "max":
        toward_floor = rev.new_aspiration <= target.aspiration
        past_floor = rev.new_aspiration < target.floor
    else:
        toward_floor = rev.new_aspiration >= target.aspiration
        past_floor = rev.new_aspiration > target.floor
    errs = []
    if not toward_floor:
        errs.append("revision must move the aspiration toward the floor, not tighten it")
    if past_floor:
        errs.append(f"TARGET_BELOW_FLOOR: new_aspiration {rev.new_aspiration} passes floor {target.floor}")
    if not rev.reason:
        errs.append("reason is required")
    return errs
