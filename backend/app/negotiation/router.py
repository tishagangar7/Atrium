"""Router: synchronous rounds, canonical delivery, evidence disclosure, delivery-time services (PRD §6.4–§6.7,
§6.10, §4.3, D-06, D-09; invariant 1, FR-024, FR-031).

The router **delivers, dedupes, logs and enforces deadlines. It never ranks, scores or selects plans.** There is
deliberately no import of `Metrics` and no comparison of evaluations anywhere in this module (FR-031 lint test).

Per round the three actors run in parallel (`asyncio.gather`); each enforces its own turn deadline. At the round
boundary the router walks outputs in canonical order (EVAC, FIRE, LOG, then message index) and for each message:

  * assigns `message_id = {dp_id}:r{round}:{agent}:{index}`; drops duplicates, stale versions, references to
    unknown plans/hashes and citations of un-held evidence (§6.10);
  * for PROPOSE/COUNTERPROPOSE: normalizes on the **proposer's** view (§6.7 step 1), computes the canonical hash,
    bounces plans invalid on the proposer's view (`plan.bounced`), drops COUNTERPROPOSE whose hash equals its
    parent (`NO_CHANGE`), assigns `plan_id` in delivery order, records the proposer's acceptance (D-09), and asks
    the simulator for validate+evaluate on **each recipient's own view**, attaching only that recipient's result to
    its inbox copy; the authoritative check is emitted for the dashboard and never enters an inbox (§4.3);
  * discloses every cited or shared evidence id to the recipients (citing is sharing, §4.3);
  * records ACCEPT / WITHDRAW / ESCALATE for the commit gate and escalation logic (B4), which read
    `DecisionPointRecord` at the round boundary via `on_round_end`.

Events go to a sink as `RouterEvent`; the run controller (WS-C) wraps them in §8.3 envelopes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from app.agents.actor import Actor, TurnInput, TurnOutcome
from app.agents.contracts import (
    AGENT_IDS,
    TargetRevision,
    Acceptance,
    AgentId,
    AgentMessage,
    Assignment,
    AssignmentDraft,
    Commit,
    EscalationPackage,
    Evaluation,
    Plan,
    TargetCheck,
    TurnMessage,
)
from app.agents.prompt import InboxItem, OpenPlan
from app.agents.sim_stub import BeliefView, SimService
from app.negotiation.hash import plan_hash, short
from app.negotiation.normalize import NormalizeError, normalize

DropReason = Literal["LATE", "DUPLICATE", "STALE", "INVALID_REFERENCE", "UNKNOWN_EVIDENCE", "NO_CHANGE",
                     "INVALID_PLAN", "NOT_ALLOWED"]
OPEN_PLAN_STATES = {"PROPOSED", "EVALUATED", "CHALLENGED", "PARTIALLY_ACCEPTED", "UNANIMOUS"}


@dataclass
class RouterSettings:
    rounds: int = 4                 # §6.4: 1 opening + 3 negotiation rounds
    turn_deadline_s: float = 8.0
    dp_budget_s: float = 30.0
    dp_max_calls: int = 48          # §6.4, §10.2, NFR-004: model calls per decision point, all actors together
    dp_max_tokens: int = 120_000    # §6.4, §10.2: input + output tokens per decision point


@dataclass
class RouterEvent:
    type: str
    data: dict[str, Any]
    dp_id: str
    round: int
    state_version: int
    agent: str | None = None


Sink = Callable[[RouterEvent], None]


@dataclass
class PlanRecord:
    plan: Plan
    assignments: list[Assignment]
    first_proposed_seq: int
    evaluations: dict[str, Evaluation] = field(default_factory=dict)   # basis -> evaluation (view_X, authoritative)

    @property
    def hash(self) -> str:
        return self.plan.plan_hash

    @property
    def drafts(self) -> list[AssignmentDraft]:
        return [AssignmentDraft.model_validate(a.model_dump(include=set(AssignmentDraft.model_fields)))
                for a in self.assignments]


@dataclass
class DecisionPointRecord:
    dp_id: str
    state_version: int
    run_id: str
    scenario_id: str
    locked: list[Assignment] = field(default_factory=list)
    round: int = 0
    seq: int = 0
    plans: dict[str, PlanRecord] = field(default_factory=dict)          # plan_hash -> record
    plan_ids: dict[str, str] = field(default_factory=dict)              # plan_id -> plan_hash
    messages: list[AgentMessage] = field(default_factory=list)          # delivered and dropped
    seen_message_ids: set[str] = field(default_factory=set)
    acceptances: list[Acceptance] = field(default_factory=list)
    escalate_votes: dict[int, set[AgentId]] = field(default_factory=dict)
    disclosures: list[dict[str, Any]] = field(default_factory=list)
    pending_inbox: dict[AgentId, list[InboxItem]] = field(default_factory=lambda: {a: [] for a in AGENT_IDS})
    turn_status: dict[int, dict[AgentId, str]] = field(default_factory=dict)
    degraded_agents: set[AgentId] = field(default_factory=set)
    budget_exceeded: bool = False
    model_calls: int = 0                                  # aggregate over all actors (§10.2)
    tokens: int = 0
    cancelled: bool = False
    cancel_reason: str | None = None
    started_monotonic: float = 0.0
    # Filled by the commit gate / escalation (B4). The router only carries them.
    notices: dict[AgentId, list[str]] = field(default_factory=lambda: {a: [] for a in AGENT_IDS})
    outcome: Literal["committed", "escalated", "stale", "cancelled"] | None = None
    commit: Commit | None = None
    escalation: EscalationPackage | None = None
    rejections: list[dict[str, Any]] = field(default_factory=list)      # {plan_id, plan_hash, violations}
    fallback_assignments: list[Assignment] = field(default_factory=list)
    fallback_hash: str | None = None

    def live_acceptances(self, plan_hash: str) -> list[Acceptance]:
        return [a for a in self.acceptances if a.plan_hash == plan_hash and not a.revoked
                and a.dp_id == self.dp_id and a.state_version == self.state_version]

    def open_plans(self) -> list[PlanRecord]:
        return [p for p in self.plans.values() if p.plan.state in OPEN_PLAN_STATES]


class Router:
    def __init__(self, actors: dict[AgentId, Actor], sim: SimService, *, run_id: str, scenario_id: str,
                 sink: Sink | None = None, settings: RouterSettings | None = None):
        if set(actors) != set(AGENT_IDS):
            raise ValueError(f"exactly three actors required (invariant 1), got {sorted(actors)}")
        self.actors = actors
        # One public target table per negotiation, shared by the three actors (§6.1: targets are public). Copied so a
        # revision (§6.11) never leaks into module defaults or another run.
        public = {a: list(ts) for a, ts in next(iter(actors.values())).state.targets.items()}
        for actor in actors.values():
            actor.state.targets = public
        self.sim = sim
        self.run_id = run_id
        self.scenario_id = scenario_id
        self.sink = sink or (lambda event: None)
        self.settings = settings or RouterSettings()
        self.current: DecisionPointRecord | None = None
        self._round_task: asyncio.Future | None = None
        self._max_calls_per_turn = {a: actor.max_model_calls for a, actor in actors.items()}   # per-turn caps (§6.4)

    # --- decision point ---------------------------------------------------------------------------------------------

    async def run_decision_point(self, dp_id: str, state_version: int, *, locked: list[Assignment] | None = None,
                                 on_round_end: Callable[[DecisionPointRecord], str | None] | None = None
                                 ) -> DecisionPointRecord:
        rec = DecisionPointRecord(dp_id=dp_id, state_version=state_version, run_id=self.run_id,
                                  scenario_id=self.scenario_id, locked=list(locked or []),
                                  started_monotonic=time.monotonic())
        self.current = rec
        self._emit(rec, "negotiation.started", {"dp_id": dp_id, "state_version": state_version})
        for round_ in range(1, self.settings.rounds + 1):
            if rec.cancelled:
                break
            time_left = self.settings.dp_budget_s - (time.monotonic() - rec.started_monotonic)
            calls_left = self.settings.dp_max_calls - rec.model_calls
            if time_left <= 0 or calls_left < len(AGENT_IDS) or rec.tokens >= self.settings.dp_max_tokens:
                rec.budget_exceeded = True          # §6.9 trigger 2, decided by B4's on_round_end / escalation
                break
            # Share what is left of the aggregate call budget so one round can never overrun it (§10.2).
            for a in AGENT_IDS:
                self.actors[a].max_model_calls = min(self._max_calls_per_turn[a], calls_left // len(AGENT_IDS))
            rec.round = round_
            self._emit(rec, "negotiation.round", {"dp_id": dp_id, "round": round_})
            outcomes = await self._run_round(rec, round_, time_left)
            if rec.cancelled:
                break
            self.deliver(rec, round_, outcomes)
            if on_round_end is not None and on_round_end(rec) == "stop":
                break
        return rec

    def cancel(self, reason: str) -> None:
        """Event injected, reset or budget exceeded (§6.10): cancel in-flight turns; their outputs are discarded."""
        rec = self.current
        if rec is None or rec.cancelled:
            return
        rec.cancelled, rec.cancel_reason = True, reason
        if self._round_task is not None and not self._round_task.done():
            self._round_task.cancel()
        self._emit(rec, "negotiation.cancelled", {"dp_id": rec.dp_id, "round": rec.round, "reason": reason})

    async def _run_round(self, rec: DecisionPointRecord, round_: int, time_left: float) -> dict[AgentId, TurnOutcome]:
        inputs = {
            a: TurnInput(view=self.sim.build_belief_view(a), round=round_, dp_id=rec.dp_id, run_id=rec.run_id,
                         inbox=rec.pending_inbox.get(a, []), open_plans=self._open_plans_for(rec, a),
                         time_left_s=time_left, deadline_s=min(self.settings.turn_deadline_s, time_left),
                         locked_assignments=rec.locked, notices=list(rec.notices.get(a, [])),
                         history=self.history_for(a))
            for a in AGENT_IDS
        }
        rec.pending_inbox = {a: [] for a in AGENT_IDS}
        rec.notices = {a: [] for a in AGENT_IDS}
        self._round_task = asyncio.gather(*(self.actors[a].run_turn(inputs[a]) for a in AGENT_IDS),
                                          return_exceptions=True)
        try:
            results = await self._round_task
        except asyncio.CancelledError:
            if not rec.cancelled:            # cancelled from outside the router (e.g. task teardown)
                rec.cancelled, rec.cancel_reason = True, "task cancelled"
            return {}
        finally:
            self._round_task = None

        outcomes: dict[AgentId, TurnOutcome] = {}
        statuses: dict[AgentId, str] = {}
        for a, result in zip(AGENT_IDS, results):
            if isinstance(result, TurnOutcome):
                outcomes[a] = result
            elif isinstance(result, asyncio.CancelledError):
                outcomes[a] = self.actors[a].last_outcome or TurnOutcome(agent_id=a, status="cancelled")
            elif isinstance(result, BaseException):
                outcomes[a] = TurnOutcome(agent_id=a, status="failed", errors=[f"actor raised {result!r}"])
            statuses[a] = outcomes[a].status
            rec.model_calls += outcomes[a].model_calls
            rec.tokens += sum((r.tokens_in or 0) + (r.tokens_out or 0) for r in outcomes[a].call_rows)
            # The second consecutive failure degrades the actor in this very turn (§6.3); escalate now, not a round late.
            if outcomes[a].status == "degraded" or self.actors[a].state.degraded:
                rec.degraded_agents.add(a)
            self._emit(rec, "agent.turn", {"agent": a, "status": outcomes[a].status,
                                           "model_calls": outcomes[a].model_calls,
                                           "latency_ms": outcomes[a].latency_ms}, agent=a)
            for row in outcomes[a].tool_rows:
                self._emit(rec, "tool.called", {"agent": a, "tool": row.tool, "args_summary": row.args_summary,
                                                "result_summary": row.result_summary,
                                                "evaluation_id": row.evaluation_id}, agent=a)
        rec.turn_status[round_] = statuses
        return outcomes

    # --- delivery (round boundary) --------------------------------------------------------------------------------

    def deliver(self, rec: DecisionPointRecord, round_: int, outcomes: dict[AgentId, TurnOutcome],
                *, current_state_version: int | None = None) -> None:
        """Canonical-order delivery. Pure apart from simulator calls, so tests can drive it directly."""
        if rec.cancelled:
            return
        stale = current_state_version is not None and current_state_version != rec.state_version
        for agent in AGENT_IDS:
            out = outcomes.get(agent)
            if out is None or out.status != "submitted" or out.turn is None:
                continue
            for index, tm in enumerate(out.turn.messages):
                message_id = f"{rec.dp_id}:r{round_}:{agent}:{index}"
                self._deliver_one(rec, round_, agent, tm, message_id, stale=stale)
            if out.turn.target_revision is not None and not stale:
                self.publish_revision(agent, out.turn.target_revision)
                self._emit(rec, "target.revised", out.turn.target_revision.model_dump(mode="json"), agent=agent)
        self._update_plan_states(rec)

    def _deliver_one(self, rec: DecisionPointRecord, round_: int, sender: AgentId, tm: TurnMessage,
                     message_id: str, *, stale: bool) -> None:
        rec.seq += 1
        view = self.sim.build_belief_view(sender)
        recipients: list[AgentId] = list(tm.recipients) or [a for a in AGENT_IDS if a != sender]
        env = self._envelope(rec, round_, sender, tm, message_id, view.step)

        def drop(reason: DropReason, *, notify_sender: bool = False) -> None:
            dropped = env.model_copy(update={"status": "dropped", "drop_reason": reason})
            rec.messages.append(dropped)
            self._emit(rec, "message.dropped", dropped.model_dump(mode="json"), agent=sender)
            if notify_sender:   # §6.10: notice in the actor's next inbox — its own message, marked dropped
                rec.pending_inbox[sender].append(InboxItem(message=dropped, evaluation=None))

        if message_id in rec.seen_message_ids:
            return drop("DUPLICATE")
        rec.seen_message_ids.add(message_id)
        if stale:
            return drop("STALE")
        held = {e.evidence_id for e in view.held_evidence}
        cited = [*tm.evidence_ids, *tm.shared_evidence_ids]
        if any(e not in held for e in cited):
            return drop("UNKNOWN_EVIDENCE")
        if round_ < 2 and tm.message_type in ("COUNTERPROPOSE", "CHALLENGE", "ACCEPT", "WITHDRAW", "ESCALATE"):
            return drop("NOT_ALLOWED")

        evaluations: dict[AgentId, Evaluation] = {}
        disclosed = False

        def disclose_cited() -> None:
            """Citing is sharing (§4.3). Runs only once the message is certain to be delivered, and before any
            delivery-time evaluation, so each recipient's own-view evaluation already reflects the cited evidence."""
            nonlocal disclosed
            if disclosed:
                return
            disclosed = True
            for eid in dict.fromkeys(cited):
                for r in recipients:
                    self.sim.disclose(eid, r)
                disclosure = {"evidence_id": eid, "from": sender, "to": recipients, "via_message_id": message_id}
                rec.disclosures.append(disclosure)
                self._emit(rec, "evidence.disclosed", disclosure, agent=sender)

        t = tm.message_type
        if t in ("PROPOSE", "COUNTERPROPOSE"):
            parent_hash: str | None = None
            if t == "COUNTERPROPOSE":
                parent_hash = rec.plan_ids.get(tm.parent_plan_id or "")
                if parent_hash is None:
                    return drop("INVALID_REFERENCE", notify_sender=True)
            try:
                assignments = normalize(tm.plan or [], view=view, sim=self.sim, locked=rec.locked)
            except NormalizeError as e:
                self._emit(rec, "plan.bounced", {"agent": sender, "violations": [{"code": "INVALID_PLAN", "detail": str(e)}]},
                           agent=sender)
                return drop("INVALID_PLAN", notify_sender=True)
            drafts = _drafts(assignments)
            violations = self.sim.validate_plan(view, drafts)
            if violations:   # safety net: the actor already bounced this inside its turn (§6.4)
                self._emit(rec, "plan.bounced", {"agent": sender, "violations": [v.model_dump(mode="json") for v in violations]},
                           agent=sender)
                return drop("INVALID_PLAN", notify_sender=True)
            h = plan_hash(rec.run_id, rec.scenario_id, rec.state_version, assignments)
            if parent_hash is not None and h == parent_hash:
                return drop("NO_CHANGE", notify_sender=True)   # FR-025 / AC-004
            record = rec.plans.get(h)
            if record is None:
                plan_id = f"{rec.dp_id}:P{len(rec.plans) + 1}"
                plan = Plan(plan_id=plan_id, plan_hash=h, proposer=sender, parent_plan_id=tm.parent_plan_id,
                            run_id=rec.run_id, dp_id=rec.dp_id, state_version=rec.state_version,
                            assignments=assignments, evidence_ids=list(tm.evidence_ids), state="PROPOSED",
                            evaluation_ids=[], tradeoffs=[], expected_shelter_use=_shelter_use(assignments))
                record = PlanRecord(plan=plan, assignments=assignments, first_proposed_seq=rec.seq)
                rec.plans[h] = record
                rec.plan_ids[plan_id] = h
                self._emit(rec, "plan.proposed", plan.model_dump(mode="json"), agent=sender)
            env = env.model_copy(update={"proposal_id": record.plan.plan_id, "plan_hash": h})
            rec.acceptances.append(Acceptance(agent_id=sender, plan_hash=h, dp_id=rec.dp_id,
                                              state_version=rec.state_version, via=t, message_id=message_id,
                                              round=round_, revoked=False))
            # Delivery-time services (FR-024, D-06): one own-view evaluation per recipient, authoritative for the UI.
            disclose_cited()
            for r in recipients:
                ev = self.sim.evaluate_plan(self.sim.build_belief_view(r), drafts, plan_hash=h)
                record.evaluations[ev.basis] = ev
                evaluations[r] = ev
                self._emit(rec, "evaluation.created", _eval_summary(ev), agent=r)
            if "authoritative" not in record.evaluations:
                auth = self.sim.evaluate_plan(self.sim.build_belief_view("authoritative"), drafts, plan_hash=h)
                record.evaluations["authoritative"] = auth
                record.plan.evaluation_ids.append(auth.evaluation_id)
                self._emit(rec, "evaluation.created", _eval_summary(auth))
            if record.plan.state == "PROPOSED":
                self._set_state(rec, record, "EVALUATED")
        elif t == "CHALLENGE":
            h = rec.plan_ids.get(tm.target_plan_id or "")
            if h is None:
                return drop("INVALID_REFERENCE", notify_sender=True)
            env = env.model_copy(update={"target_plan_hash": h})
            if rec.plans[h].plan.state in ("EVALUATED", "PARTIALLY_ACCEPTED"):
                self._set_state(rec, rec.plans[h], "CHALLENGED")
        elif t in ("ACCEPT", "WITHDRAW"):
            h = self._resolve_hash(rec, tm.target_plan_hash)
            if h is None or rec.plans[h].plan.state not in OPEN_PLAN_STATES:
                return drop("INVALID_REFERENCE", notify_sender=True)
            env = env.model_copy(update={"target_plan_hash": h})
            if t == "ACCEPT":
                rec.acceptances.append(Acceptance(agent_id=sender, plan_hash=h, dp_id=rec.dp_id,
                                                  state_version=rec.state_version, via="ACCEPT",
                                                  message_id=message_id, round=round_, revoked=False))
            else:
                for a in rec.acceptances:
                    if a.agent_id == sender and a.plan_hash == h:
                        a.revoked = True
                if rec.plans[h].plan.proposer == sender:          # §6.6: proposer withdraws → plan WITHDRAWN
                    for a in rec.acceptances:
                        if a.plan_hash == h:
                            a.revoked = True
                    self._set_state(rec, rec.plans[h], "WITHDRAWN")
        elif t == "ESCALATE":
            rec.escalate_votes.setdefault(round_, set()).add(sender)
        # REQUEST_EVIDENCE and SHARE_EVIDENCE need no bookkeeping beyond disclosure and delivery.

        disclose_cited()
        rec.messages.append(env)
        self.actors[sender].state.sent_message_ids.append(message_id)
        for r in recipients:
            rec.pending_inbox[r].append(InboxItem(message=env, evaluation=evaluations.get(r)))
        self._emit(rec, "message.delivered", env.model_dump(mode="json"), agent=sender)

    # --- bookkeeping helpers -------------------------------------------------------------------------------------

    def publish_revision(self, owner: AgentId, revision: TargetRevision) -> None:
        """§6.11: a revision is public. The owner's aspiration changes, every actor's public target table shows the new
        value (so peers know what would make the owner accept), and the simulator's target checks use it."""
        self.actors[owner].state.apply_revision(revision)
        tables = {id(a.state.targets): a.state.targets for a in self.actors.values()}
        for table in tables.values():
            table[owner] = [t.model_copy(update={"aspiration": revision.new_aspiration}) if t.metric == revision.metric
                            else t for t in table.get(owner, [])]
        setter = getattr(self.sim, "set_target_aspiration", None)
        if setter is not None:
            setter(owner, revision.metric, revision.new_aspiration)

    def mark_stale(self, rec: DecisionPointRecord) -> None:
        """FR-040 / invariant 6: a state_version change voids every acceptance and stales every open plan."""
        for a in rec.acceptances:
            if a.state_version == rec.state_version:
                a.revoked = True
        for record in rec.open_plans():
            self._set_state(rec, record, "STALE")
        if rec.outcome is None:
            rec.outcome = "stale"

    def history_for(self, agent: AgentId) -> Callable[[int | None], list[dict[str, Any]]]:
        """§6.2 `get_negotiation_history`: only messages this agent sent or received."""

        def history(rounds: int | None) -> list[dict[str, Any]]:
            rec = self.current
            if rec is None:
                return []
            visible = [m for m in rec.messages if m.status == "delivered"
                       and (m.sender == agent or agent in (m.recipients or [a for a in AGENT_IDS if a != m.sender]))]
            if rounds is not None:
                visible = [m for m in visible if m.round > rec.round - rounds]
            return [{"message_id": m.message_id, "round": m.round, "sender": m.sender, "type": m.message_type,
                     "proposal_id": m.proposal_id, "plan_hash": short(m.plan_hash) if m.plan_hash else None,
                     "target_plan_id": m.target_plan_id, "rationale": m.rationale} for m in visible]
        return history

    def _open_plans_for(self, rec: DecisionPointRecord, agent: AgentId) -> list[OpenPlan]:
        plans: list[OpenPlan] = []
        for record in sorted(rec.open_plans(), key=lambda p: p.first_proposed_seq):
            own = record.evaluations.get(f"view_{agent}")
            checks: list[TargetCheck] = [c for c in own.target_checks if c.agent_id == agent] if own else []
            plans.append(OpenPlan(plan_id=record.plan.plan_id, plan_hash=record.hash, proposer=record.plan.proposer,
                                  state=record.plan.state, my_check=checks))
        return plans

    def _resolve_hash(self, rec: DecisionPointRecord, h: str | None) -> str | None:
        if not h:
            return None
        if h in rec.plans:
            return h
        matches = [full for full in rec.plans if full.startswith(h)]
        return matches[0] if len(matches) == 1 else None

    def _update_plan_states(self, rec: DecisionPointRecord) -> None:
        """Acceptance counting only (§6.6). The gate (B4) decides COMMITTED / REJECTED_AT_COMMIT."""
        for record in rec.open_plans():
            agents = {a.agent_id for a in rec.live_acceptances(record.hash)}
            if len(agents) >= 3 and record.plan.state != "UNANIMOUS":
                self._set_state(rec, record, "UNANIMOUS")
            elif len(agents) == 2 and record.plan.state in ("EVALUATED", "CHALLENGED"):
                self._set_state(rec, record, "PARTIALLY_ACCEPTED")

    def _set_state(self, rec: DecisionPointRecord, record: PlanRecord, state: str) -> None:
        record.plan.state = state  # type: ignore[assignment]
        self._emit(rec, "plan.state", {"plan_id": record.plan.plan_id, "plan_hash": record.hash, "state": state})

    def _envelope(self, rec: DecisionPointRecord, round_: int, sender: AgentId, tm: TurnMessage, message_id: str,
                  step: int) -> AgentMessage:
        return AgentMessage(**tm.model_dump(), message_id=message_id, sender=sender, run_id=rec.run_id,
                            scenario_id=rec.scenario_id, dp_id=rec.dp_id, state_version=rec.state_version,
                            round=round_, ts=_now_iso_ms(), step=step, proposal_id=None, plan_hash=None,
                            status="delivered", drop_reason=None)

    def _emit(self, rec: DecisionPointRecord, type_: str, data: dict[str, Any], *, agent: str | None = None) -> None:
        self.sink(RouterEvent(type=type_, data=data, dp_id=rec.dp_id, round=rec.round,
                              state_version=rec.state_version, agent=agent))


def _drafts(assignments: list[Assignment]) -> list[AssignmentDraft]:
    keep = set(AssignmentDraft.model_fields)
    return [AssignmentDraft.model_validate({k: v for k, v in a.model_dump().items() if k in keep}) for a in assignments]


def _shelter_use(assignments: list[Assignment]) -> dict[str, int]:
    use: dict[str, int] = {}
    aboard: dict[str, int] = {}
    for a in assignments:
        if a.task == "load" and a.people_count:
            aboard[a.resource_id] = aboard.get(a.resource_id, 0) + a.people_count
        elif a.task == "unload" and a.shelter_id:
            use[a.shelter_id] = use.get(a.shelter_id, 0) + aboard.pop(a.resource_id, 0)
    return use


def _eval_summary(ev: Evaluation) -> dict[str, Any]:
    """§8.3 `evaluation.created` carries the Evaluation without the full trace (leg timing stays)."""
    return ev.model_dump(mode="json", exclude={"trace_ref"})


def _now_iso_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
