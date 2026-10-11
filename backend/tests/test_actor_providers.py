"""Live provider adapters, offline: request shapes and response mapping with injected fake SDK clients (PRD §3.5).

No network. These pin the strict-schema request shapes confirmed in Appendix B and the response-kind mapping of
§10.1 (refusal/truncation are malformed output, never acceptance). The real round trip is `app.agents.smoke`.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace as NS
from typing import Any

import pytest

# The SDKs are WS-C dependencies (backend/pyproject.toml). Until they are added, this module skips instead of
# breaking collection for the whole suite; run with `uv run --with anthropic --with openai` to exercise it.
pytest.importorskip("anthropic", reason="anthropic SDK not installed (add to backend/pyproject.toml)")
pytest.importorskip("openai", reason="openai SDK not installed (add to backend/pyproject.toml)")
pytest.importorskip("google.genai", reason="google-genai SDK not installed (add to backend/pyproject.toml)")

from app.agents.provider import (  # noqa: E402
    AssistantToolCalls,
    ProviderRequest,
    ToolCall,
    ToolResult,
    ToolResults,
    UserText,
)
from app.agents.provider_anthropic import AnthropicProvider
from app.agents.provider_gemini import SUBMIT_TURN_TOOL, GeminiProvider
from app.agents.provider_openai import OpenAIProvider
from app.agents.schema import turn_output_schema
from app.agents.tools import tool_specs

TURN_JSON = json.dumps({"messages": [], "target_revision": {"metric": "", "old_aspiration": 0,
                                                             "new_aspiration": 0, "reason": ""}})


class FakeSDK:
    """Records kwargs of the last create() call and returns a preset response. Works for both SDK shapes."""

    def __init__(self, response: Any):
        self.response, self.kwargs, self.timeout = response, None, None
        self.messages = self.responses = self

    def with_options(self, timeout: float):
        self.timeout = timeout
        return self

    async def create(self, **kwargs: Any):
        self.kwargs = kwargs
        return self.response


def request(**overrides: Any) -> ProviderRequest:
    base = dict(system="SYS", messages=(UserText("hello"),), tools=tool_specs(), output_schema=turn_output_schema(),
                max_output_tokens=1234, timeout_s=8.0, agent_id="LOG")
    base.update(overrides)
    return ProviderRequest(**base)


CONVERSATION = (
    UserText("u1"),
    AssistantToolCalls(calls=(ToolCall("c1", "find_routes", {"resource_id": "B1", "origin": "BASE", "destination": "PR"}),)),
    ToolResults(results=(ToolResult("c1", '{"routes": []}'),)),
)


# --- Anthropic ----------------------------------------------------------------------------------------------

def anthropic_msg(content: list[Any], stop_reason: str) -> NS:
    return NS(content=content, stop_reason=stop_reason, model="m", usage=NS(input_tokens=10, output_tokens=5),
              _request_id="req_1")


def test_anthropic_request_shape():
    sdk = FakeSDK(anthropic_msg([NS(type="text", text=TURN_JSON)], "end_turn"))
    resp = asyncio.run(AnthropicProvider("fast-tier", client=sdk).complete(request(messages=CONVERSATION)))
    k = sdk.kwargs
    assert k["model"] == "fast-tier" and k["system"] == "SYS" and k["max_tokens"] == 1234 and sdk.timeout == 8.0
    assert k["output_config"]["format"] == {"type": "json_schema", "schema": turn_output_schema()}
    assert "effort" not in k["output_config"] and "thinking" not in k
    # Not strict: True -- combined with output_config.format, Anthropic rejects the request as a too-large
    # compiled grammar (confirmed against the live API). execute_tool validates tool args defensively instead.
    assert all("strict" not in t and t["input_schema"]["additionalProperties"] is False for t in k["tools"])
    assert [t["name"] for t in k["tools"]] == ["find_routes", "validate_plan", "evaluate_plan", "get_negotiation_history"]
    assert k["messages"][0] == {"role": "user", "content": "u1"}
    assert k["messages"][1]["role"] == "assistant" and k["messages"][1]["content"][0]["type"] == "tool_use"
    assert k["messages"][2]["content"][0] == {"type": "tool_result", "tool_use_id": "c1", "content": '{"routes": []}',
                                              "is_error": False}
    assert resp.kind == "output" and resp.output_json["messages"] == [] and resp.tokens_in == 10
    assert resp.request_id == "req_1" and resp.provider == "anthropic"


def test_anthropic_effort_only_when_configured():
    sdk = FakeSDK(anthropic_msg([NS(type="text", text=TURN_JSON)], "end_turn"))
    asyncio.run(AnthropicProvider("m", effort="low", client=sdk).complete(request()))
    assert sdk.kwargs["output_config"]["effort"] == "low"


def test_anthropic_response_kinds():
    tool_use = anthropic_msg([NS(type="tool_use", id="t1", name="find_routes", input={"origin": "BASE"})], "tool_use")
    r = asyncio.run(AnthropicProvider("m", client=FakeSDK(tool_use)).complete(request()))
    assert r.kind == "tool_calls" and r.tool_calls[0] == ToolCall("t1", "find_routes", {"origin": "BASE"})

    r = asyncio.run(AnthropicProvider("m", client=FakeSDK(anthropic_msg([], "refusal"))).complete(request()))
    assert r.kind == "refusal" and r.output_json is None

    r = asyncio.run(AnthropicProvider("m", client=FakeSDK(anthropic_msg([NS(type="text", text='{"mess')], "max_tokens"))).complete(request()))
    assert r.kind == "truncated"

    r = asyncio.run(AnthropicProvider("m", client=FakeSDK(anthropic_msg([NS(type="text", text="not json")], "end_turn"))).complete(request()))
    assert r.kind == "truncated" and r.output_text == "not json"


# --- OpenAI -------------------------------------------------------------------------------------------------

def openai_resp(output: list[Any], status: str = "completed", reason: str | None = None) -> NS:
    return NS(output=output, status=status, incomplete_details=NS(reason=reason) if reason else None, model="m",
              usage=NS(input_tokens=11, output_tokens=6), _request_id="req_2")


def test_openai_request_shape():
    sdk = FakeSDK(openai_resp([NS(type="message", content=[NS(type="output_text", text=TURN_JSON)])]))
    resp = asyncio.run(OpenAIProvider("fast-tier", client=sdk).complete(request(messages=CONVERSATION)))
    k = sdk.kwargs
    assert k["model"] == "fast-tier" and k["instructions"] == "SYS" and k["max_output_tokens"] == 1234
    assert k["text"]["format"]["type"] == "json_schema" and k["text"]["format"]["strict"] is True
    assert k["text"]["format"]["schema"] == turn_output_schema() and "reasoning" not in k
    assert all(t["type"] == "function" and t["strict"] is True for t in k["tools"])
    assert k["input"][0] == {"role": "user", "content": "u1"}
    assert k["input"][1]["type"] == "function_call" and json.loads(k["input"][1]["arguments"])["origin"] == "BASE"
    assert k["input"][2] == {"type": "function_call_output", "call_id": "c1", "output": '{"routes": []}'}
    assert resp.kind == "output" and resp.tokens_out == 6 and resp.provider == "openai"


def test_openai_response_kinds():
    fc = openai_resp([NS(type="reasoning"), NS(type="function_call", call_id="c9", name="validate_plan",
                                                arguments='{"plan": []}')])
    r = asyncio.run(OpenAIProvider("m", client=FakeSDK(fc)).complete(request()))
    assert r.kind == "tool_calls" and r.tool_calls[0] == ToolCall("c9", "validate_plan", {"plan": []})

    refusal = openai_resp([NS(type="message", content=[NS(type="refusal", refusal="no")])])
    assert asyncio.run(OpenAIProvider("m", client=FakeSDK(refusal)).complete(request())).kind == "refusal"

    cut = openai_resp([NS(type="message", content=[NS(type="output_text", text='{"mess')])],
                      status="incomplete", reason="max_output_tokens")
    r = asyncio.run(OpenAIProvider("m", client=FakeSDK(cut)).complete(request()))
    assert r.kind == "truncated" and r.stop_reason == "max_output_tokens"


def test_openai_effort_only_when_configured():
    sdk = FakeSDK(openai_resp([NS(type="message", content=[NS(type="output_text", text=TURN_JSON)])]))
    asyncio.run(OpenAIProvider("m", effort="low", client=sdk).complete(request()))
    assert sdk.kwargs["reasoning"] == {"effort": "low"}


# --- Gemini ---------------------------------------------------------------------------------------------------

class FakeGeminiSDK:
    """Records kwargs of the last generate_content() call and returns a preset response."""

    def __init__(self, response: Any):
        self.response, self.kwargs = response, None
        self.aio = NS(models=self)

    async def generate_content(self, **kwargs: Any):
        self.kwargs = kwargs
        return self.response


def gemini_part(*, text: str | None = None, function_call: Any = None) -> NS:
    return NS(text=text, function_call=function_call)


def gemini_resp(parts: list[Any], finish_reason: str = "STOP") -> NS:
    return NS(candidates=[NS(finish_reason=finish_reason, content=NS(parts=parts))],
              usage_metadata=NS(prompt_token_count=10, candidates_token_count=5), model_version="m")


def test_gemini_request_shape():
    sdk = FakeGeminiSDK(gemini_resp([gemini_part(function_call=NS(id=None, name=SUBMIT_TURN_TOOL,
                                                                   args=json.loads(TURN_JSON)))]))
    resp = asyncio.run(GeminiProvider("fast-tier", client=sdk).complete(request(messages=CONVERSATION)))
    k = sdk.kwargs
    assert k["model"] == "fast-tier"
    config = k["config"]
    assert config.system_instruction == "SYS" and config.max_output_tokens == 1234
    declarations = config.tools[0].function_declarations
    names = [d.name for d in declarations]
    assert names == ["find_routes", "validate_plan", "evaluate_plan", "get_negotiation_history", SUBMIT_TURN_TOOL]
    submit = next(d for d in declarations if d.name == SUBMIT_TURN_TOOL)
    assert submit.parameters_json_schema == turn_output_schema()
    assert all(d.parameters_json_schema["additionalProperties"] is False for d in declarations[:-1])
    # The submitted turn comes back as output, not a tool call -- invisible to the actor beyond `kind`.
    assert resp.kind == "output" and resp.output_json["messages"] == []
    assert resp.tokens_in == 10 and resp.tokens_out == 5 and resp.provider == "gemini"
    # The replayed assistant tool-call and the tool-result round trip without erroring (contents built OK).
    assert len(k["contents"]) == 3


def test_gemini_tool_call_vs_submit():
    route_call = NS(id=None, name="find_routes", args={"origin": "BASE"})
    sdk = FakeGeminiSDK(gemini_resp([gemini_part(function_call=route_call)]))
    r = asyncio.run(GeminiProvider("m", client=sdk).complete(request()))
    assert r.kind == "tool_calls" and r.tool_calls[0].name == "find_routes" and r.tool_calls[0].arguments == {"origin": "BASE"}
    assert r.tool_calls[0].call_id == "find_routes#0"   # Gemini has no call id of its own; name#index stands in


def test_gemini_response_kinds():
    r = asyncio.run(GeminiProvider("m", client=FakeGeminiSDK(gemini_resp([], "SAFETY"))).complete(request()))
    assert r.kind == "refusal"

    r = asyncio.run(GeminiProvider("m", client=FakeGeminiSDK(
        gemini_resp([gemini_part(text='{"mess')], "MAX_TOKENS"))).complete(request()))
    assert r.kind == "truncated"

    # Plain text, no tool call: always malformed here -- there is no response_schema guarantee on this path.
    r = asyncio.run(GeminiProvider("m", client=FakeGeminiSDK(
        gemini_resp([gemini_part(text="not json")], "STOP"))).complete(request()))
    assert r.kind == "truncated" and r.output_text == "not json"


def test_gemini_no_output_schema_omits_submit_tool():
    sdk = FakeGeminiSDK(gemini_resp([gemini_part(text="ok")], "STOP"))
    asyncio.run(GeminiProvider("m", client=sdk).complete(request(output_schema=None)))
    names = [d.name for d in sdk.kwargs["config"].tools[0].function_declarations]
    assert SUBMIT_TURN_TOOL not in names


def test_tool_specs_are_strict_compatible():
    for spec in tool_specs():
        schema = spec.input_schema
        assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
        assert "anyOf" not in json.dumps(schema) and "null" not in json.dumps(schema)
