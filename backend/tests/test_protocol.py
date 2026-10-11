"""Router protocol tests with the TEST PROVIDER and the simulator stub (PRD §6.4–§6.7, §6.10, §4.3, §11.5).

Three real `Actor`s, scripted turns, synchronous rounds, canonical delivery. Pins AC-003 (evidence obtained from a
peer), AC-004 (no-change counterproposals), AC-005 (one own-view evaluation per inbox entry), AC-024, AC-025 slice,
AC-027 (near-identical hashes), AC-029 (late/silent never delivered), AC-032 slice (cancellation), FR-031 (router
never ranks). Commit gate and escalation are B4 and are not asserted here.
"""

from __future__ import annotations

import asyncio
import inspect
import re

import pytest

from app.agents.actor import Actor, ActorState
from app.agents.contracts import Assignment
from app.agents.prompt import DEFAULT_TARGETS
from app.agents.provider import UserText
from app.agents.provider_fake import FakeProvider
from app.agents.schema import INT_SENTINEL
from app.agents.sim_stub import StubSim
from app.negotiation import router as router_module
from app.negotiation.hash import plan_hash
from app.negotiation.normalize import NormalizeError, normalize
from app.negotiation.router import Router, RouterEvent, RouterSettings

pytestmark = pytest.mark.usefixtures("test_mode")


@pytest.fixture
def test_mode(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_TEST", "1")


NO_OBJ = {"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""}
NO_REV = {"metric": "", "old_aspiration": 0, "new_aspiration": 0, "reason": ""}
SILENT = {"messages": [], "target_revision": NO_REV}


def draft(resource="B1", dest="VJ", routes=("R1", "R3"), start=0, task="drive", **kw):
    d = {"resource_id": resource, "task": task, "origin": "BASE", "destination": dest, "route_ids": list(routes),
         "start_step": start, "people_count": INT_SENTINEL, "zone_id": "", "shelter_id": "", "crew_id": "",
         "target_cells": [], "edge_id": "", "duration_steps": INT_SENTINEL}
    d.update(kw)
    return d


def msg(message_type="PROPOSE", **kw):
    m = {"message_type": message_type, "recipients": [], "plan": [], "parent_plan_id": "", "target_plan_id": "",
         "target_plan_hash": "", "objection": NO_OBJ, "evidence_ids": [], "caused_by": [], "requested_evidence_id": "",
         "requested_topic": "", "shared_evidence_ids": [], "reason": "", "blocking": [], "rationale": "ok"}
    m.update(kw)
    return m


def turn(*messages, revision=None):
    return {"messages": list(messages), "target_revision": revision or NO_REV}


EVAC_PLAN = turn(msg(plan=[draft("B1")]))                                      # B1 BASE→VJ via R1,R3
FIRE_PLAN = turn(msg(plan=[draft("C1", dest="VJ", routes=("R3",), origin="FORK")]))   # C1 FORK→VJ
LOG_PLAN = turn(msg(plan=[draft("B2", start=2)], evidence_ids=["E-LOG-01"]))  # cites private evidence


def build(scripts: dict, *, rounds=1, sim: StubSim | None = None, **fake_kw):
    sim = sim or StubSim()
    provider = FakeProvider(scripts, **fake_kw)
    actors = {a: Actor(ActorState(agent_id=a, targets=DEFAULT_TARGETS), provider, sim) for a in ("EVAC", "FIRE", "LOG")}
    events: list[RouterEvent] = []
    router = Router(actors, sim, run_id="run-t", scenario_id="normal", sink=events.append,
                    settings=RouterSettings(rounds=rounds, turn_deadline_s=2.0, dp_budget_s=30.0))
    return router, provider, sim, events


def run_dp(router: Router, dp="dp-1", version=0, **kw):
    return asyncio.run(router.run_decision_point(dp, version, **kw))


def types(events, t):
    return [e for e in events if e.type == t]


# --- round 1: proposals, delivery services, acceptances ------------------------------------------------------------

def test_round_one_delivery_in_canonical_order_with_own_view_evaluations():
    router, provider, sim, events = build({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): FIRE_PLAN, ("LOG", 1): LOG_PLAN})
    rec = run_dp(router)
    delivered = [m for m in rec.messages if m.status == "delivered"]
    assert [m.message_id for m in delivered] == ["dp-1:r1:EVAC:0", "dp-1:r1:FIRE:0", "dp-1:r1:LOG:0"]
    assert [m.proposal_id for m in delivered] == ["dp-1:P1", "dp-1:P2", "dp-1:P3"]
    assert all(p.plan.state == "EVALUATED" for p in rec.plans.values())

    # AC-005 / FR-024: every inbox entry carries exactly one evaluation, computed on the recipient's own view.
    for agent, items in rec.pending_inbox.items():
        assert len(items) == 2 and all(i.evaluation is not None and i.evaluation.basis == f"view_{agent}" for i in items)
        assert all(i.message.sender != agent for i in items)
    # authoritative evaluations exist for the dashboard but never enter an inbox (§4.3, AC-025 slice)
    bases = [e.data["basis"] for e in types(events, "evaluation.created")]
    assert bases.count("authoritative") == 3 and not any(
        i.evaluation.basis == "authoritative" for items in rec.pending_inbox.values() for i in items)
    assert all("authoritative" in p.evaluations and p.plan.evaluation_ids for p in rec.plans.values())
    # D-09: proposing counts as accepting
    assert {(a.agent_id, a.via) for a in rec.acceptances} == {("EVAC", "PROPOSE"), ("FIRE", "PROPOSE"), ("LOG", "PROPOSE")}
    assert [e.data["status"] for e in types(events, "agent.turn")] == ["submitted"] * 3


def test_citing_evidence_discloses_it_and_changes_recipient_view():
    """AC-003 mechanics / §4.3: LOG cites E-LOG-01 → EVAC and FIRE now hold it; round-2 prompts show it."""
    router, provider, sim, events = build({("EVAC", 1): SILENT, ("FIRE", 1): SILENT, ("LOG", 1): LOG_PLAN,
                                           ("EVAC", 2): SILENT, ("FIRE", 2): SILENT, ("LOG", 2): SILENT}, rounds=2)
    rec = run_dp(router)
    disclosed = types(events, "evidence.disclosed")
    assert [(d.data["evidence_id"], d.data["from"], sorted(d.data["to"])) for d in disclosed] == [("E-LOG-01", "LOG", ["EVAC", "FIRE"])]
    assert sim.build_belief_view("EVAC").world["roads"]["R2"]["initial_status"] == "CLOSED_CLEARABLE"
    round2 = [r for r in provider.requests if r.agent_id == "EVAC"][1]
    prompt = "".join(m.text for m in round2.messages if isinstance(m, UserText))
    assert "E-LOG-01" in prompt and '"message_id":"dp-1:r1:LOG:0"' in prompt
    assert "E-LOG-02" not in prompt   # un-cited evidence stays private


def test_normalization_uses_proposers_view():
    """§6.7 step 1 on the proposer's view: empty routes become the shortest path *that agent* knows."""
    sim = StubSim()
    empty_route = [draft("B1", dest="PR", routes=())]
    for agent, expected in (("EVAC", ["R1", "R2"]), ("LOG", ["R1", "R3", "R4"])):
        from app.agents.schema import parse_assignment_drafts
        normalized = normalize(parse_assignment_drafts(empty_route), view=sim.build_belief_view(agent), sim=sim)
        assert normalized[0].route_ids == expected and normalized[0].locked is False and normalized[0].order == 0
        assert normalized[0].end_step == {"EVAC": 6, "LOG": 9}[agent]


def test_normalization_fills_start_step_and_prepends_locked():
    sim = StubSim()
    from app.agents.schema import parse_assignment_drafts
    locked = [Assignment(order=0, locked=True, resource_id="V1", task="drive", origin="BASE", destination="FORK",
                         route_ids=["R1"], start_step=0, end_step=3, wait_steps=0, people_count=None, zone_id=None,
                         shelter_id=None, crew_id=None, target_cells=[], edge_id=None, duration_steps=None)]
    drafts = parse_assignment_drafts([draft("B1", start=INT_SENTINEL),
                                      draft("B1", dest="SS", routes=("R5",), start=INT_SENTINEL, origin="VJ")])
    out = normalize(drafts, view=sim.build_belief_view("LOG"), sim=sim, locked=locked)
    assert [a.resource_id for a in out] == ["V1", "B1", "B1"] and out[0].locked and out[0].order == 0
    assert (out[1].start_step, out[1].end_step) == (0, 5) and (out[2].start_step, out[2].end_step) == (5, 8)
    with pytest.raises(NormalizeError):
        normalize(parse_assignment_drafts([draft("C1", dest="PASS", routes=(), origin="FORK")]),
                  view=sim.build_belief_view("FIRE"), sim=sim)      # crews cannot reach PASS by engine road


# --- §6.10 drop rules and §6.5 message effects -----------------------------------------------------------------------

def test_counterpropose_with_same_hash_is_no_change_and_changed_start_is_new_plan():
    """AC-004 / FR-025 and AC-027: wording-only counterproposals die; one start_step changes the hash."""
    same = turn(msg("COUNTERPROPOSE", plan=[draft("B1")], parent_plan_id="dp-1:P1", caused_by=["dp-1:r1:EVAC:0"],
                    rationale="Same plan, nicer words."))
    shifted = turn(msg("COUNTERPROPOSE", plan=[draft("B1", start=1)], parent_plan_id="dp-1:P1",
                       caused_by=["dp-1:r1:EVAC:0"]))
    router, _, _, events = build({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
                                  ("EVAC", 2): SILENT, ("FIRE", 2): same, ("LOG", 2): shifted}, rounds=2)
    rec = run_dp(router)
    dropped = [m for m in rec.messages if m.status == "dropped"]
    assert [(m.sender, m.drop_reason) for m in dropped] == [("FIRE", "NO_CHANGE")]
    assert list(rec.plan_ids) == ["dp-1:P1", "dp-1:P2"]
    p1, p2 = (rec.plans[rec.plan_ids[i]] for i in ("dp-1:P1", "dp-1:P2"))
    assert p1.hash != p2.hash and p2.plan.parent_plan_id == "dp-1:P1" and p2.plan.proposer == "LOG"
    # the FIRE notice lands in FIRE's next inbox as its own dropped message
    assert any(i.message.drop_reason == "NO_CHANGE" for i in rec.pending_inbox["FIRE"])


def test_accept_records_acceptance_and_counts_toward_unanimity():
    router, _, _, events = build({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
                                  ("EVAC", 2): SILENT,
                                  ("FIRE", 2): lambda req: turn(msg("ACCEPT", target_plan_hash=_hash_in(req))),
                                  ("LOG", 2): lambda req: turn(msg("ACCEPT", target_plan_hash=_hash_in(req)))},
                                 rounds=2)
    rec = run_dp(router)
    plan = next(iter(rec.plans.values()))
    assert {a.agent_id for a in rec.live_acceptances(plan.hash)} == {"EVAC", "FIRE", "LOG"}
    assert plan.plan.state == "UNANIMOUS"          # counting only; the commit itself is B4's gate
    assert [e.data["state"] for e in types(events, "plan.state")] == ["EVALUATED", "UNANIMOUS"]


def test_accept_of_unknown_hash_is_dropped_with_notice():
    """§6.10 INVALID_REFERENCE; AC-029: it never becomes an acceptance."""
    bogus = turn(msg("ACCEPT", target_plan_hash="deadbeefdead"))
    router, _, _, _ = build({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
                             ("EVAC", 2): SILENT, ("FIRE", 2): bogus, ("LOG", 2): SILENT}, rounds=2)
    rec = run_dp(router)
    # First line of defense: the actor's own validation rejects it (repair, then a failed turn) — never submitted.
    assert rec.turn_status[2]["FIRE"] == "failed" and all(a.agent_id != "FIRE" for a in rec.acceptances)

    # Second line of defense: a submitted bogus ACCEPT is dropped by the router with a notice to the sender.
    from app.agents.actor import TurnOutcome
    from app.agents.schema import parse_turn
    out = TurnOutcome(agent_id="FIRE", status="submitted", turn=parse_turn(bogus, agent_id="FIRE", dp_id="dp-1"))
    router.deliver(rec, 3, {"FIRE": out})
    dropped = [m for m in rec.messages if m.status == "dropped"]
    assert [(m.sender, m.drop_reason) for m in dropped] == [("FIRE", "INVALID_REFERENCE")]
    assert all(a.agent_id != "FIRE" for a in rec.acceptances)
    assert rec.pending_inbox["FIRE"][-1].message.drop_reason == "INVALID_REFERENCE"


def test_duplicate_message_id_is_dropped(monkeypatch):
    from app.agents.actor import TurnOutcome
    from app.agents.schema import parse_turn
    router, _, sim, _ = build({})
    rec = asyncio.run(router.run_decision_point("dp-1", 0, on_round_end=lambda r: "stop"))
    out = TurnOutcome(agent_id="EVAC", status="submitted", turn=parse_turn(EVAC_PLAN, agent_id="EVAC", dp_id="dp-1"))
    router.deliver(rec, 1, {"EVAC": out})
    router.deliver(rec, 1, {"EVAC": out})       # same round, same index → same message_id
    assert [(m.message_id, m.status, m.drop_reason) for m in rec.messages] == [
        ("dp-1:r1:EVAC:0", "delivered", None), ("dp-1:r1:EVAC:0", "dropped", "DUPLICATE")]
    assert len(rec.plans) == 1 and len(rec.acceptances) == 1


def test_stale_version_drops_everything():
    """Invariant 6 / FR-040 hook: outputs tagged with an old state_version never deliver."""
    from app.agents.actor import TurnOutcome
    from app.agents.schema import parse_turn
    router, _, _, _ = build({})
    rec = asyncio.run(router.run_decision_point("dp-1", 0, on_round_end=lambda r: "stop"))
    out = TurnOutcome(agent_id="LOG", status="submitted", turn=parse_turn(LOG_PLAN, agent_id="LOG", dp_id="dp-1"))
    router.deliver(rec, 1, {"LOG": out}, current_state_version=1)
    assert [m.drop_reason for m in rec.messages] == ["STALE"] and not rec.plans and not rec.acceptances


def test_plan_invalid_on_proposer_view_is_bounced_by_router_safety_net():
    from app.agents.actor import TurnOutcome
    from app.agents.schema import parse_turn
    router, _, _, events = build({})
    rec = asyncio.run(router.run_decision_point("dp-1", 0, on_round_end=lambda r: "stop"))
    bad = turn(msg(plan=[draft("B1", dest="PR", routes=("R1", "R2"))], evidence_ids=["E-LOG-01"]))
    out = TurnOutcome(agent_id="LOG", status="submitted", turn=parse_turn(bad, agent_id="LOG", dp_id="dp-1"))
    router.deliver(rec, 1, {"LOG": out})
    assert types(events, "plan.bounced")[0].data["violations"][0]["code"] == "ROAD_CLOSED"
    assert rec.messages[0].drop_reason == "INVALID_PLAN" and not rec.plans


# --- deadlines, degraded actors, cancellation --------------------------------------------------------------------------

def test_late_actor_is_silent_this_round():
    """AC-029 / §6.10 LATE: the slow agent delivers nothing; the others proceed."""
    router, _, _, events = build({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): FIRE_PLAN, ("LOG", 1): LOG_PLAN}, delay_s=0.0)
    router.actors["LOG"].provider = FakeProvider({("LOG", 1): LOG_PLAN}, delay_s=3.0)
    router.settings.turn_deadline_s = 0.1
    rec = run_dp(router)
    assert rec.turn_status[1] == {"EVAC": "submitted", "FIRE": "submitted", "LOG": "late"}
    assert [m.sender for m in rec.messages] == ["EVAC", "FIRE"] and len(rec.plans) == 2


def test_degraded_actor_is_reported():
    router, _, _, _ = build({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): FIRE_PLAN, ("LOG", 1): LOG_PLAN})
    router.actors["FIRE"].state.degraded = True
    rec = run_dp(router)
    assert rec.degraded_agents == {"FIRE"} and rec.turn_status[1]["FIRE"] == "degraded"
    assert [m.sender for m in rec.messages] == ["EVAC", "LOG"]


def test_cancel_mid_round_discards_everything():
    """AC-032 slice / FR-041: cancellation stops the round; nothing from it is delivered."""
    router, _, _, events = build({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): FIRE_PLAN, ("LOG", 1): LOG_PLAN}, delay_s=1.0)
    router.settings.turn_deadline_s = 5.0

    async def scenario():
        task = asyncio.create_task(router.run_decision_point("dp-1", 0))
        await asyncio.sleep(0.05)
        router.cancel("event injected: wind_shift")
        return await task

    rec = asyncio.run(scenario())
    assert rec.cancelled and rec.cancel_reason.startswith("event injected") and rec.messages == [] and not rec.plans
    assert types(events, "negotiation.cancelled")[0].data["round"] == 1
    assert all(a.last_outcome is not None and a.last_outcome.status == "cancelled" for a in router.actors.values())
    assert all(a.state.consecutive_failures == 0 for a in router.actors.values())


# --- history, determinism, FR-031 ----------------------------------------------------------------------------------

def test_history_is_restricted_to_sent_or_received():
    router, _, _, _ = build({("EVAC", 1): turn(msg(plan=[draft("B1")], recipients=["FIRE"])),
                             ("FIRE", 1): SILENT, ("LOG", 1): LOG_PLAN})
    run_dp(router)
    assert [m["message_id"] for m in router.history_for("LOG")(None)] == ["dp-1:r1:LOG:0"]      # EVAC→FIRE only
    assert [m["message_id"] for m in router.history_for("FIRE")(None)] == ["dp-1:r1:EVAC:0", "dp-1:r1:LOG:0"]
    assert [m["message_id"] for m in router.history_for("EVAC")(None)] == ["dp-1:r1:EVAC:0", "dp-1:r1:LOG:0"]


def test_delivery_is_deterministic_for_the_same_scripted_turns():
    """AC-014 prep: identical scripts → identical message ids, plan ids and hashes."""
    runs = []
    for _ in range(2):
        router, _, _, _ = build({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): FIRE_PLAN, ("LOG", 1): LOG_PLAN})
        rec = run_dp(router)
        runs.append([(m.message_id, m.proposal_id, m.plan_hash) for m in rec.messages])
    assert runs[0] == runs[1]
    first = next(iter(rec.plans.values()))
    assert runs[0][0][2] == plan_hash("run-t", "normal", 0, first.assignments)


def test_router_never_ranks_or_reads_metrics():
    """FR-031 lint: no Metrics import, no metric access, no ordering over evaluations."""
    import ast
    tree = ast.parse(inspect.getsource(router_module))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
                for alias in node.names}
    assert "Metrics" not in imported and not any(n.endswith(".metrics") for n in imported)
    attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "metrics" not in attrs and "target_checks" in attrs   # reads own-view checks for the prompt only
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("sorted", "max", "min"):
            assert "evaluation" not in ast.unparse(node).lower(), ast.unparse(node)
    source = inspect.getsource(router_module)
    assert "first_proposed_seq" in source     # the only ordering the router keeps is delivery order


def test_router_requires_exactly_three_actors():
    sim = StubSim()
    provider = FakeProvider({})
    two = {a: Actor(ActorState(agent_id=a, targets=DEFAULT_TARGETS), provider, sim) for a in ("EVAC", "FIRE")}
    with pytest.raises(ValueError):
        Router(two, sim, run_id="r", scenario_id="normal")


# --- helpers -------------------------------------------------------------------------------------------------------

def _hash_in(request, n: int = 0) -> str:
    """Pull the n-th open plan hash out of the OPEN PLANS block of the prompt (what a real model would do)."""
    text = "".join(m.text for m in request.messages if isinstance(m, UserText))
    plans = text.split("OPEN PLANS: ", 1)[1].split("\n", 1)[0] if "OPEN PLANS: " in text else ""
    hashes = re.findall(r'"plan_hash":"([0-9a-f]{64})"', plans)
    return hashes[n] if len(hashes) > n else ""


def accept(n: int = 0):
    return lambda req: turn(msg("ACCEPT", target_plan_hash=_hash_in(req, n)))


def accept_both():
    return lambda req: turn(msg("ACCEPT", target_plan_hash=_hash_in(req, 0)), msg("ACCEPT", target_plan_hash=_hash_in(req, 1)))


# =====================================================================================================================
# B4: commit gate, escalation, resolution, version voiding (PRD §6.8, §6.9, §6.10; AC-006/007/027/028/029/032/033)
# =====================================================================================================================

from app.agents.contracts import TargetRevision  # noqa: E402
from app.negotiation.service import (  # noqa: E402
    NegotiationService,
    NewDecisionPoint,
    NoActiveEscalation,
    PlanInfeasible,
)

B1_SHIFTED = turn(msg(plan=[draft("B1", start=1)]))                      # same assignments as EVAC_PLAN, start_step 1
EVAC_R2_PLAN = turn(msg(plan=[draft("B1", dest="PR", routes=("R1", "R2"))]))   # valid on EVAC's view only


def build_service(scripts: dict, *, rounds=4, mode="live", sim: StubSim | None = None, budget=30.0, **fake_kw):
    sim = sim or StubSim()
    provider = FakeProvider(scripts, **fake_kw)
    actors = {a: Actor(ActorState(agent_id=a, targets=DEFAULT_TARGETS), provider, sim) for a in ("EVAC", "FIRE", "LOG")}
    events: list[RouterEvent] = []
    service = NegotiationService(actors, sim, run_id="run-t", scenario_id="normal", sink=events.append, mode=mode,
                                 settings=RouterSettings(rounds=rounds, turn_deadline_s=2.0, dp_budget_s=budget))
    return service, provider, sim, events


def start(service, version=0, **kw):
    return asyncio.run(service.start_decision_point(version, **kw))


def test_unanimous_identical_hash():
    """AC-006 / FR-030: three live acceptances of one hash at the current version commit; nothing less does."""
    service, _, sim, events = build_service({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
                                             ("EVAC", 2): SILENT, ("FIRE", 2): accept(), ("LOG", 2): accept()})
    result = start(service)
    assert result.status == "committed" and result.record.round == 2
    commit = result.commit
    assert commit.authority == "unanimous" and commit.ordering_rule == "first_proposed_seq"
    assert [a.agent_id for a in commit.acceptances] == ["EVAC", "FIRE", "LOG"]
    assert [a.via for a in commit.acceptances] == ["PROPOSE", "ACCEPT", "ACCEPT"]
    assert commit.state_version_before == 0 and commit.state_version_after == 1
    assert sim.world["state_version"] == 1 and sim.world["committed_plan_hash"] == commit.plan_hash
    assert result.record.plans[commit.plan_hash].plan.state == "COMMITTED"
    assert commit.authoritative_evaluation_id.startswith("ev-") and commit.plan_id == "dp-1:P1"
    assert [e.type for e in events if e.type in ("plan.committed", "escalation.opened")] == ["plan.committed"]
    assert service.last_committed and service.last_committed[0].resource_id == "B1"


def test_near_identical():
    """AC-027: two plans differing only in start_step never combine; 2/2 acceptances → no commit → escalation."""
    service, _, _, _ = build_service({("EVAC", 1): EVAC_PLAN, ("LOG", 1): B1_SHIFTED, ("FIRE", 1): SILENT,
                                      ("EVAC", 2): accept(1), ("FIRE", 2): accept(0), ("LOG", 2): SILENT}, rounds=2)
    result = start(service)
    assert result.status == "escalated" and result.commit is None
    rec = result.record
    p1, p2 = (rec.plans[rec.plan_ids[i]] for i in ("dp-1:P1", "dp-1:P2"))
    assert {a.agent_id for a in rec.live_acceptances(p1.hash)} == {"EVAC", "FIRE"}
    assert {a.agent_id for a in rec.live_acceptances(p2.hash)} == {"LOG", "EVAC"}
    assert result.escalation.trigger == "ROUNDS_EXHAUSTED" and set(result.escalation.candidates) == {p1.hash, p2.hash}


def test_two_unanimous():
    """AC-028 / FR-032: two plans unanimous in the same round → lower first-proposal seq commits; rule logged."""
    service, _, _, events = build_service({("EVAC", 1): EVAC_PLAN, ("LOG", 1): B1_SHIFTED, ("FIRE", 1): SILENT,
                                           ("EVAC", 2): accept(1), ("FIRE", 2): accept_both(), ("LOG", 2): accept(0)})
    result = start(service)
    rec = result.record
    assert result.status == "committed" and result.commit.plan_id == "dp-1:P1"
    assert rec.plans[rec.plan_ids["dp-1:P2"]].plan.state == "UNANIMOUS"      # was unanimous too, lost on ordering
    assert result.commit.ordering_rule == "first_proposed_seq"
    assert [e for e in events if e.type == "plan.committed"][0].data["ordering_rule"] == "first_proposed_seq"


def test_rejected_at_commit_broadcasts_violations():
    """§6.8 / §4.3: unanimous but invalid on the authoritative world → REJECTED_AT_COMMIT, acceptances void,
    violation codes published to every agent, negotiation continues."""
    service, provider, _, events = build_service(
        {("EVAC", 1): EVAC_R2_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
         ("EVAC", 2): SILENT, ("FIRE", 2): accept(), ("LOG", 2): accept(),
         ("EVAC", 3): SILENT, ("FIRE", 3): SILENT, ("LOG", 3): SILENT}, rounds=3)
    result = start(service)
    rec = result.record
    plan = next(iter(rec.plans.values()))
    assert plan.plan.state == "REJECTED_AT_COMMIT" and result.status == "escalated"
    assert all(a.revoked for a in rec.acceptances if a.plan_hash == plan.hash)
    disclosed = [e for e in events if e.type == "evidence.disclosed" and e.data.get("via") == "commit_rejection"]
    assert disclosed and disclosed[0].data["violations"][0]["code"] == "ROAD_CLOSED"
    for agent in ("EVAC", "FIRE", "LOG"):
        round3 = [r for r in provider.requests if r.agent_id == agent][2]
        text = "".join(m.text for m in round3.messages if isinstance(m, UserText))
        assert "NOTICES:" in text and "ROAD_CLOSED" in text and "dp-1:P1" in text
    assert plan.hash not in result.escalation.candidates
    assert any("ROAD_CLOSED" in b for b in result.escalation.blocking_constraints)


def test_late_accept():
    """AC-029: an ACCEPT that misses the turn deadline never becomes an acceptance."""
    service, _, _, _ = build_service({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
                                      ("EVAC", 2): SILENT, ("FIRE", 2): accept(), ("LOG", 2): accept()}, rounds=2)
    slow = FakeProvider({("LOG", 1): SILENT, ("LOG", 2): accept()}, delay_s=3.0)
    service.actors["LOG"].provider = slow
    service.router.settings.turn_deadline_s = 0.15
    result = start(service)
    assert result.record.turn_status[2]["LOG"] == "late" and result.status == "escalated" and result.commit is None
    plan = next(iter(result.record.plans.values()))
    assert {a.agent_id for a in result.record.live_acceptances(plan.hash)} == {"EVAC", "FIRE"}


def test_degraded_actor_escalates_agent_unavailable():
    """§6.9 trigger 4 / AC-029: a degraded actor makes unanimity impossible → early escalation, no commit."""
    service, _, _, events = build_service({("EVAC", 1): EVAC_PLAN, ("LOG", 1): SILENT})
    service.actors["FIRE"].state.degraded = True
    result = start(service)
    assert result.status == "escalated" and result.record.round == 1
    assert result.escalation.trigger == "AGENT_UNAVAILABLE" and len(result.escalation.candidates) == 1
    assert [e.type for e in events if e.type == "escalation.opened"] == ["escalation.opened"]


def test_all_escalated_ends_early():
    esc = turn(msg("ESCALATE", reason="No plan can meet my floor", blocking=["R4 capacity"]))
    service, _, _, _ = build_service({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
                                      ("EVAC", 2): esc, ("FIRE", 2): esc, ("LOG", 2): esc})
    result = start(service)
    assert result.status == "escalated" and result.escalation.trigger == "ALL_ESCALATED" and result.record.round == 2


def test_budget_exceeded():
    """§6.9 trigger 2 / FR-034: wall-clock budget checked at round boundaries."""
    service, _, _, _ = build_service({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT}, budget=0.05,
                                     delay_s=0.1)
    result = start(service)
    assert result.status == "escalated" and result.escalation.trigger == "BUDGET_EXCEEDED"
    assert result.record.round < 4


def test_rounds_exhausted_builds_package_with_fallback():
    """§6.9 package: valid candidates only, blocking constraints from invalid plans, F0 = locked legs + hold."""
    locked = [Assignment(order=0, locked=True, resource_id="V1", task="drive", origin="BASE", destination="FORK",
                         route_ids=["R1"], start_step=0, end_step=3, wait_steps=0, people_count=None, zone_id=None,
                         shelter_id=None, crew_id=None, target_cells=[], edge_id=None, duration_steps=None)]
    service, _, _, _ = build_service({("EVAC", 1): EVAC_R2_PLAN, ("LOG", 1): LOG_PLAN, ("FIRE", 1): SILENT}, rounds=1)
    result = start(service, locked=locked)
    pkg = result.escalation
    rec = result.record
    assert pkg.trigger == "ROUNDS_EXHAUSTED" and pkg.dp_id == "dp-1" and pkg.state_version == 0
    assert pkg.candidates == [rec.plan_ids["dp-1:P2"]]                       # EVAC's R2 plan is invalid authoritatively
    assert any(b.startswith("ROAD_CLOSED in dp-1:P1") and "R2" in b for b in pkg.blocking_constraints)
    assert pkg.fallback_plan_hash == plan_hash("run-t", "normal", 0, locked)
    assert rec.fallback_assignments[0].locked and rec.fallback_assignments[0].resource_id == "V1"
    assert pkg.unmet_targets["EVAC"] == ["assisted_completion", "civilian_exposure"]   # stub has no target checks
    assert pkg.open_objections == []


def test_human_resolve_limits():
    """FR-051 / AC-033: candidate, fallback or relax — nothing else; non-candidates are infeasible."""
    service, _, sim, events = build_service({("EVAC", 1): EVAC_PLAN, ("LOG", 1): B1_SHIFTED, ("FIRE", 1): SILENT}, rounds=1)
    result = start(service)
    rec = result.record
    with pytest.raises(PlanInfeasible):
        service.resolve("dp-1", "candidate", expected_state_version=0, plan_hash="deadbeef")
    with pytest.raises(NoActiveEscalation):
        service.resolve("dp-9", "candidate", expected_state_version=0, plan_hash=rec.plan_ids["dp-1:P1"])
    with pytest.raises(NoActiveEscalation):
        service.resolve("dp-1", "fallback", expected_state_version=3)
    with pytest.raises(ValueError):
        service.resolve("dp-1", "open_road", expected_state_version=0)  # type: ignore[arg-type]

    commit = service.resolve("dp-1", "candidate", expected_state_version=0, plan_hash=rec.plan_ids["dp-1:P1"][:12])
    assert commit.authority == "human_choice" and commit.acceptances == [] and commit.plan_id == "dp-1:P1"
    assert sim.world["state_version"] == 1 and service.results["dp-1"].status == "committed"
    decisions = [e for e in events if e.type == "human.decision"]
    assert decisions and decisions[0].data["choice"] == "candidate"
    with pytest.raises(NoActiveEscalation):
        service.resolve("dp-1", "fallback", expected_state_version=0)


def test_human_fallback_and_relax():
    service, _, sim, events = build_service({("EVAC", 1): SILENT, ("FIRE", 1): SILENT, ("LOG", 1): SILENT}, rounds=1)
    result = start(service)
    assert result.status == "escalated" and result.escalation.candidates == []
    commit = service.resolve("dp-1", "fallback", expected_state_version=0)
    assert commit.plan_id == "dp-1:F0" and commit.authority == "human_choice" and commit.plan_hash == result.escalation.fallback_plan_hash
    assert sim.world["state_version"] == 1

    result2 = start(service, version=1)
    rev = TargetRevision(by="human", metric="logistics_risk", old_aspiration=1, new_aspiration=5,
                         reason="Accept more schedule risk", dp_id="dp-2")
    with pytest.raises(ValueError):   # only humans relax here; an agent-attributed revision is rejected untouched
        service.resolve("dp-2", "relax", expected_state_version=1, target_revisions=[rev.model_copy(update={"by": "LOG"})])
    assert service.actors["LOG"].state.aspirations["logistics_risk"] == 1 and service.open_escalation == "dp-2"
    nxt = service.resolve("dp-2", "relax", expected_state_version=1, target_revisions=[rev])
    assert isinstance(nxt, NewDecisionPoint) and nxt.dp_id == "dp-3" and nxt.state_version == 1
    assert service.actors["LOG"].state.aspirations["logistics_risk"] == 5      # humans may pass the floor (3)
    assert any(e.type == "target.revised" and e.agent == "LOG" for e in events)
    assert service.open_escalation is None


def test_benchmark_auto_fallback():
    """D-14 / FR-052: benchmark escalations resolve to F0 deterministically; no human decision, no tie-break."""
    service, _, sim, events = build_service({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT},
                                            rounds=1, mode="benchmark")
    result = start(service)
    assert result.status == "committed" and result.commit.authority == "auto_fallback"
    assert result.commit.plan_id == "dp-1:F0" and result.escalation is not None
    assert result.escalation.candidates and result.commit.plan_hash != result.escalation.candidates[0]
    assert sim.world["state_version"] == 1 and not any(e.type == "human.decision" for e in events)
    assert [e.type for e in events if e.type in ("escalation.opened", "plan.committed")] == ["escalation.opened", "plan.committed"]


def test_event_voids_acceptances():
    """AC-007 / FR-040: a state_version change stales open plans and voids acceptances; the next DP is dp-2."""
    service, _, sim, events = build_service({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
                                             ("EVAC", 2): SILENT, ("FIRE", 2): accept(), ("LOG", 2): SILENT}, rounds=2)
    result = start(service)
    rec = result.record
    plan = next(iter(rec.plans.values()))
    assert len(rec.live_acceptances(plan.hash)) == 2 and result.status == "escalated"
    new_version = sim.apply_event({"event_id": "e1", "step": 15, "kind": "road_status", "target": "R3", "value": "CLOSED_HARD"})
    service.on_event_applied(new_version)
    assert plan.plan.state == "STALE" and rec.live_acceptances(plan.hash) == [] and all(a.revoked for a in rec.acceptances)
    assert service.results["dp-1"].status == "stale" and service.open_escalation is None
    with pytest.raises(NoActiveEscalation):
        service.resolve("dp-1", "fallback", expected_state_version=0)
    nxt = start(service, version=1)
    assert nxt.dp_id == "dp-2" and nxt.record.state_version == 1


def test_inject_mid_round():
    """AC-032 / FR-041: an event during a round cancels in-flight turns; late outputs are discarded."""
    service, _, sim, events = build_service({("EVAC", 1): EVAC_PLAN, ("FIRE", 1): FIRE_PLAN, ("LOG", 1): LOG_PLAN},
                                            delay_s=1.0)
    service.router.settings.turn_deadline_s = 5.0

    async def scenario():
        task = asyncio.create_task(service.start_decision_point(0))
        await asyncio.sleep(0.05)
        version = sim.apply_event({"event_id": "e1", "step": 0, "kind": "wind_change", "target": None, "value": "SE:3"})
        service.on_event_applied(version)
        return await task

    result = asyncio.run(scenario())
    assert result.status == "stale" and result.record.messages == [] and not result.record.plans
    assert [e.type for e in events if e.type == "negotiation.cancelled"] == ["negotiation.cancelled"]
    assert not service.in_progress
    nxt = start(service, version=1)
    assert nxt.dp_id == "dp-2" and nxt.record.state_version == 1 and sim.world["wind"]["direction"] == "SE"
