"""Labeled TEST PROVIDER guard and scripting; provider settings (PRD §11.5, AC-026, AC-029)."""

from __future__ import annotations

import asyncio

import pytest

from app.agents.provider import (
    ProviderError,
    ProviderRequest,
    Settings,
    ToolCall,
    UserText,
    get_provider,
    load_backend_env,
)
from app.agents.schema import parse_turn

ACCEPT_TURN = {
    "messages": [{
        "message_type": "ACCEPT", "recipients": [], "plan": [], "parent_plan_id": "", "target_plan_id": "",
        "target_plan_hash": "9f03c2d4e1aa",
        "objection": {"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""},
        "evidence_ids": [], "caused_by": [], "requested_evidence_id": "", "requested_topic": "",
        "shared_evidence_ids": [], "reason": "", "blocking": [], "rationale": "Meets my floor.",
    }],
    "target_revision": {"metric": "", "old_aspiration": 0, "new_aspiration": 0, "reason": ""},
}


def _req(agent: str) -> ProviderRequest:
    return ProviderRequest(system="s", messages=(UserText("u"),), agent_id=agent)


def test_fake_provider_refused_without_test_flag(monkeypatch):
    """Invariant 8 / AC-026: the scripted provider can never be constructed in live mode."""
    monkeypatch.delenv("RESCUEMESH_TEST", raising=False)
    from app.agents.provider_fake import FakeProvider
    with pytest.raises(ProviderError):
        FakeProvider()


def test_factory_refuses_fake_without_test_mode():
    with pytest.raises(ProviderError):
        get_provider(Settings(provider="fake", model="x", test_mode=False))


def test_fake_provider_is_labeled_and_scripted(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_TEST", "1")
    provider = get_provider(Settings(provider="fake", model="test-provider", test_mode=True),
                            script={("EVAC", 3): ACCEPT_TURN})
    assert provider.label == "TEST PROVIDER" and provider.name == "fake"

    provider.set_round("EVAC", 3)
    resp = asyncio.run(provider.complete(_req("EVAC")))
    assert resp.kind == "output" and resp.provider == "fake"
    turn = parse_turn(resp.output_json, agent_id="EVAC", dp_id="dp-1")
    assert turn.messages[0].message_type == "ACCEPT"
    assert turn.messages[0].target_plan_hash == "9f03c2d4e1aa"
    assert len(provider.requests) == 1


def test_unscripted_turn_is_silence(monkeypatch):
    """AC-029: silence is a real output that carries no acceptance, not a fabricated message."""
    monkeypatch.setenv("RESCUEMESH_TEST", "1")
    from app.agents.provider_fake import FakeProvider
    resp = asyncio.run(FakeProvider().complete(_req("FIRE")))
    turn = parse_turn(resp.output_json, agent_id="FIRE", dp_id="dp-1")
    assert turn.messages == [] and turn.target_revision is None


def test_scripted_tool_calls_then_output(monkeypatch):
    """§6.3: the fake can drive the CALLING_MODEL ⇄ RUNNING_TOOL loop deterministically."""
    monkeypatch.setenv("RESCUEMESH_TEST", "1")
    from app.agents.provider_fake import FakeProvider, ScriptedTurn
    call = ToolCall(call_id="c1", name="find_routes", arguments={"origin": "BASE", "destination": "PR"})
    provider = FakeProvider({("LOG", 1): ScriptedTurn(output=ACCEPT_TURN, tool_calls=[[call]])})
    first = asyncio.run(provider.complete(_req("LOG")))
    second = asyncio.run(provider.complete(_req("LOG")))
    assert first.kind == "tool_calls" and first.tool_calls == (call,)
    assert second.kind == "output"


def test_scripted_failure_kinds(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_TEST", "1")
    from app.agents.provider_fake import FakeProvider, ScriptedTurn
    provider = FakeProvider({
        ("LOG", 1): ScriptedTurn(output={}, kind_override="refusal"),
        ("EVAC", 1): ScriptedTurn(output={}, raise_error=ProviderError("boom", retryable=True, status=503)),
    })
    assert asyncio.run(provider.complete(_req("LOG"))).kind == "refusal"
    with pytest.raises(ProviderError) as ei:
        asyncio.run(provider.complete(_req("EVAC")))
    assert ei.value.retryable and ei.value.status == 503


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_PROVIDER", "anthropic")
    monkeypatch.setenv("RESCUEMESH_MODEL", "some-fast-tier")
    monkeypatch.delenv("RESCUEMESH_TEST", raising=False)
    s = Settings.from_env()
    assert s.provider == "anthropic" and s.model == "some-fast-tier" and not s.test_mode and s.effort is None

    monkeypatch.setenv("RESCUEMESH_PROVIDER", "openai")
    monkeypatch.delenv("RESCUEMESH_MODEL", raising=False)
    with pytest.raises(ProviderError):
        Settings.from_env()


def test_load_backend_env_does_not_override(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    # Not a key pattern on purpose: scripts/check.sh scans tracked files for sk-… strings (NFR-006).
    env.write_text('RESCUEMESH_PROVIDER="anthropic"\n# comment\nRESCUEMESH_MODEL=m1\n')
    monkeypatch.setenv("RESCUEMESH_MODEL", "already")
    monkeypatch.delenv("RESCUEMESH_PROVIDER", raising=False)
    loaded = load_backend_env(env)
    assert loaded == {"RESCUEMESH_PROVIDER": "anthropic"}
    import os
    assert os.environ["RESCUEMESH_MODEL"] == "already"
