"""Single-agent baseline: union view, same tool/schema contract, matched vs natural budgets, F0 fallback
(PRD §11.2, §11.3, FR-061, AC-010, D-14)."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agents.contracts import Assignment
from app.agents.provider import ToolCall, UserText
from app.agents.provider_fake import FakeProvider, ToolCalls
from app.agents.schema import INT_SENTINEL, turn_output_schema
from app.agents.sim_stub import StubSim
from app.baselines.single_agent import MATCHED, NATURAL, BaselineBudget, SingleAgentBaseline
from app.negotiation.hash import plan_hash
from app.negotiation.router import RouterEvent, RouterSettings

pytestmark = pytest.mark.usefixtures("test_mode")


@pytest.fixture
def test_mode(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_TEST", "1")


NO_OBJ = {"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""}
NO_REV = {"metric": "", "old_aspiration": 0, "new_aspiration": 0, "reason": ""}
SILENT = {"messages": [], "target_revision": NO_REV}
DRIVE = {"resource_id": "B1", "task": "drive", "origin": "BASE", "destination": "VJ", "route_ids": ["R1", "R3"],
         "start_step": 0, "people_count": INT_SENTINEL, "zone_id": "", "shelter_id": "", "crew_id": "",
         "target_cells": [], "edge_id": "", "duration_steps": INT_SENTINEL}
PROPOSE = {"messages": [{"message_type": "PROPOSE", "recipients": [], "plan": [DRIVE], "parent_plan_id": "",
                         "target_plan_id": "", "target_plan_hash": "", "objection": NO_OBJ, "evidence_ids": [],
                         "caused_by": [], "requested_evidence_id": "", "requested_topic": "", "shared_evidence_ids": [],
                         "reason": "", "blocking": [], "rationale": "B1 to Valley Junction."}],
           "target_revision": NO_REV}
LOCKED = [Assignment(order=0, locked=True, resource_id="V1", task="drive", origin="BASE", destination="FORK",
                     route_ids=["R1"], start_step=0, end_step=3, wait_steps=0, people_count=None, zone_id=None,
                     shelter_id=None, crew_id=None, target_cells=[], edge_id=None, duration_steps=None)]
AGENT = "single_agent"


def build(script, *, budget=MATCHED, deadline=2.0, dp_budget=30.0, **fake_kw):
    sim = StubSim()
    provider = FakeProvider({(AGENT, r): s for r, s in enumerate(script, start=1)} if isinstance(script, list)
                            else script, **fake_kw)
    events: list[RouterEvent] = []
    baseline = SingleAgentBaseline(provider, sim, run_id="run-t", scenario_id="normal", budget=budget,
                                   sink=events.append,
                                   settings=RouterSettings(rounds=4, turn_deadline_s=deadline, dp_budget_s=dp_budget))
    return baseline, provider, sim, events


def decide(baseline, version=0, **kw):
    return asyncio.run(baseline.decide(version, **kw))


def prompt_text(request) -> str:
    return request.system + "".join(m.text for m in request.messages if isinstance(m, UserText))


def test_union_view_sees_every_evidence_item():
    """§5.9 / B§12: the baseline receives the union of all evidence — nothing is private to it."""
    baseline, provider, _, _ = build([PROPOSE])
    decide(baseline)
    text = prompt_text(provider.requests[0])
    for eid in ("E-EVAC-01", "E-EVAC-02", "E-EVAC-03", "E-FIRE-01", "E-FIRE-02", "E-LOG-01", "E-LOG-02"):
        assert eid in text
    assert "CLOSED_CLEARABLE" in text and '"background":320' in text and '"basis":"union"' in text
    assert "single incident decision-maker" in provider.requests[0].system and "no negotiation" in provider.requests[0].system
    assert "logistics_risk" in provider.requests[0].system and "assisted_completion" in provider.requests[0].system


def test_same_tool_and_schema_contract():
    """AC-010 / §11.2: identical tools and output schema to the negotiating agents; canonical hash."""
    baseline, provider, _, _ = build([PROPOSE])
    d = decide(baseline)
    req = provider.requests[0]
    assert [t.name for t in req.tools] == ["find_routes", "validate_plan", "evaluate_plan", "get_negotiation_history"]
    assert req.output_schema == turn_output_schema() and req.agent_id == AGENT
    assert d.plan_hash == plan_hash("run-t", "normal", 0, d.assignments)


def test_valid_plan_is_applied():
    baseline, _, sim, events = build([PROPOSE])
    d = decide(baseline)
    assert d.status == "committed" and d.method == "single_agent" and d.resolution is None
    assert d.model_calls == 1 and d.turns == 1 and d.invalid_attempted == 0
    assert d.budget_name == "matched" and d.budget_calls == 48 and d.budget_tokens == 120_000
    assert sim.world["state_version"] == 1 and sim.world["committed_plan_hash"] == d.plan_hash
    assert d.state_version_before == 0 and d.state_version_after == 1
    assert d.authoritative_evaluation_id.startswith("ev-") and d.assignments[0].resource_id == "B1"
    kinds = [e.type for e in events]
    assert kinds.count("baseline.decision") == 1 and kinds.count("agent.turn") == 1
    decision = next(e for e in events if e.type == "baseline.decision")
    assert decision.data["method"] == "single_agent" and decision.data["budget"] == "matched"
    assert baseline.last_committed == d.assignments


def test_tools_run_on_union_view():
    """The baseline's find_routes knows R2 is closed (union == authoritative statics)."""
    call = ToolCall("t1", "find_routes", {"resource_id": "B1", "origin": "BASE", "destination": "PR"})
    baseline, _, _, _ = build([[ToolCalls([call]), PROPOSE]])
    d = decide(baseline)
    assert d.status == "committed" and d.model_calls == 2 and len(d.tool_rows) == 1
    result = next(t["content"] for t in d.transcript if t["role"] == "tool")
    routes = json.loads(result.split(": ", 1)[1])["routes"]
    assert routes and all("R2" not in r["route_ids"] for r in routes)


def test_turn_without_plan_gets_a_notice_then_plan():
    baseline, provider, _, _ = build([SILENT, PROPOSE])
    d = decide(baseline)
    assert d.status == "committed" and d.turns == 2 and d.model_calls == 2
    second = prompt_text(provider.requests[1])
    assert "NOTICES:" in second and "exactly one PROPOSE" in second
    assert "NOTICES:" not in prompt_text(provider.requests[0])


def test_natural_budget_exhausts_then_fallback():
    """§11.2 natural (8 calls) + D-14: budget out → F0 (locked legs + hold), recorded AUTO_FALLBACK."""
    baseline, _, sim, events = build({(AGENT, r): SILENT for r in range(1, 20)}, budget=NATURAL)
    d = decide(baseline, locked=LOCKED)
    assert d.status == "fallback" and d.resolution == "AUTO_FALLBACK" and d.fallback_source == "locked_only"
    assert d.model_calls == 8 == d.budget_calls and d.turns == 8 and d.budget_name == "natural"
    assert d.plan_hash == plan_hash("run-t", "normal", 0, LOCKED) and d.assignments[0].locked
    assert sim.world["state_version"] == 1 and sim.world["committed_plan_hash"] == d.plan_hash
    assert next(e for e in events if e.type == "baseline.decision").data["resolution"] == "AUTO_FALLBACK"


def test_matched_budget_cap_is_exact_and_disclosed():
    small = BaselineBudget("matched", 5, 120_000)
    baseline, _, _, _ = build({(AGENT, r): SILENT for r in range(1, 20)}, budget=small)
    d = decide(baseline)
    assert d.model_calls == 5 and d.status == "fallback" and d.budget_calls == 5
    assert d.summary()["budget_calls"] == 5 and d.summary()["method"] == "single_agent"


def test_budget_never_exceeded_mid_turn():
    """A turn may use up to 4 calls; the per-DP cap still binds exactly."""
    call = ToolCall("t1", "find_routes", {"resource_id": "B1", "origin": "BASE", "destination": "VJ"})
    baseline, _, _, _ = build({(AGENT, r): [ToolCalls([call]), ToolCalls([call]), SILENT] for r in range(1, 20)},
                              budget=BaselineBudget("natural", 7, 120_000))
    d = decide(baseline)
    assert d.model_calls <= 7 and d.status == "fallback"


def test_deadline_twice_degrades_then_fallback():
    """§10.1: late turns are failed turns; two in a row → DEGRADED → F0."""
    baseline, _, _, _ = build([PROPOSE], deadline=0.05, delay_s=0.3)
    d = decide(baseline)
    assert d.status == "fallback" and d.turns == 2 and d.model_calls == 2
    assert all(r.status == "timeout" for r in d.call_rows)


def test_fallback_without_locked_legs_is_hold():
    baseline, _, sim, _ = build([SILENT], budget=BaselineBudget("natural", 1, 120_000))
    d = decide(baseline)
    assert d.status == "fallback" and d.assignments == [] and d.plan_hash == plan_hash("run-t", "normal", 0, [])
    assert d.authoritative_evaluation_id == "" and sim.world["state_version"] == 1


def test_decisions_are_deterministic_for_the_same_script():
    results = [decide(build([SILENT, PROPOSE])[0]) for _ in range(2)]
    assert [(r.plan_hash, r.model_calls, r.invalid_attempted, r.turns, r.status) for r in results] == \
        [(results[0].plan_hash, 2, 0, 2, "committed")] * 2


def test_world_moving_during_the_model_call_is_never_applied():
    """FR-040 / invariant 6: if the world's state_version changes while the model thinks, nothing is applied."""
    from app.negotiation.gate import StaleDecisionPoint

    baseline, provider, sim, events = build([PROPOSE])
    original = provider.complete

    async def world_moves(*args, **kwargs):
        sim.world["state_version"] += 1          # e.g. a scheduled event fired meanwhile
        return await original(*args, **kwargs)

    provider.complete = world_moves
    with pytest.raises(StaleDecisionPoint):
        decide(baseline)
    assert sim.world["committed_plan_hash"] is None
    assert not any(e.type == "baseline.decision" for e in events)
