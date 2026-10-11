"""Anthropic Messages API adapter (PRD §3.4 "Model access", §3.5, Appendix B).

Structured output via `output_config.format` (`json_schema`), strict tools via `strict: true`. The model id
comes from settings (`RESCUEMESH_MODEL`), never from code. `thinking` is left to the model's default and
`output_config.effort` is sent only when `RESCUEMESH_EFFORT` is set, because the runtime tier is chosen at H+1
and the two knobs are not accepted by every tier. Refusals and truncation are reported as response kinds and
handled by the actor as malformed output (§10.1) — no server-side fallback model is configured.

The SDK client performs at most one retry (timeout, 429, 5xx) and the request timeout equals the turn deadline,
so a call never outlives its round (§6.4, §10.1).
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from app.agents.provider import (
    AssistantToolCalls,
    MessageItem,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    Stopwatch,
    ToolCall,
    ToolResults,
    UserText,
)


class AnthropicProvider:
    name = "anthropic"
    label = "LIVE"

    def __init__(self, model: str, *, effort: str | None = None, client: Any | None = None):
        self.model = model
        self.effort = effort
        # Credentials resolve from the environment (ANTHROPIC_API_KEY loaded from backend/.env).
        self._client = client or anthropic.AsyncAnthropic(max_retries=1)

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        kwargs = self._build_kwargs(request)
        try:
            with Stopwatch() as sw:
                msg = await self._client.with_options(timeout=request.timeout_s).messages.create(**kwargs)
        except anthropic.APITimeoutError as e:
            raise ProviderError(f"anthropic timeout after {request.timeout_s}s", retryable=True) from e
        except anthropic.RateLimitError as e:
            raise ProviderError("anthropic rate limited", retryable=True, status=429) from e
        except anthropic.APIStatusError as e:
            raise ProviderError(f"anthropic HTTP {e.status_code}: {e.message}",
                                retryable=e.status_code >= 500, status=e.status_code) from e
        except anthropic.APIConnectionError as e:
            raise ProviderError("anthropic connection error", retryable=True) from e
        return self._parse(msg, sw.ms)

    # --- request ------------------------------------------------------------------------------------------

    def _build_kwargs(self, request: ProviderRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens,
            "system": request.system,
            "messages": [_to_anthropic_message(m) for m in request.messages],
        }
        if request.tools:
            # Not `strict: True`: combined with `output_config.format` below, Anthropic rejects the request
            # with "the compiled grammar is too large" -- the two constrained-decoding grammars can't coexist
            # in one call regardless of schema size (confirmed empirically; tools alone or output alone both
            # work at any size tried). `execute_tool` (app/agents/tools.py) already validates tool arguments
            # defensively (ValidationError/ValueError/KeyError/TypeError -> an error ToolResult, never a crash),
            # so losing the strict guarantee on tool arguments costs nothing here.
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.input_schema}
                for t in request.tools
            ]
        output_config: dict[str, Any] = {}
        if request.output_schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": request.output_schema}
        if self.effort:
            output_config["effort"] = self.effort
        if output_config:
            kwargs["output_config"] = output_config
        return kwargs

    # --- response -----------------------------------------------------------------------------------------

    def _parse(self, msg: Any, latency_ms: int) -> ProviderResponse:
        usage = getattr(msg, "usage", None)
        common = dict(provider="anthropic", model=getattr(msg, "model", self.model), latency_ms=latency_ms,
                      tokens_in=getattr(usage, "input_tokens", None), tokens_out=getattr(usage, "output_tokens", None),
                      stop_reason=msg.stop_reason, request_id=getattr(msg, "_request_id", None))
        text = "".join(b.text for b in msg.content if b.type == "text")
        calls = tuple(ToolCall(call_id=b.id, name=b.name, arguments=dict(b.input))
                      for b in msg.content if b.type == "tool_use")

        if msg.stop_reason == "refusal":
            return ProviderResponse(kind="refusal", output_text=text, **common)
        if msg.stop_reason == "max_tokens":
            return ProviderResponse(kind="truncated", output_text=text, **common)
        if msg.stop_reason == "tool_use" or calls:
            return ProviderResponse(kind="tool_calls", tool_calls=calls, output_text=text, **common)
        try:
            output_json = json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            output_json = None
        if not isinstance(output_json, dict):
            # Structured output guarantees JSON when requested; anything else is malformed for the repair path.
            return ProviderResponse(kind="truncated", output_text=text, **common)
        return ProviderResponse(kind="output", output_json=output_json, output_text=text, **common)


def _to_anthropic_message(item: MessageItem) -> dict[str, Any]:
    if isinstance(item, UserText):
        return {"role": "user", "content": item.text}
    if isinstance(item, AssistantToolCalls):
        content: list[dict[str, Any]] = []
        if item.text:
            content.append({"type": "text", "text": item.text})
        content.extend({"type": "tool_use", "id": c.call_id, "name": c.name, "input": c.arguments} for c in item.calls)
        return {"role": "assistant", "content": content}
    if isinstance(item, ToolResults):
        return {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
            for r in item.results]}
    raise TypeError(f"unsupported message item {type(item).__name__}")
