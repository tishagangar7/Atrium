"""Model-callable tools: specs and implementations (PRD §6.2, §4.4, §10.3, §10.5).

All four tools run on the caller's belief view. The runtime injects `ToolContext(agent_id=...)`; the schemas carry
no `agent_id` argument, and one supplied by the model is ignored and recorded in the tool ledger row (§4.4 #2).
Model arguments are validated before anything runs and unknown IDs fail closed (§10.3): a bad call returns a
`ToolResult(is_error=True)` to the model and counts toward the turn's tool budget — it never crashes the actor.
Schemas are strict-compatible: every property required, `additionalProperties: false`, no unions.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.agents.contracts import AgentId, AssignmentDraft
from app.agents.provider import Stopwatch, ToolCall, ToolResult, ToolSpec
from app.agents.schema import parse_assignment_drafts, turn_output_schema
from app.agents.sim_stub import HORIZON, BeliefView, SimService

MAX_TOOL_EXECUTIONS = 4   # per actor turn (§10.2)
SUMMARY_CHARS = 200


class ToolError(Exception):
    """Bad arguments or an unknown reference; returned to the model as an error tool result (§10.1)."""


@dataclass
class ToolLedgerRow:
    """One row of the tool ledger (§10.5)."""

    agent: AgentId
    tool: str
    args_summary: str
    result_summary: str
    sim_ms: int
    evaluation_id: str | None = None
    is_error: bool = False
    ignored_args: list[str] = field(default_factory=list)   # e.g. a model-supplied agent_id (§4.4)


@dataclass
class ToolContext:
    """Everything a tool may see. Built by the actor from its own state; never holds the authoritative world."""

    agent_id: AgentId
    sim: SimService
    view: BeliefView
    run_id: str
    dp_id: str
    # Router log restricted to messages the caller sent or received (§6.2). None = all rounds.
    history: Callable[[int | None], list[dict[str, Any]]] = lambda rounds: []


# --- schemas ----------------------------------------------------------------------------------------------------

def _obj(properties: dict[str, Any], description: str | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "object", "properties": properties, "required": list(properties),
                              "additionalProperties": False}
    if description:
        schema["description"] = description
    return schema


def plan_schema() -> dict[str, Any]:
    """The sentinel-form assignment list, identical to `TurnMessage.plan` in the turn schema."""
    return turn_output_schema()["properties"]["messages"]["items"]["properties"]["plan"]


def tool_specs() -> tuple[ToolSpec, ...]:
    return (
        ToolSpec(
            name="find_routes",
            description="Up to 3 open routes between two nodes for the given resource, with travel steps, "
                        "computed on your current knowledge of the road network.",
            input_schema=_obj({
                "resource_id": {"type": "string", "description": "Resource that will drive (crews need engine-capable roads)."},
                "origin": {"type": "string", "description": "Node id, e.g. BASE"},
                "destination": {"type": "string", "description": "Node id, e.g. PR"},
            }),
        ),
        ToolSpec(
            name="validate_plan",
            description="Check a plan against hard constraints on your current knowledge. Returns violation codes; "
                        "an empty list means the plan is feasible as far as you know.",
            input_schema=_obj({"plan": plan_schema()}),
        ),
        ToolSpec(
            name="evaluate_plan",
            description="Run a plan in the simulator on your current knowledge and return the forecast Evaluation "
                        "(metrics, violations, leg timing, your target checks). The only source of outcome numbers.",
            input_schema=_obj({
                "plan": plan_schema(),
                "horizon": {"type": "integer", "description": "Simulated steps to run; -1 for the default (60)."},
            }),
        ),
        ToolSpec(
            name="get_negotiation_history",
            description="Compact log of this decision point: messages you sent or received, with plan ids and hashes.",
            input_schema=_obj({
                "rounds": {"type": "integer", "description": "How many most recent rounds; -1 for all."},
            }),
        ),
    )


# --- execution --------------------------------------------------------------------------------------------------

def execute_tool(ctx: ToolContext, call: ToolCall) -> tuple[ToolResult, ToolLedgerRow]:
    """Run one tool call on the caller's view. Never raises for model mistakes; returns an error result instead."""
    args = dict(call.arguments) if isinstance(call.arguments, dict) else {}
    ignored = [k for k in ("agent_id",) if k in args]
    for k in ignored:
        args.pop(k)

    evaluation_id: str | None = None
    with Stopwatch() as sw:
        try:
            impl = _DISPATCH.get(call.name)
            if impl is None:
                raise ToolError(f"unknown tool {call.name!r}")
            payload = impl(ctx, args)
            evaluation_id = payload.get("evaluation_id") if call.name == "evaluate_plan" else None
            result = ToolResult(call_id=call.call_id, content=json.dumps(payload, separators=(",", ":")))
            summary = _result_summary(call.name, payload)
            is_error = False
        except ToolError as e:
            result = ToolResult(call_id=call.call_id, content=json.dumps({"error": str(e)}), is_error=True)
            summary, is_error = f"error: {e}", True
        except (ValidationError, ValueError, KeyError, TypeError) as e:
            detail = _short(str(e))
            result = ToolResult(call_id=call.call_id, content=json.dumps({"error": f"invalid arguments: {detail}"}),
                                is_error=True)
            summary, is_error = f"error: invalid arguments: {detail}", True
    row = ToolLedgerRow(agent=ctx.agent_id, tool=call.name, args_summary=_short(json.dumps(args, separators=(",", ":"))),
                        result_summary=_short(summary), sim_ms=sw.ms, evaluation_id=evaluation_id,
                        is_error=is_error, ignored_args=ignored)
    return result, row


def _find_routes(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    resource_id, origin, destination = (_require_str(args, k) for k in ("resource_id", "origin", "destination"))
    if resource_id not in ctx.view.world["resources"]:
        raise ToolError(f"UNKNOWN_RESOURCE {resource_id!r}")
    nodes = ctx.view.world["nodes"]
    for n in (origin, destination):
        if n not in nodes:
            raise ToolError(f"unknown node {n!r}; nodes are {sorted(nodes)}")
    routes = ctx.sim.find_routes(ctx.view, origin, destination, resource_id=resource_id)
    return {"routes": [{"route_ids": r.route_ids, "nodes": r.nodes, "travel_steps": r.travel_steps} for r in routes],
            "basis": ctx.view.basis}


def _validate_plan(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    drafts = parse_assignment_drafts(args.get("plan"))
    violations = ctx.sim.validate_plan(ctx.view, drafts)
    return {"valid": not violations, "violations": [v.model_dump(mode="json") for v in violations],
            "basis": ctx.view.basis}


def _evaluate_plan(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    drafts = parse_assignment_drafts(args.get("plan"))
    if not drafts:
        raise ToolError("plan is empty")
    horizon = args.get("horizon", -1)
    if horizon in (-1, None):
        horizon = HORIZON
    if not isinstance(horizon, int) or isinstance(horizon, bool) or not (1 <= horizon <= HORIZON):
        raise ToolError(f"horizon must be an integer in [1, {HORIZON}] or -1 for the default")
    evaluation = ctx.sim.evaluate_plan(ctx.view, drafts, plan_hash=draft_plan_hash(drafts), horizon=horizon)
    payload = evaluation.model_dump(mode="json")
    payload["note"] = ("Forecast on your current knowledge. plan_hash is the hash of this draft; the delivered "
                       "plan hash may differ after normalization.")
    return payload


def _history(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    rounds = args.get("rounds", -1)
    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < -1:
        raise ToolError("rounds must be a non-negative integer or -1 for all")
    return {"messages": ctx.history(None if rounds == -1 else rounds)}


_DISPATCH: dict[str, Callable[[ToolContext, dict[str, Any]], dict[str, Any]]] = {
    "find_routes": _find_routes,
    "validate_plan": _validate_plan,
    "evaluate_plan": _evaluate_plan,
    "get_negotiation_history": _history,
}


# --- helpers ----------------------------------------------------------------------------------------------------

def draft_plan_hash(drafts: list[AssignmentDraft]) -> str:
    """Hash of an un-normalized draft, for tool-call evaluation ids only. The canonical plan hash (§6.7) is
    computed by the router at delivery over the normalized plan (B4, negotiation/hash.py)."""
    payload = json.dumps([d.model_dump(mode="json") for d in drafts], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value:
        raise ToolError(f"{key} must be a non-empty string")
    return value


def _result_summary(tool: str, payload: dict[str, Any]) -> str:
    if tool == "find_routes":
        return f"{len(payload['routes'])} routes"
    if tool == "validate_plan":
        codes = sorted({v["code"] for v in payload["violations"]})
        return "valid" if payload["valid"] else f"{len(payload['violations'])} violations: {', '.join(codes)}"
    if tool == "evaluate_plan":
        return f"{payload['evaluation_id']}: {'valid' if payload['valid'] else 'invalid'}"
    return f"{len(payload.get('messages', []))} messages"


def _short(text: str, n: int = SUMMARY_CHARS) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"
