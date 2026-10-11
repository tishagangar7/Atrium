"""Negotiation service: the B → C boundary (PRD §12.2, §8.2, §4.6, §6.8–§6.11; FR-034, FR-040, FR-041, FR-051).

WS-C's endpoints call this and nothing deeper:

    POST /negotiate                      -> await service.start_decision_point(state_version, locked=...)
    POST /negotiate/cancel               -> service.cancel("cancelled by operator")
    POST /events/inject                  -> service.on_event_applied(new_state_version); then start the next DP
    POST /escalations/{dp_id}/resolve    -> service.resolve(dp_id, choice, plan_hash=..., target_revisions=...)

Every decision point ends COMMITTED or ESCALATED within the round and wall-clock budgets (FR-034), or is cancelled
by an event (then the next one opens at the new version). Humans can commit a listed candidate, commit F0, or relax
aspirations and run one more negotiation — nothing else exists (FR-051, AC-033). In benchmark mode escalation
resolves to F0 automatically with `authority: "auto_fallback"` (D-14).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.agents.actor import Actor
from app.agents.contracts import AGENT_IDS, AgentId, Assignment, Commit, EscalationPackage, Plan, Target, TargetRevision
from app.agents.prompt import DEFAULT_TARGETS
from app.agents.sim_stub import SimService
from app.negotiation.escalation import build_package, escalation_trigger
from app.negotiation.gate import Apply, CommitGate, StaleDecisionPoint
from app.negotiation.router import DecisionPointRecord, PlanRecord, Router, RouterSettings, Sink

Mode = Literal["live", "benchmark"]
Choice = Literal["candidate", "fallback", "relax"]


class NegotiationInProgress(Exception):
    pass


class NoActiveEscalation(Exception):
    pass


class PlanInfeasible(Exception):
    pass


@dataclass
class DecisionPointResult:
    dp_id: str
    status: Literal["committed", "escalated", "cancelled", "stale"]
    record: DecisionPointRecord
    commit: Commit | None = None
    escalation: EscalationPackage | None = None


@dataclass
class NewDecisionPoint:
    """`relax` resolution: the caller opens this decision point (same state_version, §6.9 option c)."""

    dp_id: str
    state_version: int
    revisions: list[TargetRevision] = field(default_factory=list)


class NegotiationService:
    def __init__(self, actors: dict[AgentId, Actor], sim: SimService, *, run_id: str, scenario_id: str,
                 sink: Sink | None = None, settings: RouterSettings | None = None, mode: Mode = "live",
                 apply: Apply | None = None, targets: dict[AgentId, list[Target]] | None = None):
        self.router = Router(actors, sim, run_id=run_id, scenario_id=scenario_id, sink=sink, settings=settings)
        self.gate = CommitGate(sim, apply=apply)
        self.actors, self.sim, self.mode = actors, sim, mode
        self.targets = targets or DEFAULT_TARGETS
        self.results: dict[str, DecisionPointResult] = {}
        self.last_committed: list[Assignment] | None = None
        self.open_escalation: str | None = None
        self._dp_counter = 0
        self._running = False

    # --- decision points ----------------------------------------------------------------------------------------

    def next_dp_id(self) -> str:
        self._dp_counter += 1
        return f"dp-{self._dp_counter}"

    @property
    def in_progress(self) -> bool:
        return self._running

    async def start_decision_point(self, state_version: int, *, locked: list[Assignment] | None = None,
                                   dp_id: str | None = None) -> DecisionPointResult:
        if self._running:
            raise NegotiationInProgress("a decision point is already running (409 NEGOTIATION_IN_PROGRESS)")
        self._running = True
        dp_id = dp_id or self.next_dp_id()
        try:
            rec = await self.router.run_decision_point(dp_id, state_version, locked=locked,
                                                       on_round_end=self._round_end)
        finally:
            self._running = False

        if rec.outcome == "committed":
            result = DecisionPointResult(dp_id, "committed", rec, commit=rec.commit)
        elif rec.outcome == "stale" or (rec.cancelled and rec.outcome is None and _is_event(rec.cancel_reason)):
            result = DecisionPointResult(dp_id, "stale", rec)
        elif rec.cancelled:
            result = DecisionPointResult(dp_id, "cancelled", rec)
        else:
            if rec.escalation is None:   # loop ended on budget or rounds without a round-end hook firing
                trigger = escalation_trigger(rec, rounds=self.router.settings.rounds) or "ROUNDS_EXHAUSTED"
                self._escalate(rec, trigger)
            result = DecisionPointResult(dp_id, "escalated", rec, escalation=rec.escalation)
            if self.mode == "benchmark":
                commit = self._commit_fallback(rec, authority="auto_fallback")
                result = DecisionPointResult(dp_id, "committed", rec, commit=commit, escalation=rec.escalation)
            else:
                self.open_escalation = dp_id
        self.results[dp_id] = result
        return result

    def cancel(self, reason: str = "cancelled by operator") -> None:
        self.router.cancel(reason)

    def on_event_applied(self, new_state_version: int) -> None:
        """FR-040/041 (§4.6): the event cancels in-flight turns, voids acceptances and stales open plans; results
        tagged with the old version are discarded. The caller opens the next decision point at `new_state_version`."""
        rec = self.router.current
        if rec is None:
            return
        if self._running:
            self.router.cancel(f"event applied: state_version {rec.state_version} -> {new_state_version}")
        self.router.mark_stale(rec)
        if self.open_escalation == rec.dp_id:
            self.open_escalation = None
            if rec.dp_id in self.results:
                self.results[rec.dp_id].status = "stale"

    # --- round boundary (§6.8 then §6.9) ---------------------------------------------------------------------------

    def _round_end(self, rec: DecisionPointRecord) -> str | None:
        try:
            result = self.gate.check(rec, emit=lambda t, d: self.router._emit(rec, t, d))
        except StaleDecisionPoint:
            self.router.mark_stale(rec)
            return "stop"
        if result.outcome == "committed":
            self.last_committed = rec.plans[result.commit.plan_hash].assignments if result.commit else None
            return "stop"
        trigger = escalation_trigger(rec, rounds=self.router.settings.rounds)
        if trigger is not None:
            self._escalate(rec, trigger)
            return "stop"
        return None

    def _escalate(self, rec: DecisionPointRecord, trigger: str) -> None:
        rec.escalation = build_package(rec, self.sim, trigger=trigger, targets=self.targets,  # type: ignore[arg-type]
                                       last_committed=self.last_committed)
        rec.outcome = "escalated"
        self.router._emit(rec, "escalation.opened", rec.escalation.model_dump(mode="json"))

    # --- human resolution (§6.9 options, FR-051) -------------------------------------------------------------------

    def resolve(self, dp_id: str, choice: Choice, *, expected_state_version: int, plan_hash: str | None = None,
                target_revisions: list[TargetRevision] | None = None) -> Commit | NewDecisionPoint:
        result = self.results.get(dp_id)
        if result is None or self.open_escalation != dp_id or result.record.escalation is None:
            raise NoActiveEscalation(f"no open escalation for {dp_id!r} (409 NO_ACTIVE_ESCALATION)")
        rec = result.record
        if expected_state_version != rec.state_version:
            raise NoActiveEscalation(f"escalation is at state_version {rec.state_version}, got {expected_state_version}")

        if choice == "candidate":
            full = self.router._resolve_hash(rec, plan_hash)
            if full is None or full not in rec.escalation.candidates:
                raise PlanInfeasible(f"{plan_hash!r} is not a feasible candidate (422 PLAN_INFEASIBLE)")
            record = rec.plans[full]
            if self.sim.validate_plan(self.sim.build_belief_view("authoritative"), record.drafts):
                raise PlanInfeasible(f"candidate {plan_hash!r} is no longer valid on the authoritative world")
            commit = self.gate.commit(rec, record, authority="human_choice", acceptances=[],
                                      emit=lambda t, d: self.router._emit(rec, t, d))
            self._close(result, commit, {"choice": "candidate", "plan_hash": full})
            return commit
        if choice == "fallback":
            commit = self._commit_fallback(rec, authority="human_choice")
            self._close(result, commit, {"choice": "fallback", "plan_hash": commit.plan_hash})
            return commit
        if choice == "relax":
            revisions = list(target_revisions or [])
            if not revisions:
                raise ValueError("relax requires at least one target_revision")
            owners: list[AgentId] = []
            for rev in revisions:                                     # validate everything before touching state
                if rev.by != "human":
                    raise ValueError("relax revisions must carry by='human'")
                owner = next((a for a in AGENT_IDS if any(t.metric == rev.metric for t in self.targets.get(a, []))), None)
                if owner is None:
                    raise ValueError(f"unknown target metric {rev.metric!r}")
                owners.append(owner)
            for rev, owner in zip(revisions, owners):
                self.router.publish_revision(owner, rev)             # humans may pass the floor (§5.12)
                self.router._emit(rec, "target.revised", rev.model_dump(mode="json"), agent=owner)
            self.open_escalation = None
            self.router._emit(rec, "human.decision", {"choice": "relax", "plan_hash": None,
                                                      "revisions": [r.model_dump(mode="json") for r in revisions]})
            return NewDecisionPoint(dp_id=self.next_dp_id(), state_version=rec.state_version, revisions=revisions)
        raise ValueError(f"unknown choice {choice!r}; humans may only pick a candidate, the fallback, or relax targets")

    # --- internals --------------------------------------------------------------------------------------------------

    def _commit_fallback(self, rec: DecisionPointRecord, *, authority: Literal["human_choice", "auto_fallback"]) -> Commit:
        assert rec.fallback_hash is not None, "escalation package not built"
        authoritative = self.sim.build_belief_view("authoritative")
        f0 = rec.fallback_assignments
        from app.negotiation.escalation import _drafts
        from app.negotiation.gate import StaleDecisionPoint
        # Same guarantees as a unanimous commit (§6.8): the world must not have moved, and F0 — even locked-only —
        # must still be valid on the authoritative world right before it is applied.
        if authoritative.state_version != rec.state_version:
            raise StaleDecisionPoint(f"F0 built for state_version {rec.state_version}, world at {authoritative.state_version}")
        violations = self.sim.validate_plan(authoritative, _drafts(f0)) if f0 else []
        if violations:
            raise PlanInfeasible("fallback F0 is no longer valid: " + ", ".join(sorted({v.code for v in violations})))
        evaluation_id = ""
        if f0:
            evaluation_id = self.sim.evaluate_plan(authoritative, _drafts(f0), plan_hash=rec.fallback_hash).evaluation_id
        before = rec.state_version
        after = self.gate.apply(f0, rec.fallback_hash)
        commit = Commit(run_id=rec.run_id, dp_id=rec.dp_id, plan_hash=rec.fallback_hash, plan_id=f"{rec.dp_id}:F0",
                        state_version_before=before, state_version_after=after, acceptances=[],
                        ordering_rule="first_proposed_seq", authority=authority,
                        authoritative_evaluation_id=evaluation_id, ts=_now_iso_ms(), step=authoritative.step)
        rec.commit, rec.outcome = commit, "committed"
        self.last_committed = list(f0)
        self.router._emit(rec, "plan.committed", commit.model_dump(mode="json"))
        return commit

    def _close(self, result: DecisionPointResult, commit: Commit, decision: dict[str, Any]) -> None:
        result.status, result.commit = "committed", commit
        self.last_committed = (self.router.current.plans[commit.plan_hash].assignments
                               if self.router.current and commit.plan_hash in self.router.current.plans
                               else self.last_committed)
        self.open_escalation = None
        self.router._emit(result.record, "human.decision", decision)


def _is_event(reason: str | None) -> bool:
    return bool(reason and reason.startswith("event applied"))


def _now_iso_ms() -> str:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
