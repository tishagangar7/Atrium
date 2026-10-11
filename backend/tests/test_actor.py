"""Single actor lifecycle with the TEST PROVIDER and the simulator stub (PRD §6.3, §6.4, §10.1; AC-001, AC-024, AC-029).

Every test builds real `Actor` objects over `FakeProvider` + `StubSim`; nothing is mocked inside the actor.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agents.actor import MAX_MODEL_CALLS_PER_TURN, Actor, ActorState, TurnInput
from app.agents.ledger import CallLedger, ToolLedger, redact
from app.agents.prompt import DEFAULT_TARGETS
from app.agents.provider import ProviderError, ToolCall, UserText
from app.agents.provider_fake import SILENT_TURN, Fail, FakeProvider, Refuse, ToolCalls, Truncate
from app.agents.schema import INT_SENTINEL
from app.agents.sim_stub import StubSim

pytestmark = pytest.mark.usefixtures("test_mode")


@pytest.fixture
def test_mode(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_TEST", "1")


NO_OBJECTION = {"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""}
NO_REVISION = {"metric": "", "old_aspiration": 0, "new_aspiration": 0, "reason": ""}
DRIVE = {"resource_id": "B1", "task": "drive", "origin": "BASE", "destination": "VJ", "route_ids": ["R1", "R3"],
         "start_step": 0, "people_count": INT_SENTINEL, "zone_id": "", "shelter_id": "", "crew_id": "",
         "target_cells": [], "edge_id": "", "duration_steps": INT_SENTINEL}


def propose(evidence_ids: list[str] | None = None, rationale: str = "B1 to Valley Junction first.") -> dict:
    return {"messages": [{
        "message_type": "PROPOSE", "recipients": [], "plan": [DRIVE], "parent_plan_id": "", "target_plan_id": "",
        "target_plan_hash": "", "objection": NO_OBJECTION, "evidence_ids": evidence_ids or [], "caused_by": [],
        "requested_evidence_id": "", "requested_topic": "", "shared_evidence_ids": [], "reason": "", "blocking": [],
        "rationale": rationale,
    }], "target_revision": NO_REVISION}


GOOD = propose(["E-LOG-01"])
BAD_RATIONALE = propose(["E-LOG-01"], rationale="x" * 300)
FIND = ToolCalls([ToolCall("t1", "find_routes", {"resource_id": "B1", "origin": "BASE", "destination": "PR"})])
VALIDATE = ToolCalls([ToolCall("t2", "validate_plan", {"plan": [DRIVE]})])


def make_actor(agent: str, script, sim: StubSim | None = None, provider: FakeProvider | None = None, **kw):
    sim = sim or StubSim()
    provider = provider or FakeProvider(script, **kw)
    actor = Actor(ActorState(agent_id=agent, targets=DEFAULT_TARGETS), provider, sim)
    return actor, provider, sim


def turn_input(sim: StubSim, agent: str, round_: int = 1, **kw) -> TurnInput:
    return TurnInput(view=sim.build_belief_view(agent), round=round_, dp_id="dp-1", run_id="run-t", **kw)


def run(actor: Actor, inp: TurnInput):
    return asyncio.run(actor.run_turn(inp))


# --- happy paths --------------------------------------------------------------------------------------------------

def test_scripted_propose_is_submitted():
    actor, provider, sim = make_actor("LOG", {("LOG", 1): GOOD})
    out = run(actor, turn_input(sim, "LOG"))
    assert out.status == "submitted" and out.model_calls == 1 and out.turn is not None
    assert out.turn.messages[0].message_type == "PROPOSE" and out.turn.messages[0].plan[0].resource_id == "B1"
    assert [r.status for r in out.call_rows] == ["ok"] and out.call_rows[0].purpose == "decision"
    assert out.call_rows[0].agent == "LOG" and out.call_rows[0].provider == "fake"
    assert provider.requests[0].agent_id == "LOG" and provider.requests[0].output_schema is not None
    assert actor.state.consecutive_failures == 0 and out.latency_ms >= 0


def test_silence_is_a_distinct_status():
    """AC-029: an empty turn is silence — recorded, never an acceptance."""
    actor, _, sim = make_actor("FIRE", {("FIRE", 1): SILENT_TURN})
    out = run(actor, turn_input(sim, "FIRE"))
    assert out.status == "silent" and out.turn is not None and out.turn.messages == []


def test_tool_loop_runs_on_callers_view():
    """§6.3 CALLING_MODEL ⇄ RUNNING_TOOL, AC-024: EVAC's find_routes sees R2 open; LOG's does not."""
    for agent, sees_r2 in (("EVAC", True), ("LOG", False)):
        script = {(agent, 1): [FIND, VALIDATE, propose()]}
        actor, provider, sim = make_actor(agent, script)
        out = run(actor, turn_input(sim, agent))
        assert out.status == "submitted" and out.model_calls == 3
        assert [r.tool for r in out.tool_rows] == ["find_routes", "validate_plan"]
        assert [r.purpose for r in out.call_rows] == ["decision", "tool_iteration", "tool_iteration"]
        routes = json.loads(out.transcript[2]["content"].split(": ", 1)[1])["routes"]
        assert any("R2" in r["route_ids"] for r in routes) is sees_r2
        # after the second iteration the request carries no tools and the "no more tools" note
        assert provider.requests[1].tools and provider.requests[2].tools == ()
        assert any(isinstance(m, UserText) and "budget" in m.text for m in provider.requests[2].messages)


def test_tool_calls_after_budget_are_malformed_and_capped():
    """§6.4: ≤ 2 tool iterations, ≤ 4 model calls; a model that keeps calling tools ends the turn failed."""
    actor, _, sim = make_actor("LOG", {("LOG", 1): [FIND, FIND, FIND, FIND, FIND]})
    out = run(actor, turn_input(sim, "LOG"))
    assert out.status == "failed" and out.model_calls == MAX_MODEL_CALLS_PER_TURN == 4
    assert len(out.tool_rows) == 2 and any("not allowed" in e for e in out.errors)


# --- repair and failure -------------------------------------------------------------------------------------------

def test_one_repair_fixes_a_semantic_error():
    """§10.1: one repair call carrying the error list; a valid second answer is submitted."""
    actor, provider, sim = make_actor("LOG", {("LOG", 1): [BAD_RATIONALE, GOOD]})
    out = run(actor, turn_input(sim, "LOG"))
    assert out.status == "submitted" and out.model_calls == 2
    assert [r.purpose for r in out.call_rows] == ["decision", "repair"]
    repair_msgs = [m for m in provider.requests[1].messages if isinstance(m, UserText)]
    assert any("rationale" in m.text and "280" in m.text and "ERRORS:" in m.text for m in repair_msgs)


def test_unheld_evidence_is_repaired_or_fails():
    actor, _, sim = make_actor("EVAC", {("EVAC", 1): [propose(["E-LOG-01"]), propose(["E-LOG-01"])]})
    out = run(actor, turn_input(sim, "EVAC"))
    assert out.status == "failed" and any("UNKNOWN_EVIDENCE" in e for e in out.errors) and out.turn is None


def test_two_failed_turns_degrade_the_actor():
    """§6.3 / §6.9 #4 / AC-029: after two consecutive failed turns the actor is DEGRADED and makes no calls."""
    actor, provider, sim = make_actor("LOG", {("LOG", 1): [BAD_RATIONALE]})
    assert run(actor, turn_input(sim, "LOG")).status == "failed"
    assert actor.state.consecutive_failures == 1 and not actor.state.degraded
    provider.reset_progress()
    assert run(actor, turn_input(sim, "LOG")).status == "failed"
    assert actor.state.degraded
    calls_before = len(provider.requests)
    out = run(actor, turn_input(sim, "LOG"))
    assert out.status == "degraded" and out.turn is None and len(provider.requests) == calls_before


def test_refusal_and_truncation_are_malformed_never_fabricated():
    for step in (Refuse(), Truncate()):
        actor, _, sim = make_actor("LOG", {("LOG", 1): [step, step]})
        out = run(actor, turn_input(sim, "LOG"))
        assert out.status == "failed" and out.turn is None and out.model_calls == 2
        assert out.call_rows[0].status == "ok"   # the call itself succeeded; the content was unusable


def test_schema_invalid_json_is_repaired():
    actor, _, sim = make_actor("LOG", {("LOG", 1): [{"messages": [{"message_type": "SHOUT"}], "target_revision": NO_REVISION}, GOOD]})
    out = run(actor, turn_input(sim, "LOG"))
    assert out.status == "submitted" and out.model_calls == 2


# --- deadline, cancellation, provider errors ----------------------------------------------------------------------

def test_turn_deadline_makes_the_actor_late():
    """§6.10 LATE / AC-029: a slow model yields no turn; the in-flight call is recorded as a timeout."""
    actor, _, sim = make_actor("LOG", {("LOG", 1): GOOD}, delay_s=0.3)
    out = run(actor, turn_input(sim, "LOG", deadline_s=0.05))
    assert out.status == "late" and out.turn is None
    assert out.call_rows[-1].status == "timeout" and out.call_rows[-1].cancelled
    assert actor.state.consecutive_failures == 1


def test_cancellation_propagates_and_is_recorded():
    """§4.6 / FR-041: cancelling the turn task records the in-flight call and re-raises."""
    actor, _, sim = make_actor("LOG", {("LOG", 1): GOOD}, delay_s=1.0)

    async def scenario():
        task = asyncio.create_task(actor.run_turn(turn_input(sim, "LOG", deadline_s=5)))
        await asyncio.sleep(0.02)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert actor.last_outcome is not None and actor.last_outcome.status == "cancelled"
    assert actor.last_outcome.call_rows[0].cancelled and actor.last_outcome.call_rows[0].status == "cancelled"
    assert actor.state.consecutive_failures == 0   # cancellation is not a failed turn


def test_retryable_provider_error_is_retried_once():
    """§10.1: one retry inside the deadline on timeout/429/5xx; non-retryable errors fail the turn."""
    actor, _, sim = make_actor("LOG", {("LOG", 1): [Fail(ProviderError("503", retryable=True, status=503)), GOOD]})
    out = run(actor, turn_input(sim, "LOG"))
    assert out.status == "submitted" and [r.status for r in out.call_rows] == ["error", "ok"] and out.model_calls == 2

    actor, _, sim = make_actor("LOG", {("LOG", 1): [Fail(ProviderError("401", retryable=False, status=401)), GOOD]})
    out = run(actor, turn_input(sim, "LOG"))
    assert out.status == "failed" and [r.status for r in out.call_rows] == ["error"]
    assert any("provider error" in e for e in out.errors)


# --- isolation (AC-001, AC-025 slice) ------------------------------------------------------------------------------

def test_three_actors_share_nothing_and_leak_nothing():
    sim = StubSim()
    provider = FakeProvider({(a, 1): propose() for a in ("EVAC", "FIRE", "LOG")})
    actors = {a: Actor(ActorState(agent_id=a, targets=DEFAULT_TARGETS), provider, sim) for a in ("EVAC", "FIRE", "LOG")}
    assert len({id(x.state) for x in actors.values()}) == 3 and len({id(x.state.aspirations) for x in actors.values()}) == 3

    async def all_turns():
        return await asyncio.gather(*(actors[a].run_turn(turn_input(sim, a)) for a in ("EVAC", "FIRE", "LOG")))

    outcomes = asyncio.run(all_turns())
    assert all(o.status == "submitted" for o in outcomes)
    markers = {"LOG": ["E-LOG-01", "CLOSED_CLEARABLE"], "FIRE": ["E-FIRE-01", '"firebreak_bonus":true'],
               "EVAC": ["E-EVAC-01", '"assisted_initial":60']}
    for req in provider.requests:
        text = req.system + "".join(m.text for m in req.messages if isinstance(m, UserText))
        for holder, words in markers.items():
            for w in words:
                assert (w in text) is (holder == req.agent_id), f"{w} vs {req.agent_id}"


def test_transcript_matches_prompt_capture_shape():
    actor, _, sim = make_actor("LOG", {("LOG", 1): [FIND, GOOD]})
    out = run(actor, turn_input(sim, "LOG"))
    assert [t["role"] for t in out.transcript] == ["system", "user", "tool", "assistant"]


# --- ledgers (§10.5, §10.4) ----------------------------------------------------------------------------------------

def test_ledgers_write_jsonl_and_redact(tmp_path):
    actor, _, sim = make_actor("LOG", {("LOG", 1): [FIND, GOOD]})
    out = run(actor, turn_input(sim, "LOG"))
    calls, tools = CallLedger(), ToolLedger()
    calls.extend(out.call_rows)
    tools.extend(out.tool_rows)
    assert calls.totals()["calls"] == 2 and calls.totals()["ok"] == 2 and tools.totals()["tool_calls"] == 1
    # Fixture kept below scripts/check.sh's key-pattern threshold (sk-ant- + 10 chars) on purpose (NFR-006).
    calls.rows[0].error = "leaked sk-ant-abcdefghi in message"
    n = calls.write_jsonl(tmp_path / "calls.jsonl")
    lines = (tmp_path / "calls.jsonl").read_text().splitlines()
    assert n == 2 and len(lines) == 2 and "sk-ant-abcdefghi" not in lines[0] and "sk-REDACTED" in lines[0]
    assert json.loads(lines[1])["purpose"] == "tool_iteration"
    assert redact("key sk-abcdefghijkl end") == "key sk-REDACTED end"


# --- proposer-view validation (§6.4 "bounced back to the proposer as that turn's repair attempt") -----------------

def test_plan_invalid_on_own_view_is_bounced_into_repair():
    r2_plan = propose(["E-LOG-01"])
    r2_plan["messages"][0]["plan"] = [dict(DRIVE, destination="PR", route_ids=["R1", "R2"])]
    actor, provider, sim = make_actor("LOG", {("LOG", 1): [r2_plan, GOOD]})
    out = run(actor, turn_input(sim, "LOG"))
    assert out.status == "submitted" and out.model_calls == 2
    repair = [m.text for m in provider.requests[1].messages if isinstance(m, UserText)]
    assert any("ROAD_CLOSED" in t and "your own view" in t for t in repair)


def test_same_plan_is_valid_on_evacuations_view():
    """AC-024 via the actor: Evacuation does not know R2 is closed, so its proposal over R2 is not bounced."""
    r2_plan = propose()
    r2_plan["messages"][0]["plan"] = [dict(DRIVE, destination="PR", route_ids=["R1", "R2"])]
    actor, _, sim = make_actor("EVAC", {("EVAC", 1): r2_plan})
    out = run(actor, turn_input(sim, "EVAC"))
    assert out.status == "submitted" and out.model_calls == 1
