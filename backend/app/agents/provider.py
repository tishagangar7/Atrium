"""Provider-neutral model access for the three actors and the single-agent baseline (PRD §3.4, §3.5, D-03).

One interface, four implementations: `provider_anthropic.py`, `provider_openai.py`, `provider_gemini.py`
(free-tier option) and the labeled `provider_fake.py` (protocol tests only). Switching provider or model is
a config change in `backend/.env`:

    RESCUEMESH_PROVIDER=anthropic|openai|gemini|fake
    RESCUEMESH_MODEL=<provider model id>        # never hard-coded in app code (AGENTS.md §5)
    RESCUEMESH_EFFORT=low|medium|high           # optional; omitted -> provider default
    RESCUEMESH_TEST=1                           # required for the fake provider (§11.5)

Request/response shapes carry only what the actor loop (§6.3) needs: a system prompt, a conversation that may
include tool calls and results, strict tool specs, a structured-output schema, and a per-call deadline.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

ProviderName = Literal["anthropic", "openai", "gemini", "fake"]
ResponseKind = Literal["output", "tool_calls", "refusal", "truncated"]
CallPurpose = Literal["decision", "tool_iteration", "repair", "smoke"]

DEFAULT_TURN_DEADLINE_S = 8.0  # §6.4 turn deadline
DEFAULT_MAX_OUTPUT_TOKENS = 4096


class ProviderError(Exception):
    """A provider call failed. `retryable` follows §10.1: timeout, 429 and 5xx get one retry inside the deadline."""

    def __init__(self, message: str, *, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass(frozen=True)
class ToolSpec:
    """A model-callable tool. `input_schema` must be strict-compatible (additionalProperties false, all required)."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]
    # Gemini-only (provider_gemini.py): opaque per-call state the model needs echoed back verbatim on the
    # next turn for correct multi-turn function calling. None for every other provider.
    thought_signature: bytes | None = None


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    content: str          # JSON text; §10.3: data, never instructions
    is_error: bool = False


@dataclass(frozen=True)
class UserText:
    text: str


@dataclass(frozen=True)
class AssistantToolCalls:
    calls: tuple[ToolCall, ...]
    text: str = ""        # any text the model emitted alongside the calls (kept for faithful replay)


@dataclass(frozen=True)
class ToolResults:
    results: tuple[ToolResult, ...]


MessageItem = UserText | AssistantToolCalls | ToolResults


@dataclass(frozen=True)
class ProviderRequest:
    system: str
    messages: tuple[MessageItem, ...]
    tools: tuple[ToolSpec, ...] = ()
    output_schema: dict[str, Any] | None = None
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout_s: float = DEFAULT_TURN_DEADLINE_S
    purpose: CallPurpose = "decision"
    agent_id: str | None = None   # for the ledger only; never sent to the model as an argument (§4.4)


@dataclass(frozen=True)
class ProviderResponse:
    kind: ResponseKind
    provider: ProviderName
    model: str
    latency_ms: int
    output_json: dict[str, Any] | None = None     # kind == "output": parsed structured output (sentinel form)
    output_text: str = ""                          # raw text block, for prompt capture (§10.5)
    tool_calls: tuple[ToolCall, ...] = ()          # kind == "tool_calls"
    tokens_in: int | None = None
    tokens_out: int | None = None
    stop_reason: str | None = None
    request_id: str | None = None


@dataclass
class CallLedgerRow:
    """One row of runs/<run_id>/calls.jsonl (§10.5). B2 writes these; B1 fixes the shape."""

    provider: ProviderName
    model: str
    agent: str | None
    purpose: CallPurpose
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: int
    status: Literal["ok", "error", "timeout", "cancelled"]
    cancelled: bool = False
    request_id: str | None = None
    error: str | None = None

    @classmethod
    def from_response(cls, req: ProviderRequest, resp: ProviderResponse) -> "CallLedgerRow":
        return cls(provider=resp.provider, model=resp.model, agent=req.agent_id, purpose=req.purpose,
                   tokens_in=resp.tokens_in, tokens_out=resp.tokens_out, latency_ms=resp.latency_ms,
                   status="ok", request_id=resp.request_id)


@runtime_checkable
class Provider(Protocol):
    name: ProviderName
    model: str
    label: str   # shown in the UI header when it is not a live provider (TEST PROVIDER)

    async def complete(self, request: ProviderRequest) -> ProviderResponse: ...


# --- configuration ------------------------------------------------------------------------------------------

def backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def load_backend_env(path: Path | None = None) -> dict[str, str]:
    """Load KEY=VALUE lines from backend/.env into os.environ without overriding existing variables.

    Keys live only in that git-ignored file (invariant 10). No python-dotenv dependency: the format we need is
    one assignment per line, `#` comments, optional surrounding quotes.
    """
    path = path or backend_dir() / ".env"
    loaded: dict[str, str] = {}
    if not path.is_file():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


@dataclass(frozen=True)
class Settings:
    provider: ProviderName
    model: str
    test_mode: bool
    effort: str | None = None
    turn_deadline_s: float = DEFAULT_TURN_DEADLINE_S

    @classmethod
    def from_env(cls) -> "Settings":
        load_backend_env()
        # `MODEL_PROVIDER` is the name backend/.env.example (WS-C) uses; accepted as an alias.
        provider = (os.environ.get("RESCUEMESH_PROVIDER") or os.environ.get("MODEL_PROVIDER") or "").strip().lower()
        if provider not in ("anthropic", "openai", "gemini", "fake"):
            raise ProviderError(
                f"RESCUEMESH_PROVIDER must be anthropic|openai|gemini|fake, got {provider!r} "
                "(set it in backend/.env)", retryable=False)
        model = os.environ.get("RESCUEMESH_MODEL", "").strip()
        if provider != "fake" and not model:
            raise ProviderError("RESCUEMESH_MODEL is required for live providers (backend/.env)", retryable=False)
        return cls(
            provider=provider,  # type: ignore[arg-type]
            model=model or "test-provider",
            test_mode=os.environ.get("RESCUEMESH_TEST") == "1",
            effort=os.environ.get("RESCUEMESH_EFFORT", "").strip() or None,
            turn_deadline_s=float(os.environ.get("RESCUEMESH_TURN_DEADLINE_S", DEFAULT_TURN_DEADLINE_S)),
        )


def get_provider(settings: Settings, **fake_kwargs: Any) -> Provider:
    """Build the configured provider. The fake provider is refused outside test mode (§11.5, AC-026)."""
    if settings.provider == "fake":
        if not settings.test_mode:
            raise ProviderError("TEST PROVIDER requested without RESCUEMESH_TEST=1 — refusing (PRD §11.5)",
                                retryable=False)
        from app.agents.provider_fake import FakeProvider
        return FakeProvider(**fake_kwargs)
    if settings.provider == "anthropic":
        from app.agents.provider_anthropic import AnthropicProvider
        return AnthropicProvider(model=settings.model, effort=settings.effort)
    if settings.provider == "gemini":
        from app.agents.provider_gemini import GeminiProvider
        return GeminiProvider(model=settings.model, effort=settings.effort)
    from app.agents.provider_openai import OpenAIProvider
    return OpenAIProvider(model=settings.model, effort=settings.effort)


class Stopwatch:
    def __enter__(self) -> "Stopwatch":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        self.ms = int((time.perf_counter() - self._t0) * 1000)
