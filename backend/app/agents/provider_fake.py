"""TEST PROVIDER: scripted `AgentTurn` outputs for protocol tests (PRD §11.5, invariant 8, AC-026).

This is a labeled test asset. It never runs in live mode: the constructor refuses unless `RESCUEMESH_TEST=1`,
and anything that displays provider state must show `FakeProvider.label` ("TEST PROVIDER").

A script maps `(agent_id, round)` to what the "model" does on successive calls within that turn:
  - a sentinel-form AgentTurn dict (see schema.py): returned as structured output on every call, or
  - a list of steps consumed one per model call (the last step repeats once exhausted):
      dict                       -> structured output
      ToolCalls([...])           -> a tool_calls response (§6.3 tool iteration)
      Refuse() / Truncate()      -> a refusal / max_tokens response (§10.1 failure paths)
      Fail(ProviderError)        -> raise that error (retry tests)
  - a callable `(request) -> dict | list[step]` for tests that need to look at the prompt.
The round is taken from `set_round()` when called, else parsed from the "ROUND: n of 4" line of the user prompt.
Unscripted turns return silence (`{"messages": [], ...}`), which the gate must never read as acceptance (AC-029).
"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.agents.provider import (
    Provider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ToolCall,
    UserText,
)

LABEL = "TEST PROVIDER"
SILENT_TURN: dict[str, Any] = {
    "messages": [],
    "target_revision": {"metric": "", "old_aspiration": 0, "new_aspiration": 0, "reason": ""},
}
_ROUND_RE = re.compile(r"^ROUND: (\d+) of \d+", re.MULTILINE)


@dataclass(frozen=True)
class ToolCalls:
    calls: list[ToolCall]


@dataclass(frozen=True)
class Refuse:
    text: str = ""


@dataclass(frozen=True)
class Truncate:
    text: str = '{"messages": [{"message_type": "PROPOSE", "recipients": [], "pl'


@dataclass(frozen=True)
class Fail:
    error: ProviderError


Step = dict[str, Any] | ToolCalls | Refuse | Truncate | Fail


@dataclass
class ScriptedTurn:
    """Kept for B1-era tests; equivalent to `[Fail?] + [ToolCalls...] + [output]`."""

    output: dict[str, Any]
    tool_calls: list[list[ToolCall]] = field(default_factory=list)
    kind_override: str | None = None
    raise_error: ProviderError | None = None

    def steps(self) -> list[Step]:
        out: list[Step] = []
        if self.raise_error is not None:
            out.append(Fail(self.raise_error))
        out.extend(ToolCalls(calls) for calls in self.tool_calls)
        final: Step = {"refusal": Refuse(), "truncated": Truncate()}.get(self.kind_override, self.output)  # type: ignore[arg-type]
        out.append(final)
        return out


ScriptValue = dict[str, Any] | list[Step] | ScriptedTurn | Callable[[ProviderRequest], Any]
Script = dict[tuple[str, int], ScriptValue]


class FakeProvider(Provider):
    name = "fake"
    label = LABEL

    def __init__(self, script: Script | None = None, *, model: str = "test-provider", latency_ms: int = 0,
                 delay_s: float = 0.0):
        if os.environ.get("RESCUEMESH_TEST") != "1":
            raise ProviderError(f"{LABEL} refused: set RESCUEMESH_TEST=1 to use provider_fake (PRD §11.5)",
                                retryable=False)
        self.model = model
        self.script: Script = dict(script or {})
        self.latency_ms = latency_ms
        self.delay_s = delay_s                            # real wall-clock delay, for deadline/cancellation tests
        self.requests: list[ProviderRequest] = []          # every call, for leak and budget tests
        self._progress: dict[tuple[str, int], int] = {}
        self._current_round: dict[str, int] = {}

    def set_round(self, agent_id: str, round_: int) -> None:
        """Override the round for an agent (otherwise parsed from the prompt's ROUND line)."""
        self._current_round[agent_id] = round_
        self._progress.pop((agent_id, round_), None)

    def reset_progress(self) -> None:
        self._progress.clear()

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        agent = request.agent_id or "?"
        key = (agent, self._round_for(agent, request))
        steps = self._steps_for(key, request)
        idx = self._progress.get(key, 0)
        step = steps[min(idx, len(steps) - 1)]
        self._progress[key] = idx + 1
        return self._respond(step)

    # --- internals ----------------------------------------------------------------------------------------------

    def _round_for(self, agent: str, request: ProviderRequest) -> int:
        if agent in self._current_round:
            return self._current_round[agent]
        for item in request.messages:
            if isinstance(item, UserText):
                m = _ROUND_RE.search(item.text)
                if m:
                    return int(m.group(1))
        return 1

    def _steps_for(self, key: tuple[str, int], request: ProviderRequest) -> list[Step]:
        value: Any = self.script.get(key, SILENT_TURN)
        if callable(value) and not isinstance(value, dict):
            value = value(request)
        if isinstance(value, ScriptedTurn):
            return value.steps()
        if isinstance(value, list):
            return value or [SILENT_TURN]
        return [value]

    def _respond(self, step: Step) -> ProviderResponse:
        common = dict(provider="fake", model=self.model, latency_ms=self.latency_ms, tokens_in=0, tokens_out=0)
        if isinstance(step, Fail):
            raise step.error
        if isinstance(step, ToolCalls):
            return ProviderResponse(kind="tool_calls", tool_calls=tuple(step.calls), stop_reason="tool_use", **common)
        if isinstance(step, Refuse):
            return ProviderResponse(kind="refusal", output_text=step.text, stop_reason="refusal", **common)
        if isinstance(step, Truncate):
            return ProviderResponse(kind="truncated", output_text=step.text, stop_reason="max_tokens", **common)
        return ProviderResponse(kind="output", output_json=step, output_text=_compact(step), stop_reason="end_turn",
                                **common)


def _compact(obj: dict[str, Any]) -> str:
    import json
    return json.dumps(obj, separators=(",", ":"))
