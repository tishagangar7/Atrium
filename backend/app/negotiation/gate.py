"""Commit gate (PRD §6.8; FR-030, FR-032, FR-033; invariants 1, 2, 4).

    at each round boundary, holding the run lock:
      live = acceptances where dp_id == current_dp and state_version == current_version (and not revoked)
      unanimous = { h : the three agents each have a live ACCEPT (or auto-accept) of h }
      order unanimous by the router seq of each plan's first PROPOSE/COUNTERPROPOSE (ascending)
      for h in that order:
          validate_plan(plan[h], authoritative_world)
          valid   -> assert world.state_version == current_version; apply_accepted_plan(h); COMMITTED
          invalid -> REJECTED_AT_COMMIT; void its acceptances; broadcast violations
      otherwise continue to the next round (or escalate if none left)

The gate applies a fixed ordering rule, never a quality judgment: it does not read metrics, and
`first_proposed_seq` is the only sort key. Silence, timeouts and malformed output never produced an `Acceptance`
in the first place (router + actor), so they cannot count here. `apply` is the WS-C hook that mutates the
authoritative world under the run lock (default: `sim.apply_accepted_plan`, §6.2).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from app.agents.contracts import AGENT_IDS, Acceptance, Assignment, Commit
from app.agents.sim_stub import SimService
from app.negotiation.hash import short
from app.negotiation.router import DecisionPointRecord, PlanRecord

Apply = Callable[[list[Assignment], str], int]           # (assignments, plan_hash) -> new state_version
Emit = Callable[[str, dict[str, Any]], None]              # (event type, data)
ORDERING_RULE = "first_proposed_seq"


class StaleDecisionPoint(Exception):
    """The authoritative state_version moved under the decision point (§6.8 atomic version check failed)."""


@dataclass
class GateResult:
    outcome: Literal["committed", "continue"]
    commit: Commit | None = None
    rejected: list[str] = field(default_factory=list)     # plan hashes rejected at commit this round


class CommitGate:
    def __init__(self, sim: SimService, *, apply: Apply | None = None):
        self.sim = sim
        self.apply: Apply = apply or sim.apply_accepted_plan

    def check(self, rec: DecisionPointRecord, *, emit: Emit) -> GateResult:
        authoritative = self.sim.build_belief_view("authoritative")
        unanimous = [record for record in rec.open_plans()
                     if len({a.agent_id for a in rec.live_acceptances(record.hash)}) >= len(AGENT_IDS)]
        unanimous.sort(key=lambda record: record.first_proposed_seq)   # the only ordering rule (§6.8)
        rejected: list[str] = []

        for record in unanimous:
            violations = self.sim.validate_plan(authoritative, record.drafts)
            if not violations:
                if authoritative.world["state_version"] != rec.state_version:
                    raise StaleDecisionPoint(
                        f"world is at state_version {authoritative.world['state_version']}, decision point at {rec.state_version}")
                commit = self.commit(rec, record, authority="unanimous",
                                     acceptances=_one_per_agent(rec.live_acceptances(record.hash)), emit=emit)
                return GateResult(outcome="committed", commit=commit, rejected=rejected)

            # REJECTED_AT_COMMIT: a physical fact discovered by trying to act — published to all agents (§4.3).
            record.plan.state = "REJECTED_AT_COMMIT"
            emit("plan.state", {"plan_id": record.plan.plan_id, "plan_hash": record.hash, "state": "REJECTED_AT_COMMIT"})
            for a in rec.acceptances:
                if a.plan_hash == record.hash:
                    a.revoked = True
            codes = sorted({v.code for v in violations})
            rec.rejections.append({"plan_id": record.plan.plan_id, "plan_hash": record.hash,
                                   "violations": [v.model_dump(mode="json") for v in violations]})
            notice = (f"Plan {record.plan.plan_id} ({short(record.hash)}) was accepted by all three agents but failed "
                      f"authoritative validation: {', '.join(codes)}. Its acceptances are void; propose or accept another plan.")
            for agent in AGENT_IDS:
                rec.notices[agent].append(notice)
            emit("evidence.disclosed", {"evidence_id": f"COMMIT_REJECTION:{record.plan.plan_id}", "from": "simulator",
                                        "to": list(AGENT_IDS), "via_message_id": None, "via": "commit_rejection",
                                        "violations": [v.model_dump(mode="json") for v in violations]})
            rejected.append(record.hash)
        return GateResult(outcome="continue", rejected=rejected)

    def commit(self, rec: DecisionPointRecord, record: PlanRecord, *, authority: Literal["unanimous", "human_choice"],
               acceptances: list[Acceptance], emit: Emit) -> Commit:
        """Apply a plan that passed authoritative validation and record the Commit (§7.7)."""
        before = rec.state_version
        after = self.apply(record.assignments, record.hash)
        auth_eval = record.evaluations.get("authoritative")
        commit = Commit(run_id=rec.run_id, dp_id=rec.dp_id, plan_hash=record.hash, plan_id=record.plan.plan_id,
                        state_version_before=before, state_version_after=after, acceptances=acceptances,
                        ordering_rule=ORDERING_RULE, authority=authority,
                        authoritative_evaluation_id=auth_eval.evaluation_id if auth_eval else "",
                        ts=_now_iso_ms(), step=self.sim.build_belief_view("authoritative").step)
        record.plan.state = "COMMITTED"
        rec.commit, rec.outcome = commit, "committed"
        emit("plan.state", {"plan_id": record.plan.plan_id, "plan_hash": record.hash, "state": "COMMITTED"})
        emit("plan.committed", commit.model_dump(mode="json"))
        return commit


def _one_per_agent(acceptances: list[Acceptance]) -> list[Acceptance]:
    """Exactly three acceptance records in canonical agent order (an agent may have both PROPOSE and ACCEPT)."""
    chosen: dict[str, Acceptance] = {}
    for a in acceptances:
        chosen.setdefault(a.agent_id, a)
    return [chosen[a] for a in AGENT_IDS if a in chosen]


def _now_iso_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
