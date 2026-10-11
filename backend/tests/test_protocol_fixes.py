"""Regressions for the WS-B findings in the C7 audit (PRD §4.3, §6.3, §6.8, §6.9, §6.11, §10.2)."""

from __future__ import annotations

import pytest

from app.agents.prompt import DEFAULT_TARGETS
from app.agents.provider_fake import Refuse
from app.negotiation.gate import StaleDecisionPoint
from tests.test_protocol import (EVAC_PLAN, FIRE_PLAN, LOG_PLAN, SILENT, build, build_service, msg, run_dp, start,
                                 turn)

pytestmark = pytest.mark.usefixtures("test_mode")


@pytest.fixture
def test_mode(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_TEST", "1")


def test_cited_evidence_is_disclosed_before_recipients_evaluate_the_plan():
    """§4.3 + FR-024: a recipient's delivery-time evaluation must already know the evidence the message cites."""
    router, _, sim, _ = build({("EVAC", 1): SILENT, ("FIRE", 1): SILENT, ("LOG", 1): LOG_PLAN})
    order: list[str] = []
    disclose, evaluate = sim.disclose, sim.evaluate_plan
    sim.disclose = lambda eid, to: (order.append(f"disclose:{to}"), disclose(eid, to))[1]
    sim.evaluate_plan = lambda view, drafts, **kw: (order.append(f"evaluate:{view.agent}"), evaluate(view, drafts, **kw))[1]
    run_dp(router)
    for recipient in ("EVAC", "FIRE"):
        assert order.index(f"disclose:{recipient}") < order.index(f"evaluate:{recipient}")


def test_rejected_message_discloses_nothing():
    router, _, sim, events = build({("EVAC", 1): SILENT, ("FIRE", 1): SILENT,
                                    ("LOG", 1): turn(msg("ACCEPT", target_plan_hash="nope", evidence_ids=["E-LOG-01"]))})
    run_dp(router)
    assert not [e for e in events if e.type == "evidence.disclosed"]


def test_target_revision_reaches_peers_and_the_simulator_and_never_the_defaults():
    """§6.11: revisions are public — peers' target tables and simulator target checks use the new aspiration."""
    revision = {"metric": "fire_extent", "old_aspiration": 22, "new_aspiration": 26, "reason": "R2 needs a crew"}
    router, _, sim, _ = build({("EVAC", 1): SILENT, ("LOG", 1): SILENT,
                               ("FIRE", 1): {**FIRE_PLAN, "target_revision": revision}})
    seen: list[tuple] = []
    sim.set_target_aspiration = lambda agent, metric, value: seen.append((agent, metric, value))
    default_before = [t.aspiration for t in DEFAULT_TARGETS["FIRE"]]
    run_dp(router)
    for agent in ("EVAC", "LOG", "FIRE"):
        fire_extent = next(t for t in router.actors[agent].state.targets["FIRE"] if t.metric == "fire_extent")
        assert fire_extent.aspiration == 26
    assert seen == [("FIRE", "fire_extent", 26)]
    assert [t.aspiration for t in DEFAULT_TARGETS["FIRE"]] == default_before


def test_aggregate_call_budget_stops_the_decision_point():
    """§10.2 / NFR-004: calls are capped across all actors for the whole decision point → BUDGET_EXCEEDED."""
    service, _, _, _ = build_service({(a, r): SILENT for a in ("EVAC", "FIRE", "LOG") for r in (1, 2, 3, 4)},
                                     rounds=4)
    service.router.settings.dp_max_calls = 5          # round 1 uses 3; fewer than 3 left → stop before round 2
    result = start(service)
    assert result.record.budget_exceeded and result.record.round == 1
    assert result.escalation.trigger == "BUDGET_EXCEEDED"
    assert result.record.model_calls <= 5


def test_second_failure_escalates_in_the_same_round():
    """§6.3 / §6.9 trigger 4: the turn that degrades an actor ends the decision point at that round boundary."""
    bad = [Refuse(), Refuse()]                          # refusal + failed repair = one failed turn
    scripts = {(a, r): SILENT for a in ("EVAC", "LOG") for r in (1, 2, 3, 4)}
    scripts |= {("FIRE", 1): bad, ("FIRE", 2): bad}
    service, _, _, _ = build_service(scripts, rounds=4)
    result = start(service)
    assert result.escalation.trigger == "AGENT_UNAVAILABLE"
    assert result.record.round == 2                     # not round 3


def test_fallback_commit_refuses_a_moved_world():
    """§6.8 parity: F0 (even locked-only) is re-checked against the current version before it is applied."""
    service, _, sim, _ = build_service({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT}, rounds=1)
    result = start(service)
    assert result.status == "escalated"
    sim.world["state_version"] += 1                     # the world moved after the package was built
    with pytest.raises(StaleDecisionPoint):
        service.resolve("dp-1", "fallback", expected_state_version=0)
