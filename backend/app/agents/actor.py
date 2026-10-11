"""One negotiation actor: the §6.3 turn lifecycle with the §6.4 / §10.1 / §10.2 bounds.

    IDLE → BUILDING_PROMPT → CALLING_MODEL ⇄ RUNNING_TOOL (≤ 2 tool iterations)
         → PARSING → (VALIDATING → REPAIRING ≤ 1) → SUBMITTED → IDLE
    any state → CANCELLED (event injected, reset, budget exceeded)
    2 consecutive failed turns → DEGRADED (stays silent; triggers escalation, §6.9)

An actor owns exactly one `ActorState` (private, §4.3) and sees the world only through the `BeliefView` the router
hands it each turn. It never ranks plans, never talks to peers directly and never touches the authoritative world:
tools run through `ToolContext(agent_id=...)` on the view (§4.4). Model calls that were in flight when a turn is
cancelled are still recorded in the ledger (§4.6).

Three actors are composed by the router in B3; this module knows nothing about rounds beyond the number it is told.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from app.agents.contracts import AgentId, AgentTurn, Target, TargetRevision
from app.agents.prompt import (
    InboxItem,
    OpenPlan,
    build_observation,
    build_repair_prompt,
    build_system_prompt,
    build_user_prompt,
    no_more_tools_note,
)
from app.agents.provider import (
    DEFAULT_TURN_DEADLINE_S,
    AssistantToolCalls,
    CallLedgerRow,
    CallPurpose,
    MessageItem,
    Provider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ToolResult,
    ToolResults,
    UserText,
)
from app.agents.schema import TurnContext, parse_turn, turn_output_schema, validate_turn, validation_error_lines
from app.agents.sim_stub import BeliefView, SimService
from app.agents.tools import MAX_TOOL_EXECUTIONS, ToolContext, ToolLedgerRow, execute_tool, tool_specs

TurnStatus = Literal["submitted", "silent", "failed", "degraded", "late", "cancelled"]

MAX_MODEL_CALLS_PER_TURN = 4      # 1 decision + ≤ 2 tool iterations + ≤ 1 repair (§6.4)
MAX_TOOL_ITERATIONS = 2
MAX_REPAIRS = 1
DEGRADED_AFTER_FAILURES = 2       # §6.3


@dataclass
class ActorState:
    """Private state of one actor (§4.3). Nothing here is shared with another actor object."""

    agent_id: str   # one of AGENT_IDS for the three negotiating actors; "single_agent" for the §11.2 baseline
    targets: dict[AgentId, list[Target]]                 # public table (§6.1); own row is read from here
    aspirations: dict[str, float] = field(default_factory=dict)   # own current aspirations after revisions (§6.11)
    consecutive_failures: int = 0
    degraded: bool = False
    turns_run: int = 0
    sent_message_ids: list[str] = field(default_factory=list)
    received_message_ids: list[str] = field(default_factory=list)
    revisions: list[TargetRevision] = field(default_factory=list)

    def __post_init__(self) -> None:
        for t in self.targets.get(self.agent_id, []):
            self.aspirations.setdefault(t.metric, t.aspiration)

    def own_targets(self) -> list[Target]:
        """Own targets with the current aspirations applied — what validate_turn and the prompt use."""
        return [t.model_copy(update={"aspiration": self.aspirations.get(t.metric, t.aspiration)})
                for t in self.targets.get(self.agent_id, [])]

    def apply_revision(self, revision: TargetRevision) -> None:
        """Called by the router at the round boundary once the revision is accepted and logged (§6.11)."""
        self.aspirations[revision.metric] = revision.new_aspiration
        self.revisions.append(revision)


@dataclass
class TurnInput:
    view: BeliefView
    round: int
    dp_id: str
    run_id: str
    inbox: list[InboxItem] = field(default_factory=list)
    open_plans: list[OpenPlan] = field(default_factory=list)
    time_left_s: float = 30.0
    deadline_s: float = DEFAULT_TURN_DEADLINE_S
    public_events: list[Any] = field(default_factory=list)
    locked_assignments: list[Any] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)   # router notices, e.g. commit-rejection violation codes (§4.3)
    history: Callable[[int | None], list[dict[str, Any]]] = lambda rounds: []


@dataclass
class TurnOutcome:
    agent_id: str   # one of AGENT_IDS for the three negotiating actors; "single_agent" for the §11.2 baseline
    status: TurnStatus
    turn: AgentTurn | None = None
    errors: list[str] = field(default_factory=list)
    model_calls: int = 0
    call_rows: list[CallLedgerRow] = field(default_factory=list)
    tool_rows: list[ToolLedgerRow] = field(default_factory=list)
    transcript: list[dict[str, str]] = field(default_factory=list)   # prompt capture (§10.5) and leak tests
    raw_output: str = ""
    latency_ms: int = 0

    @property
    def counts_as_failed_turn(self) -> bool:
        return self.status in ("failed", "late")


PromptBuilder = Callable[[ActorState, TurnInput], tuple[str, str]]


def default_prompt_builder(state: ActorState, inp: TurnInput) -> tuple[str, str]:
    """§6.13 per-role prompt. Typed inputs only; the view already carries only held evidence (§4.4 #1)."""
    system = build_system_prompt(state.agent_id, state.targets, state.aspirations)  # type: ignore[arg-type]
    observation = build_observation(state.agent_id, inp.view, run_id=inp.run_id, dp_id=inp.dp_id,  # type: ignore[arg-type]
                                    round_=inp.round, targets=state.targets, public_events=inp.public_events,
                                    locked_assignments=inp.locked_assignments)
    user = build_user_prompt(observation, inp.inbox, inp.open_plans, round_=inp.round, time_left_s=inp.time_left_s,
                             notices=inp.notices)
    return system, user


class Actor:
    def __init__(self, state: ActorState, provider: Provider, sim: SimService, *,
                 max_model_calls: int = MAX_MODEL_CALLS_PER_TURN,
                 max_tool_iterations: int = MAX_TOOL_ITERATIONS,
                 max_tool_executions: int = MAX_TOOL_EXECUTIONS,
                 prompt_builder: PromptBuilder | None = None):
        self.state = state
        self.provider = provider
        self.sim = sim
        self.max_model_calls = max_model_calls
        self.max_tool_iterations = max_tool_iterations
        self.max_tool_executions = max_tool_executions
        self.prompt_builder = prompt_builder or default_prompt_builder   # the single-agent baseline swaps the prompt only
        self.last_outcome: TurnOutcome | None = None

    @property
    def agent_id(self) -> AgentId:
        return self.state.agent_id

    # --- public ---------------------------------------------------------------------------------------------------

    async def run_turn(self, inp: TurnInput) -> TurnOutcome:
        """Run one bounded turn. Raises `asyncio.CancelledError` through (after recording), like any task."""
        if self.state.degraded:
            outcome = TurnOutcome(agent_id=self.agent_id, status="degraded",
                                  errors=["actor is DEGRADED after consecutive failed turns (§6.3)"])
            self.last_outcome = outcome
            return outcome

        outcome = TurnOutcome(agent_id=self.agent_id, status="failed")
        self.last_outcome = outcome
        self.state.turns_run += 1
        started = time.perf_counter()
        try:
            async with asyncio.timeout(inp.deadline_s):
                await self._turn(inp, outcome)
        except TimeoutError:
            outcome.status = "late"
            outcome.errors.append(f"turn deadline {inp.deadline_s}s exceeded (§6.10 LATE)")
            if outcome.call_rows and outcome.call_rows[-1].cancelled:
                outcome.call_rows[-1].status = "timeout"
        except asyncio.CancelledError:
            outcome.status = "cancelled"
            outcome.errors.append("turn cancelled (event injected, reset or budget exceeded)")
            raise
        finally:
            outcome.latency_ms = int((time.perf_counter() - started) * 1000)
        self._settle(outcome)
        return outcome

    # --- lifecycle --------------------------------------------------------------------------------------------------

    async def _turn(self, inp: TurnInput, out: TurnOutcome) -> None:
        state = self.state
        # BUILDING_PROMPT
        system, user = self.prompt_builder(state, inp)
        out.transcript += [{"role": "system", "content": system}, {"role": "user", "content": user}]
        state.received_message_ids += [item.message.message_id for item in inp.inbox]

        ctx = TurnContext(
            agent_id=state.agent_id, round=inp.round, step=inp.view.step, horizon=inp.view.world.get("horizon", 60),
            held_evidence_ids={e.evidence_id for e in inp.view.held_evidence},
            known_plan_ids={p.plan_id for p in inp.open_plans},
            current_plan_hashes={p.plan_hash for p in inp.open_plans},
            own_targets=state.own_targets(), known_resource_ids=set(inp.view.world.get("resources", {})),
        )
        tool_ctx = ToolContext(agent_id=state.agent_id, sim=self.sim, view=inp.view, run_id=inp.run_id,
                               dp_id=inp.dp_id, history=inp.history)

        messages: list[MessageItem] = [UserText(user)]
        schema = turn_output_schema()
        specs = tool_specs()
        purpose: CallPurpose = "decision"
        tool_iterations = 0
        tool_executions = 0
        repairs = 0

        while True:
            if out.model_calls >= self.max_model_calls:
                out.errors.append(f"model call budget ({self.max_model_calls}) exhausted (§6.4)")
                return
            tools_allowed = tool_iterations < self.max_tool_iterations
            request = ProviderRequest(system=system, messages=tuple(messages), tools=specs if tools_allowed else (),
                                      output_schema=schema, timeout_s=inp.deadline_s, purpose=purpose,
                                      agent_id=state.agent_id)
            resp = await self._call(request, out)
            if resp is None:                       # provider failed after its one retry (§10.1)
                return

            # RUNNING_TOOL
            if resp.kind == "tool_calls" and tools_allowed:
                tool_iterations += 1
                results: list[ToolResult] = []
                for call in resp.tool_calls:
                    if tool_executions >= self.max_tool_executions:
                        results.append(ToolResult(call_id=call.call_id, is_error=True,
                                                  content='{"error": "tool execution budget for this turn is used up"}'))
                        continue
                    tool_executions += 1
                    result, row = execute_tool(tool_ctx, call)
                    results.append(result)
                    out.tool_rows.append(row)
                    out.transcript.append({"role": "tool", "content": f"{call.name}: {result.content}"})
                messages.append(AssistantToolCalls(calls=resp.tool_calls, text=resp.output_text))
                messages.append(ToolResults(results=tuple(results)))
                if tool_iterations >= self.max_tool_iterations:
                    messages.append(UserText(no_more_tools_note()))
                purpose = "tool_iteration"
                continue

            # PARSING → VALIDATING
            out.raw_output = resp.output_text
            out.transcript.append({"role": "assistant", "content": resp.output_text})
            errors = self._parse_and_validate(resp, ctx, inp.dp_id, inp.view, out)
            if not errors:
                out.status = "submitted" if out.turn and out.turn.messages else "silent"
                return

            # REPAIRING (≤ 1)
            if repairs >= MAX_REPAIRS:
                out.errors = errors
                return
            repairs += 1
            out.errors = list(errors)
            if resp.output_text:
                messages.append(AssistantToolCalls(calls=(), text=resp.output_text))
            messages.append(UserText(build_repair_prompt(errors, resp.output_text)))
            purpose = "repair"

    def _parse_and_validate(self, resp: ProviderResponse, ctx: TurnContext, dp_id: str, view: BeliefView,
                            out: TurnOutcome) -> list[str]:
        if resp.kind == "refusal":
            return [f"model refused to answer (stop_reason={resp.stop_reason}); output must be AgentTurn JSON"]
        if resp.kind == "truncated":
            return [f"model output was truncated or not a JSON object (stop_reason={resp.stop_reason})"]
        if resp.kind == "tool_calls":
            return ["tool calls are not allowed after the tool budget; return the AgentTurn JSON"]
        try:
            turn = parse_turn(resp.output_json or {}, agent_id=self.agent_id, dp_id=dp_id)
        except ValidationError as e:
            return validation_error_lines(e)
        except ValueError as e:
            return [str(e)]
        errors = validate_turn(turn, ctx)
        # §6.4: a new plan must be valid on the proposer's own view; if not, it is bounced back as this turn's
        # repair attempt (inside the deadline) rather than delivered. The router keeps a safety-net check.
        for i, m in enumerate(turn.messages):
            if m.message_type in ("PROPOSE", "COUNTERPROPOSE") and m.plan:
                for v in self.sim.validate_plan(view, m.plan):
                    errors.append(f"messages[{i}]: plan invalid on your own view: {v.code} — {v.detail}")
        if not errors:
            out.turn = turn
        return errors

    async def _call(self, request: ProviderRequest, out: TurnOutcome) -> ProviderResponse | None:
        """One model call with the §10.1 single retry. Returns None when the call ultimately failed."""
        for attempt in (0, 1):
            out.model_calls += 1
            try:
                resp = await self.provider.complete(request)
            except asyncio.CancelledError:
                out.call_rows.append(CallLedgerRow(provider=self.provider.name, model=self.provider.model,
                                                   agent=self.agent_id, purpose=request.purpose, tokens_in=None,
                                                   tokens_out=None, latency_ms=0, status="cancelled", cancelled=True))
                raise
            except ProviderError as e:
                out.call_rows.append(CallLedgerRow(provider=self.provider.name, model=self.provider.model,
                                                   agent=self.agent_id, purpose=request.purpose, tokens_in=None,
                                                   tokens_out=None, latency_ms=0, status="error", error=str(e)))
                if e.retryable and attempt == 0 and out.model_calls < self.max_model_calls:
                    continue
                out.errors.append(f"provider error: {e}")
                return None
            out.call_rows.append(CallLedgerRow.from_response(request, resp))
            return resp
        return None

    def _settle(self, outcome: TurnOutcome) -> None:
        if outcome.counts_as_failed_turn:
            self.state.consecutive_failures += 1
            if self.state.consecutive_failures >= DEGRADED_AFTER_FAILURES:
                self.state.degraded = True
        elif outcome.status in ("submitted", "silent"):
            self.state.consecutive_failures = 0
