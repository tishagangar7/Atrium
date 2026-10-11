"""Real benchmark methods (PRD §11.2, §11.3; queue C6). One paired run = one preset, seed and method on the same
authoritative simulator, with decision points at step 0 and after every scheduled event (§11.2 common conditions).

- `fixed_rule` needs no model and always runs.
- `single_agent` and `rescuemesh` need a configured live provider (`backend/.env`). Without one they are reported as
  skipped — never a stub row (Tisha's C6 note; AGENTS.md invariant 9: no results without real runs). The scripted
  TEST PROVIDER is refused here: a benchmark over canned turns would be a fake result.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import models as m
from .. import run
from ..agents.provider import ProviderError, Settings, get_provider
from ..baselines.fixed_rule import FixedRulePlanner
from ..negotiation.hash import plan_hash
from ..sim.service import SimulatorService

Emit = Callable[[str, dict[str, Any]], None]
MODEL_METHODS = ("single_agent", "rescuemesh")


class MethodUnavailable(Exception):
    """The method cannot run honestly in this environment (e.g. no live model provider)."""


@dataclass
class Outcome:
    metrics: m.Metrics
    decision_points: int = 0
    commits: int = 0
    escalations: int = 0
    adaptation_wall_ms: list[int] = field(default_factory=list)
    model_calls: int = 0
    tokens_in: int | None = None
    tokens_out: int | None = None
    model: str | None = None
    invalid_attempted: int = 0
    inappropriate_consensus: int = 0
    justified_escalations: int = 0
    final_state_hash: str | None = None
    notes: str = ""


def _snapshot(sim: SimulatorService, run_id: str, emit: Emit, *,
              dp_id: str | None = None, status: str = "idle") -> None:
    snapshot = m.Snapshot(
        run_id=run_id, mode="benchmark", last_seq=0, world=sim.world,
        evidence_holders=sim.evidence_holders(), dp_id=dp_id,
        negotiation_status=status, committed_plan=None, escalation=None,
        label="Synthetic simulation",
    )
    emit("state.snapshot", snapshot.model_dump(mode="json"))


def _meets_all_floors(checks: list[m.TargetCheck]) -> bool:
    return bool(checks) and all(check.meets_floor for check in checks)


def _record_consensus_quality(result: Any, out: Outcome) -> None:
    """PRD §11.1: compare the committed forecast with other valid plans in the same DP."""
    forecasts = {
        plan_hash: record.evaluations.get("authoritative")
        for plan_hash, record in result.record.plans.items()
    }
    feasible = {
        plan_hash: evaluation for plan_hash, evaluation in forecasts.items()
        if evaluation is not None and evaluation.valid
    }
    if getattr(result, "escalation", None) is not None or result.status == "escalated":
        if not any(_meets_all_floors(evaluation.target_checks) for evaluation in feasible.values()):
            out.justified_escalations += 1
    elif result.status == "committed" and result.commit is not None:
        chosen = feasible.get(result.commit.plan_hash)
        if (chosen is not None and not _meets_all_floors(chosen.target_checks)
                and any(_meets_all_floors(other.target_checks)
                        for plan_hash, other in feasible.items()
                        if plan_hash != result.commit.plan_hash)):
            out.inappropriate_consensus += 1


def live_provider():
    """The configured live provider, or `MethodUnavailable` (no key, no model, or only the TEST PROVIDER)."""
    try:
        settings = Settings.from_env()
    except ProviderError as e:
        raise MethodUnavailable(str(e)) from e
    if settings.provider == "fake":
        raise MethodUnavailable("only the TEST PROVIDER is configured; benchmarks need a live model")
    try:
        return get_provider(settings), settings
    except ProviderError as e:
        raise MethodUnavailable(str(e)) from e


def _timed(sim: SimulatorService, drafts: list[m.AssignmentDraft]) -> list[m.Assignment]:
    view = sim.build_belief_view("authoritative")
    timing = sim.plan_timing(view, drafts)
    return [m.Assignment(**d.model_dump() | {"order": i, "locked": bool(getattr(d, "locked", False)),
                                             "start_step": t["start_step"], "end_step": t["end_step"],
                                             "wait_steps": t["wait_steps"]})
            for i, (d, t) in enumerate(zip(drafts, timing))]


def _advance(sim: SimulatorService, emit: Emit) -> None:
    """Execute until the next scheduled-event pause or the horizon (§5.7, §5.8)."""
    horizon = sim.scenario.horizon
    version = sim.world.state_version
    while sim.world.step < horizon and sim.world.state_version == version:
        before = sim.world.step
        sim.step(horizon - sim.world.step)
        emit("state.step", {"step": sim.world.step, "changes": sim.last_changes[-20:]})
        _snapshot(sim, sim.world.run_id, emit)
        if sim.world.step == before and sim.world.state_version == version:
            break                                                    # nothing left to execute


def run_fixed_rule(preset: str, seed: int, run_id: str, emit: Emit) -> Outcome:
    sim = SimulatorService(preset, seed, run_id)
    _snapshot(sim, run_id, emit)
    planner = FixedRulePlanner(sim)
    out = Outcome(metrics=sim.realized_metrics(), notes="fixed_rule: deterministic §11.2 policy, no model calls")
    event_seen_at: float | None = None
    while sim.world.step < sim.scenario.horizon:
        version = sim.world.state_version
        out.decision_points += 1
        drafts = planner.plan(sim.build_belief_view("union"), locked=sim.locked_legs())
        violations = sim.validate_plan(sim.build_belief_view("authoritative"), drafts)
        if violations:                                               # §11.1 invalid_attempted; hold instead
            out.invalid_attempted += 1
            drafts = list(sim.locked_legs())
        assignments = _timed(sim, drafts)
        sim.apply_accepted_plan(assignments, plan_hash(run_id, preset, version, assignments))
        out.commits += 1
        emit("plan.committed", {"dp_id": f"dp-{out.decision_points}", "method": "fixed_rule",
                                "assignments": len(assignments), "state_version_before": version})
        _snapshot(sim, run_id, emit, dp_id=f"dp-{out.decision_points}", status="committed")
        if event_seen_at is not None:
            out.adaptation_wall_ms.append(int((time.monotonic() - event_seen_at) * 1000))
            event_seen_at = None
        after = sim.world.state_version
        _advance(sim, emit)
        if sim.world.state_version != after and sim.world.step < sim.scenario.horizon:
            event_seen_at = time.monotonic()                         # an event paused the run: new decision point
        elif sim.world.state_version == after:
            break
    out.metrics = sim.realized_metrics()
    out.metrics = out.metrics.model_copy(update={
        "invalid_attempted": out.metrics.invalid_attempted + out.invalid_attempted,
    })
    out.final_state_hash = run._state_hash(sim.world)
    return out


async def run_model_method(method: str, preset: str, seed: int, run_id: str, emit: Emit,
                           budget: dict[str, Any]) -> Outcome:
    """`single_agent` / `rescuemesh` against a live provider. Raises `MethodUnavailable` if none is configured."""
    provider, settings = live_provider()
    from ..agents.actor import Actor, ActorState
    from ..baselines.single_agent import MATCHED, NATURAL, SingleAgentBaseline
    from ..negotiation.router import RouterSettings
    from ..negotiation.service import NegotiationService

    sim = SimulatorService(preset, seed, run_id)
    _snapshot(sim, run_id, emit)
    out = Outcome(metrics=sim.realized_metrics(), model=settings.model, tokens_in=0, tokens_out=0,
                  notes=f"{method}: live provider {settings.provider}/{settings.model}")
    defaults = RouterSettings()
    router_settings = RouterSettings(turn_deadline_s=settings.turn_deadline_s,
                                     dp_budget_s=getattr(settings, "dp_budget_s", defaults.dp_budget_s),
                                     dp_max_tokens=getattr(settings, "dp_max_tokens", defaults.dp_max_tokens))
    if budget.get("calls"):
        router_settings.dp_max_calls = int(budget["calls"])
    if budget.get("tokens"):
        router_settings.dp_max_tokens = int(budget["tokens"])

    async def loop() -> None:
        service = None
        baseline = None
        if method == "rescuemesh":
            actors = {a: Actor(ActorState(agent_id=a, targets=sim.scenario.targets), provider, sim)
                      for a in ("EVAC", "FIRE", "LOG")}

            def record_event(event: Any) -> None:
                if event.type == "agent.turn":
                    out.model_calls += event.data.get("model_calls", 0)
                    outcome = actors[event.data["agent"]].last_outcome
                    if outcome is not None:
                        out.tokens_in = (out.tokens_in or 0) + sum(row.tokens_in or 0 for row in outcome.call_rows)
                        out.tokens_out = (out.tokens_out or 0) + sum(row.tokens_out or 0 for row in outcome.call_rows)
                emit(event.type, event.data)

            service = NegotiationService(actors, sim, run_id=run_id, scenario_id=preset, mode="benchmark",
                                         settings=router_settings, targets=sim.scenario.targets,
                                         sink=record_event)
        else:
            baseline = SingleAgentBaseline(provider, sim, run_id=run_id, scenario_id=preset,
                                           budget=NATURAL if budget.get("natural") else MATCHED,
                                           targets=sim.scenario.targets, settings=router_settings,
                                           sink=lambda ev: emit(ev.type, ev.data))
        while sim.world.step < sim.scenario.horizon:
            version = sim.world.state_version
            out.decision_points += 1
            started = time.monotonic()
            if service is not None:
                result = await service.start_decision_point(version, locked=sim.locked_legs())
                _record_consensus_quality(result, out)
                if result.escalation is not None:
                    out.escalations += 1                             # benchmark mode resolves to F0 (D-14)
                elif result.status == "committed":
                    out.commits += 1
            else:
                decision = await baseline.decide(version, locked=sim.locked_legs())
                if decision.status == "committed":
                    out.commits += 1
                else:
                    out.escalations += 1                             # AUTO_FALLBACK, reported like an escalation (D-14)
                out.model_calls += decision.model_calls
                out.tokens_in = (out.tokens_in or 0) + decision.tokens_in
                out.tokens_out = (out.tokens_out or 0) + decision.tokens_out
                out.invalid_attempted += decision.invalid_attempted
            _snapshot(sim, run_id, emit, dp_id=f"dp-{out.decision_points}",
                      status="committed" if service is None or result.status == "committed" else "escalated")
            if out.decision_points > 1:
                out.adaptation_wall_ms.append(int((time.monotonic() - started) * 1000))
            after = sim.world.state_version
            _advance(sim, emit)
            if sim.world.state_version == after:
                break


    await loop()
    out.metrics = sim.realized_metrics()
    out.final_state_hash = run._state_hash(sim.world)
    out.metrics = out.metrics.model_copy(update={
        "invalid_attempted": out.metrics.invalid_attempted + out.invalid_attempted,
    })
    return out
