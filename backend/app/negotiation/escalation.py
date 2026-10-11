"""Escalation triggers, package and fallback F0 (PRD §6.9, §5.8, §7.7; FR-050, D-14).

Triggers (first one wins when several apply): round 4 ends without a commit; wall-clock budget exceeded at a round
boundary; all non-degraded agents ESCALATE in the same round; an actor is DEGRADED (unanimity impossible).

The package is computed by the simulator's authoritative validation and evaluations, never by a model:
candidates (plans valid on the authoritative world), per-candidate target checks, unmet targets per agent, open
objections, blocking constraints, and the fallback F0 = locked legs + the still-valid remaining legs of the last
committed plan (else locked legs + hold). Nothing here ranks candidates: the human (or, in benchmark mode, the
deterministic F0 rule) chooses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.agents.contracts import (
    AGENT_IDS,
    AgentId,
    Assignment,
    AssignmentDraft,
    EscalationPackage,
    Target,
    TargetCheck,
)
from app.agents.sim_stub import SimService
from app.negotiation.hash import plan_hash
from app.negotiation.router import DecisionPointRecord, PlanRecord

Trigger = Literal["ROUNDS_EXHAUSTED", "BUDGET_EXCEEDED", "ALL_ESCALATED", "AGENT_UNAVAILABLE"]
CANDIDATE_STATES = {"PROPOSED", "EVALUATED", "CHALLENGED", "PARTIALLY_ACCEPTED", "UNANIMOUS", "REJECTED_AT_COMMIT"}


def escalation_trigger(rec: DecisionPointRecord, *, rounds: int) -> Trigger | None:
    """§6.9 triggers in PRD precedence. Evaluated at every round boundary after the gate ran."""
    if rec.outcome == "committed":
        return None
    if rec.round >= rounds:
        return "ROUNDS_EXHAUSTED"
    if rec.budget_exceeded:
        return "BUDGET_EXCEEDED"
    active = set(AGENT_IDS) - rec.degraded_agents
    if active and rec.escalate_votes.get(rec.round, set()) >= active:
        return "ALL_ESCALATED"
    if rec.degraded_agents:
        return "AGENT_UNAVAILABLE"
    return None


@dataclass
class Fallback:
    assignments: list[Assignment]
    plan_hash: str
    source: Literal["last_committed", "locked_only"]


def build_fallback_from(locked: list[Assignment], last_committed: list[Assignment] | None, sim: SimService, *,
                        run_id: str, scenario_id: str, state_version: int) -> Fallback:
    """F0 (§6.9): locked legs + remaining legs of the last committed plan that are still valid; else locked + hold.
    Shared by the negotiation escalation and the benchmark baselines (D-14: the same deterministic fallback)."""
    authoritative = sim.build_belief_view("authoritative")
    remaining = [a for a in (last_committed or []) if not a.locked and a.end_step > authoritative.step]
    candidate = [*locked, *remaining]
    if remaining and not sim.validate_plan(authoritative, _drafts(candidate)):
        chosen, source = candidate, "last_committed"
    else:
        chosen, source = list(locked), "locked_only"
    chosen = [a.model_copy(update={"order": i}) for i, a in enumerate(chosen)]
    return Fallback(assignments=chosen, plan_hash=plan_hash(run_id, scenario_id, state_version, chosen),
                    source=source)  # type: ignore[arg-type]


def build_fallback(rec: DecisionPointRecord, sim: SimService, *, last_committed: list[Assignment] | None) -> Fallback:
    return build_fallback_from(rec.locked, last_committed, sim, run_id=rec.run_id, scenario_id=rec.scenario_id,
                               state_version=rec.state_version)


def build_package(rec: DecisionPointRecord, sim: SimService, *, trigger: Trigger,
                  targets: dict[AgentId, list[Target]], last_committed: list[Assignment] | None) -> EscalationPackage:
    authoritative = sim.build_belief_view("authoritative")
    candidates: list[str] = []
    checks: dict[str, list[TargetCheck]] = {}
    blocking: list[str] = []
    for record in sorted(rec.plans.values(), key=lambda r: r.first_proposed_seq):
        if record.plan.state not in CANDIDATE_STATES:
            continue
        violations = sim.validate_plan(authoritative, record.drafts)
        if violations:
            blocking.extend(_describe(v.code, v.resource_id, v.road_id, record.plan.plan_id) for v in violations)
            continue
        candidates.append(record.hash)
        auth = record.evaluations.get("authoritative")
        checks[record.hash] = list(auth.target_checks) if auth else []
    for rejection in rec.rejections:
        blocking.extend(_describe(v["code"], v.get("resource_id"), v.get("road_id"), rejection["plan_id"])
                        for v in rejection["violations"])

    unmet: dict[AgentId, list[str]] = {}
    for agent in AGENT_IDS:
        unmet[agent] = []
        for t in targets.get(agent, []):
            relevant = [c for h in candidates for c in checks[h] if c.agent_id == agent and c.metric == t.metric]
            if not relevant or not any(c.meets_aspiration for c in relevant):
                unmet[agent].append(t.metric)
            if relevant and candidates and not any(c.meets_floor for c in relevant):
                blocking.append(f"{t.metric.upper()}_FLOOR unmet in all candidates")

    fallback = build_fallback(rec, sim, last_committed=last_committed)
    rec.fallback_assignments, rec.fallback_hash = fallback.assignments, fallback.plan_hash
    return EscalationPackage(
        run_id=rec.run_id, dp_id=rec.dp_id, state_version=rec.state_version, trigger=trigger,
        candidates=candidates, candidate_checks=checks, unmet_targets=unmet,
        open_objections=_open_objections(rec), blocking_constraints=list(dict.fromkeys(blocking)),
        fallback_plan_hash=fallback.plan_hash,
    )


def _open_objections(rec: DecisionPointRecord) -> list[str]:
    """Latest unanswered CHALLENGE per agent: the challenger never accepted the challenged plan afterwards."""
    out: list[str] = []
    for agent in AGENT_IDS:
        challenges = [m for m in rec.messages if m.status == "delivered" and m.sender == agent
                      and m.message_type == "CHALLENGE"]
        if not challenges:
            continue
        latest = challenges[-1]
        answered = any(a.agent_id == agent and a.plan_hash == latest.target_plan_hash and not a.revoked
                       for a in rec.acceptances)
        if not answered:
            out.append(latest.message_id)
    return out


def _describe(code: str, resource_id: str | None, road_id: str | None, plan_id: str) -> str:
    related = ", ".join(x for x in (resource_id, road_id) if x)
    return f"{code} in {plan_id}" + (f" (related: {related})" if related else "")


def _drafts(assignments: list[Assignment]) -> list[AssignmentDraft]:
    keep = set(AssignmentDraft.model_fields)
    return [AssignmentDraft.model_validate({k: v for k, v in a.model_dump().items() if k in keep}) for a in assignments]
