"""OpenAI Responses API adapter (PRD §3.4 "Model access", §3.5, Appendix B, D-03).

Structured output via `text.format` (`json_schema`, `strict: true`), strict function tools. Same contract as
`provider_anthropic.py`, so the runtime switches providers by changing `RESCUEMESH_PROVIDER` only. `reasoning.effort`
is sent only when `RESCUEMESH_EFFORT` is set (not every tier accepts it).
"""

from __future__ import annotations

import json
from typing import Any

import openai

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

OUTPUT_SCHEMA_NAME = "agent_turn"


class OpenAIProvider:
    name = "openai"
    label = "LIVE"

    def __init__(self, model: str, *, effort: str | None = None, client: Any | None = None):
        self.model = model
        self.effort = effort
        # Credentials resolve from the environment (OPENAI_API_KEY loaded from backend/.env).
        self._client = client or openai.AsyncOpenAI(max_retries=1)

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        kwargs = self._build_kwargs(request)
        try:
            with Stopwatch() as sw:
                resp = await self._client.with_options(timeout=request.timeout_s).responses.create(**kwargs)
        except openai.APITimeoutError as e:
            raise ProviderError(f"openai timeout after {request.timeout_s}s", retryable=True) from e
        except openai.RateLimitError as e:
            raise ProviderError("openai rate limited", retryable=True, status=429) from e
        except openai.APIStatusError as e:
            raise ProviderError(f"openai HTTP {e.status_code}: {e.message}",
                                retryable=e.status_code >= 500, status=e.status_code) from e
        except openai.APIConnectionError as e:
            raise ProviderError("openai connection error", retryable=True) from e
        return self._parse(resp, sw.ms)

    # --- request ------------------------------------------------------------------------------------------

    def _build_kwargs(self, request: ProviderRequest) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "instructions": request.system,
            "input": [item for m in request.messages for item in _to_openai_items(m)],
            "max_output_tokens": request.max_output_tokens,
        }
        if request.tools:
            kwargs["tools"] = [
                {"type": "function", "name": t.name, "description": t.description,
                 "parameters": t.input_schema, "strict": True}
                for t in request.tools
            ]
        if request.output_schema is not None:
            kwargs["text"] = {"format": {"type": "json_schema", "name": OUTPUT_SCHEMA_NAME,
                                         "schema": request.output_schema, "strict": True}}
        if self.effort:
            kwargs["reasoning"] = {"effort": self.effort}
        return kwargs

    # --- response -----------------------------------------------------------------------------------------

    def _parse(self, resp: Any, latency_ms: int) -> ProviderResponse:
        usage = getattr(resp, "usage", None)
        incomplete = getattr(resp, "incomplete_details", None)
        stop_reason = getattr(incomplete, "reason", None) or getattr(resp, "status", None)
        common = dict(provider="openai", model=getattr(resp, "model", self.model), latency_ms=latency_ms,
                      tokens_in=getattr(usage, "input_tokens", None), tokens_out=getattr(usage, "output_tokens", None),
                      stop_reason=stop_reason, request_id=getattr(resp, "_request_id", None))
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        refused = False
        for item in resp.output:
            if item.type == "function_call":
                try:
                    args = json.loads(item.arguments) if isinstance(item.arguments, str) else dict(item.arguments)
                except json.JSONDecodeError:
                    args = {"_raw": item.arguments}
                calls.append(ToolCall(call_id=item.call_id, name=item.name, arguments=args))
            elif item.type == "message":
                for part in item.content:
                    if part.type == "output_text":
                        text_parts.append(part.text)
                    elif part.type == "refusal":
                        refused = True
                        text_parts.append(part.refusal)
        text = "".join(text_parts)

        if refused:
            return ProviderResponse(kind="refusal", output_text=text, **common)
        if getattr(resp, "status", None) == "incomplete":
            return ProviderResponse(kind="truncated", output_text=text, **common)
        if calls:
            return ProviderResponse(kind="tool_calls", tool_calls=tuple(calls), output_text=text, **common)
        try:
            output_json = json.loads(text) if text.strip() else None
        except json.JSONDecodeError:
            output_json = None
        if not isinstance(output_json, dict):
            return ProviderResponse(kind="truncated", output_text=text, **common)
        return ProviderResponse(kind="output", output_json=output_json, output_text=text, **common)


def _to_openai_items(item: MessageItem) -> list[dict[str, Any]]:
    if isinstance(item, UserText):
        return [{"role": "user", "content": item.text}]
    if isinstance(item, AssistantToolCalls):
        items: list[dict[str, Any]] = []
        if item.text:
            items.append({"role": "assistant", "content": item.text})
        items.extend({"type": "function_call", "call_id": c.call_id, "name": c.name,
                      "arguments": json.dumps(c.arguments, separators=(",", ":"))} for c in item.calls)
        return items
    if isinstance(item, ToolResults):
        return [{"type": "function_call_output", "call_id": r.call_id, "output": r.content} for r in item.results]
    raise TypeError(f"unsupported message item {type(item).__name__}")
