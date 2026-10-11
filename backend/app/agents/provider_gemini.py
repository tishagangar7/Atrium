"""Google Gemini adapter (PRD §3.4 "Model access", §3.5, Appendix B).

Free-tier option alongside `provider_anthropic.py` / `provider_openai.py`. Gemini's standard (non-preview)
models reject a request that combines custom function-calling `tools` with `response_schema` structured
output -- confirmed against the documented API behavior, the same category of conflict `provider_anthropic.py`
hit and fixed (not identical mechanism: Gemini rejects the combination outright rather than compiling an
oversized grammar, but the practical effect -- can't use both in one call -- is the same).

So this adapter never sends `response_schema`. Instead, the structured `AgentTurn` output becomes one more
function the model can call: `SUBMIT_TURN_TOOL`, whose arguments are `request.output_schema`. The model picks
among the real tools (find_routes, validate_plan, ...) and `submit_turn` in the same multi-tool function-calling
call, exactly like it already picks among real tools versus ending its turn with Anthropic/OpenAI's structured
output -- the difference is invisible to `actor.py`, which only sees `ProviderResponse.kind`.

Untested against a live key as of writing (no model-specific surprise can be fully ruled out until it runs
against the real API, the same lesson from the Anthropic fix). Offline tests pin the request/response shaping.
"""

from __future__ import annotations

from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

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

SUBMIT_TURN_TOOL = "submit_turn"
MIN_TIMEOUT_S = 10.0  # Gemini rejects a request-level deadline below this (confirmed against the live API);
                      # the actor's own turn_deadline_s round-level accounting is unaffected by this floor.


class GeminiProvider:
    name = "gemini"
    label = "LIVE"

    def __init__(self, model: str, *, effort: str | None = None, client: Any | None = None):
        self.model = model
        self.effort = effort  # Gemini's thinking budget is a token count, not low/medium/high; not wired yet.
        # Credentials resolve from the environment (GEMINI_API_KEY loaded from backend/.env).
        self._client = client or genai.Client()

    async def complete(self, request: ProviderRequest) -> ProviderResponse:
        contents, config = self._build_request(request)
        try:
            with Stopwatch() as sw:
                resp = await self._client.aio.models.generate_content(
                    model=self.model, contents=contents,
                    config=genai_types.GenerateContentConfig(**config, http_options=genai_types.HttpOptions(
                        timeout=int(max(request.timeout_s, MIN_TIMEOUT_S) * 1000))),
                )
        except genai_errors.ClientError as e:
            raise ProviderError(f"gemini HTTP {e.code}: {e.message}",
                                retryable=e.code == 429, status=e.code) from e
        except genai_errors.ServerError as e:
            raise ProviderError(f"gemini HTTP {e.code}: {e.message}", retryable=True, status=e.code) from e
        except genai_errors.APIError as e:
            raise ProviderError(f"gemini error: {e.message}", retryable=False, status=getattr(e, "code", None)) from e
        return self._parse(resp, sw.ms)

    # --- request ------------------------------------------------------------------------------------------

    def _build_request(self, request: ProviderRequest) -> tuple[list[Any], dict[str, Any]]:
        declarations = [genai_types.FunctionDeclaration(name=t.name, description=t.description,
                                                        parameters_json_schema=t.input_schema)
                        for t in request.tools]
        if request.output_schema is not None:
            declarations.append(genai_types.FunctionDeclaration(
                name=SUBMIT_TURN_TOOL,
                description="Submit your turn for this round: the structured AgentTurn JSON (messages, "
                            "target_revision). Call this instead of a reconnaissance tool when you are done.",
                parameters_json_schema=request.output_schema,
            ))
        config: dict[str, Any] = {
            "system_instruction": request.system,
            "max_output_tokens": request.max_output_tokens,
        }
        if declarations:
            config["tools"] = [genai_types.Tool(function_declarations=declarations)]
        contents = [part for m in request.messages for part in _to_gemini_contents(m)]
        return contents, config

    # --- response -----------------------------------------------------------------------------------------

    def _parse(self, resp: Any, latency_ms: int) -> ProviderResponse:
        candidate = resp.candidates[0] if resp.candidates else None
        finish_reason = str(getattr(candidate, "finish_reason", "") or "")
        usage = getattr(resp, "usage_metadata", None)
        common = dict(provider="gemini", model=getattr(resp, "model_version", None) or self.model,
                      latency_ms=latency_ms,
                      tokens_in=getattr(usage, "prompt_token_count", None),
                      tokens_out=getattr(usage, "candidates_token_count", None),
                      stop_reason=finish_reason or None, request_id=None)

        if "SAFETY" in finish_reason or "RECITATION" in finish_reason or "PROHIBITED" in finish_reason:
            return ProviderResponse(kind="refusal", **common)

        parts = list(getattr(candidate.content, "parts", []) or []) if candidate and candidate.content else []
        text = "".join(p.text for p in parts if getattr(p, "text", None))
        # Keep each function_call paired with its own part's thought_signature -- Gemini requires that
        # signature echoed back verbatim on the next turn (confirmed against the live API: a missing
        # signature is a 400, not a soft degradation) -- it is not carried on FunctionCall itself.
        call_parts = [(p.function_call, getattr(p, "thought_signature", None))
                      for p in parts if getattr(p, "function_call", None)]

        submit = next((fc for fc, _ in call_parts if fc.name == SUBMIT_TURN_TOOL), None)
        if submit is not None:
            return ProviderResponse(kind="output", output_json=dict(submit.args), output_text=text, **common)

        if call_parts:
            # fc.id exists but function_response matching is by name, not by it (confirmed against the
            # live API), so call_id always encodes "<name>#<index>" -- real id isn't useful here and a
            # repeated tool in one turn still needs a unique, decodable id either way.
            calls = tuple(ToolCall(call_id=f"{fc.name}#{i}", name=fc.name, arguments=dict(fc.args),
                                   thought_signature=sig)
                          for i, (fc, sig) in enumerate(call_parts))
            return ProviderResponse(kind="tool_calls", tool_calls=calls, output_text=text, **common)

        if "MAX_TOKENS" in finish_reason:
            return ProviderResponse(kind="truncated", output_text=text, **common)
        # STOP (or anything else) with no tool call at all: the model neither reconnoitered nor submitted.
        # Never guessed as valid structured output -- there is no response_schema guarantee here, unlike
        # the Anthropic/OpenAI adapters, so free text is always malformed for the repair path.
        return ProviderResponse(kind="truncated", output_text=text, **common)


def _to_gemini_contents(item: MessageItem) -> list[genai_types.Content]:
    if isinstance(item, UserText):
        return [genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=item.text)])]
    if isinstance(item, AssistantToolCalls):
        parts = []
        if item.text:
            parts.append(genai_types.Part.from_text(text=item.text))
        # thought_signature must be echoed back verbatim or Gemini 400s on the next turn (confirmed live);
        # Part.from_function_call doesn't accept it, so these are built directly instead.
        parts.extend(genai_types.Part(function_call=genai_types.FunctionCall(name=c.name, args=c.arguments),
                                      thought_signature=c.thought_signature)
                    for c in item.calls)
        return [genai_types.Content(role="model", parts=parts)]
    if isinstance(item, ToolResults):
        return [genai_types.Content(role="user", parts=[
            genai_types.Part.from_function_response(
                name=r.call_id.rsplit("#", 1)[0],
                response={"error": r.content} if r.is_error else {"result": r.content})
            for r in item.results])]
    raise TypeError(f"unsupported message item {type(item).__name__}")
