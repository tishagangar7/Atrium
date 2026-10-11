"""Backend HTTP/SSE integration (PRD §8). Calls simulator and negotiation services
through their public boundaries; physics and agent decisions remain with A/B.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from app.agents import contracts as ws_b_contracts
from app.agents.provider import ProviderError, Settings, get_provider
from app.sim.scenario import load_scenario
from app.negotiation.service import (
    NegotiationInProgress,
    NewDecisionPoint,
    NoActiveEscalation,
    PlanInfeasible,
)

from . import models as m
from . import store
from .bench.runner import AlreadyRunning, BenchmarkRunner
from .negotiation_session import INJECT_EVENT_CATALOG, NegotiationSession
from .run import (
    InvalidRequest,
    NoActiveRun,
    ReplayReadOnly,
    RunController,
    RunMismatch,
    RunNotFound,
    ScenarioNotFound,
    StateVersionMismatch,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
HELLO_STREAM_FIXTURE = FIXTURES_DIR / "hello_stream.json"
# Matches hello_stream.json's own run_id -- before any reset, the hello fixture acts as a
# virtual "run" for Last-Event-ID comparison purposes (PRD §8.4).
HELLO_FIXTURE_RUN_ID = "run-fixture-hello-s1"
MAX_EVENTS_PAGE = 500  # PRD §8.2: GET /events returns Envelope[] (max 500)


class ResetRequest(BaseModel):
    seed: int = 1
    request_id: str | None = None


class StepRequest(BaseModel):
    run_id: str
    expected_state_version: int
    steps: int | None = None
    until: Literal["next_event", "horizon"] | None = None
    request_id: str | None = None


class ReplayRequest(BaseModel):
    speed: Literal[1, 2, 4] = 1


class BenchmarkBudget(BaseModel):
    calls: int | None = None
    tokens: int | None = None


class BenchmarkRunRequest(BaseModel):
    presets: list[str] | None = None
    seeds: list[int] | None = None
    methods: list[m.Method] | None = None
    budget: BenchmarkBudget | None = None


class NegotiateRequest(BaseModel):
    run_id: str
    expected_state_version: int
    request_id: str | None = None


class NegotiateCancelRequest(BaseModel):
    run_id: str
    reason: str | None = None


class EventsInjectRequest(BaseModel):
    run_id: str
    expected_state_version: int
    event: Literal["wind_shift_road_closure", "wind_shift", "road_closure", "compound_failure"]
    auto_negotiate: bool = True
    request_id: str | None = None


class EnvironmentCommandRequest(BaseModel):
    """WS-A `EnvironmentalControls` commands (frontend/src/simulation/prd/EnvironmentalControls.tsx). Each becomes a
    public scheduled event applied now, exactly like `/events/inject` (§5.8, §8.2)."""
    run_id: str
    expected_state_version: int
    command: dict
    auto_negotiate: bool = True
    request_id: str | None = None


WIND_DIRS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _command_events(command: dict, step: int, version: int) -> list[dict]:
    """Translate one controls command into simulator events. Invariant 7: hard constraints are never waived from the
    UI — no opening a road by fiat (only a crew's clear_road reopens one) and no restoring or adding a resource."""
    kind = command.get("type")
    base = {"step": step, "public": True}
    if kind == "set_wind":
        direction, speed = command.get("direction"), command.get("speed")
        if direction not in WIND_DIRS or not isinstance(speed, int) or not 1 <= speed <= 3:
            raise ValueError("set_wind needs direction in N..NW and speed 1..3 (calm is not modelled, §5.2)")
        return [{**base, "event_id": f"control-wind-{version}", "kind": "wind_change", "target": None,
                 "value": f"{direction}:{speed}"}]
    if kind == "set_road_status":
        status = command.get("status")
        if status not in ("CLOSED_CLEARABLE", "CLOSED_HARD"):
            raise ValueError("roads can only be closed from controls; a road reopens only through clear_road")
        return [{**base, "event_id": f"control-road-{command.get('road_id')}-{version}", "kind": "road_status",
                 "target": command.get("road_id"), "value": status}]
    if kind == "set_resource_available":
        if command.get("available") is not False:
            raise ValueError("controls can take a resource out of service, never add or restore one")
        return [{**base, "event_id": f"control-resource-{command.get('resource_id')}-{version}",
                 "kind": "resource_status", "target": command.get("resource_id"), "value": "OUT_OF_SERVICE"}]
    if kind == "inject_preset" and command.get("preset") == "wind_shift_and_closure":
        events = []
        for source in ("wind_shift", "road_closure"):
            for event in load_scenario(source).events:
                events.append({**event.model_dump(mode="json"), "event_id": f"control-{source}-{version}-{len(events)}",
                               "step": step})
        return events
    raise ValueError(f"unknown controls command {kind!r}")


class EscalationResolveRequest(BaseModel):
    run_id: str
    expected_state_version: int
    choice: Literal["candidate", "fallback", "relax"]
    plan_hash: str | None = None
    target_revisions: list[m.TargetRevision] | None = None
    request_id: str | None = None


def _load_hello_fixture_envelopes() -> list[dict]:
    with HELLO_STREAM_FIXTURE.open() as f:
        return json.load(f)


def _hello_fixture_envelopes_after(last_seq: int) -> list[dict]:
    return [e for e in _load_hello_fixture_envelopes() if e["seq"] > last_seq]


def _parse_last_event_id(last_event_id: str) -> tuple[str, int]:
    """`<run_id>:<seq>` (PRD §8.4). `run_id`s never contain ':', so split on the last one."""
    run_id, _, seq_part = last_event_id.rpartition(":")
    seq = int(seq_part) if seq_part.isdigit() else 0
    return run_id, seq


def _now_iso_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _snapshot_required_envelope(active_run_id: str | None) -> dict:
    """PRD §8.3: sent on reconnect when the client's Last-Event-ID run doesn't match the
    active run -- a reset happened underneath it. Not appended to any JSONL log: it's a
    transient reconnect signal, not a fact about the world (§4.7 only logs those)."""
    return {
        "seq": 0,
        "run_id": active_run_id,
        "mode": "live",
        "type": "snapshot.required",
        "ts": _now_iso_ms(),
        "step": 0,
        "state_version": 0,
        "dp_id": None,
        "trace_id": f"{active_run_id or '-'}/-/-/-",
        "data": {"active_run_id": active_run_id},
    }


def _error_response(status_code: int, code: str, message: str, *, retryable: bool,
                     run_id: str | None = None, state_version: int | None = None) -> JSONResponse:
    error = m.ErrorObject(
        code=code, message=message, retryable=retryable,
        run_id=run_id, state_version=state_version, details={},
    )
    return JSONResponse(status_code=status_code, content={"error": error.model_dump(mode="json")})


def create_app(
    *,
    results_csv_path: Path | None = None,
    summary_json_path: Path | None = None,
    negotiation_script: dict | None = None,
    negotiation_delay_s: float = 0.0,
) -> FastAPI:
    app = FastAPI(title="RescueMesh backend", version="0.1.0")
    controller = RunController()
    bench_runner = BenchmarkRunner(
        results_csv_path or (store.RUNS_DIR / "results.csv"),
        summary_json_path or (store.RUNS_DIR / "summary.json"),
    )
    # At most one entry: cleared on every successful reset (one active run at a time, §8.1).
    # `negotiation_script`/`negotiation_delay_s` let tests inject a deterministic TEST PROVIDER
    # script/pacing; production usage passes neither, so behavior is entirely `.env`-driven
    # (RESCUEMESH_PROVIDER/_TEST).
    negotiation_sessions: dict[str, NegotiationSession] = {}
    decision_tasks: dict[str, asyncio.Task] = {}

    def _negotiation_envelope(run_id: str, envelope_type: str, data: dict) -> None:
        if run_id != controller.active_run_id or controller.mode != "live":
            return  # an old task completed after reset/replay
        if envelope_type == "negotiation.started":
            controller._dp_id = data["dp_id"]
            controller._negotiation_status = "running"
            controller._escalation = None
        elif envelope_type == "negotiation.cancelled":
            controller._negotiation_status = "cancelled"
        elif envelope_type == "escalation.opened":
            controller._negotiation_status = "escalated"
            controller._escalation = m.EscalationPackage.model_validate(data)
        elif envelope_type == "plan.committed":
            controller._negotiation_status = "committed"
            session = negotiation_sessions.get(run_id)
            record = session.service.router.current if session else None
            plan = record.plans.get(data["plan_hash"]) if record else None
            controller._committed_plan = m.Plan.model_validate(plan.plan.model_dump()) if plan else None
            controller._escalation = None
        elif envelope_type == "target.revised":
            controller.revise_target(data["metric"], data["new_aspiration"])
        controller.emit_external(run_id, envelope_type, data)
        if envelope_type in ("plan.committed", "escalation.opened", "negotiation.cancelled", "target.revised"):
            controller.publish_simulator_snapshot()

    def _get_or_create_session(run_id: str, scenario_id: str) -> NegotiationSession:
        session = negotiation_sessions.get(run_id)
        if session is None:
            session = NegotiationSession(
                run_id, scenario_id, on_envelope=_negotiation_envelope,
                simulator=controller.simulator,
                script=negotiation_script, delay_s=negotiation_delay_s,
            )
            negotiation_sessions[run_id] = session
        return session

    # Dev-only: lets Rohaan's Vite dev server (frontend/, WS-D) call this scaffold.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict:
        """Report configured provider readiness without making a billed model call."""
        try:
            settings = Settings.from_env()
            get_provider(settings)
            provider = "TEST PROVIDER" if settings.provider == "fake" else settings.provider
            available = True
        except ProviderError:
            provider, available = None, False
        return {
            "ok": True,
            "model_available": available,
            "provider": provider,
            "mode": controller.mode,
        }

    @app.post("/scenarios/{scenario_id}/reset")
    async def reset_scenario(scenario_id: str, body: ResetRequest = ResetRequest()):
        for session in negotiation_sessions.values():
            session.service.cancel("run reset")
        try:
            response = await controller.reset(scenario_id, seed=body.seed, request_id=body.request_id)
        except ScenarioNotFound as e:
            return _error_response(404, "NOT_FOUND", str(e), retryable=False)
        negotiation_sessions.clear()
        decision_tasks.clear()
        return response

    @app.get("/state")
    async def get_state():
        try:
            return controller.snapshot()
        except NoActiveRun:
            return _error_response(404, "NOT_FOUND", "no active run", retryable=False)

    @app.post("/simulation/step")
    async def simulation_step(body: StepRequest):
        session = negotiation_sessions.get(body.run_id)
        if session is not None and (session.service.in_progress or
                                    (task := decision_tasks.get(body.run_id)) is not None and not task.done()):
            return _error_response(409, "NEGOTIATION_IN_PROGRESS", "world is paused for negotiation",
                                   retryable=True, run_id=body.run_id)
        try:
            response = await controller.step(
                body.run_id, body.expected_state_version,
                steps=body.steps if body.steps is not None else 1, until=body.until, request_id=body.request_id,
            )
            if session is not None and response["state_version"] != body.expected_state_version:
                session.service.on_event_applied(response["state_version"])
                controller._negotiation_status = "idle"
                dp_id = session.service.next_dp_id()
                _schedule_decision_point(session, dp_id, response["state_version"],
                                         controller.simulator.locked_legs() if controller.simulator else None)
            return response
        except ReplayReadOnly as e:
            return _error_response(409, "REPLAY_READ_ONLY", str(e), retryable=False,
                                    run_id=body.run_id)
        except InvalidRequest as e:
            return _error_response(422, "INVALID_REQUEST", str(e), retryable=False)
        except NoActiveRun:
            return _error_response(409, "RUN_MISMATCH", "no active run", retryable=True,
                                    run_id=body.run_id)
        except RunMismatch as e:
            return _error_response(409, "RUN_MISMATCH", str(e), retryable=True,
                                    run_id=body.run_id)
        except StateVersionMismatch as e:
            return _error_response(409, "STATE_VERSION_MISMATCH", str(e), retryable=True,
                                    run_id=body.run_id, state_version=e.current)

    @app.get("/events/stream", response_class=EventSourceResponse)
    async def events_stream(request: Request) -> AsyncIterator[ServerSentEvent]:
        """SSE stream (PRD §8.3/§8.4). Streams the active run's live envelopes once one
        exists; before any reset, replays the hand-written hello fixture from C1 (labeled
        "Synthetic simulation" -- never live agent output, AGENTS.md invariant 8).

        Reconnect (§8.4): `Last-Event-ID: <run_id>:<seq>`. If `run_id` matches the
        current run (real or, pre-reset, the virtual hello-fixture run), resume after
        `seq`. If it doesn't -- a reset happened since the client last connected -- send
        one `snapshot.required` envelope and stop; the client re-fetches `GET /state` and
        reconnects from its `last_seq`. This is the server's whole job per §8.4; it does
        not resend stale envelopes.
        """
        if controller.is_active or controller.has_buffered_envelopes:
            effective_run_id = controller.active_run_id
            envelopes_after = controller.envelopes_after
        else:
            effective_run_id = HELLO_FIXTURE_RUN_ID
            envelopes_after = _hello_fixture_envelopes_after

        last_event_id = request.headers.get("last-event-id")
        if last_event_id:
            header_run_id, header_seq = _parse_last_event_id(last_event_id)
            if header_run_id != effective_run_id:
                envelope = _snapshot_required_envelope(controller.active_run_id)
                yield ServerSentEvent(event=envelope["type"], data=envelope)
                return
        else:
            header_seq = 0

        is_replay = controller.is_active and controller.mode == "replay"
        prev_ts: datetime | None = None
        for envelope in envelopes_after(header_seq):
            if is_replay and prev_ts is not None:
                # §4.7: re-emit with original relative timing, scaled by the chosen speed.
                delay = (_parse_ts(envelope["ts"]) - prev_ts).total_seconds() / controller.replay_speed
                if delay > 0:
                    await asyncio.sleep(delay)
            prev_ts = _parse_ts(envelope["ts"])
            yield ServerSentEvent(
                event=envelope["type"],
                id=f"{envelope['run_id']}:{envelope['seq']}",
                data=envelope,
            )

    @app.get("/events")
    async def get_events(run_id: str, after_seq: int = 0):
        """Polling/resume fallback (PRD §8.2, §8.4) alongside the SSE stream."""
        if not controller.is_active or run_id != controller.active_run_id:
            return _error_response(409, "RUN_MISMATCH", f"run_id {run_id!r} is not the active run",
                                    retryable=True, run_id=run_id)
        return controller.envelopes_after(after_seq)[:MAX_EVENTS_PAGE]

    @app.post("/replay/{run_id}")
    async def replay(run_id: str, body: ReplayRequest = ReplayRequest()):
        """PRD §4.7/§8.2, §13.3: replaces the active run with a labeled replay of a saved
        recording. Never calls the model or the simulator."""
        try:
            for session in negotiation_sessions.values():
                session.service.cancel("replay started")
            negotiation_sessions.clear()
            decision_tasks.clear()
            return await controller.start_replay(run_id, speed=body.speed)
        except RunNotFound as e:
            return _error_response(404, "NOT_FOUND", str(e), retryable=False)

    @app.get("/runs")
    async def list_runs():
        summaries = []
        for run_id in store.list_run_ids():
            summary = store.run_summary(run_id)
            if summary is not None:
                summaries.append(summary)
        return summaries

    @app.get("/runs/{run_id}")
    async def get_run(run_id: str):
        summary = store.run_summary(run_id)
        if summary is None:
            return _error_response(404, "NOT_FOUND", f"unknown run_id {run_id!r}", retryable=False)
        # result stays null until C6's benchmark runner populates runs/results.csv.
        return {"summary": summary, "result": None, "events_url": f"/runs/{run_id}/events"}

    @app.get("/runs/{run_id}/events")
    async def get_run_events(run_id: str):
        events = store.read_events(run_id)
        if not events:
            return _error_response(404, "NOT_FOUND", f"unknown run_id {run_id!r}", retryable=False)
        return events

    @app.post("/benchmarks/run")
    async def start_benchmark(body: BenchmarkRunRequest = BenchmarkRunRequest()):
        """PRD §8.2/§4.7/§11.3 (queue item C6). Runs headless, independent of the live
        controller's active run (§8.1)."""
        try:
            benchmark_id = await bench_runner.start(
                body.presets, body.seeds, body.methods,
                body.budget.model_dump() if body.budget else {},
                on_envelope=lambda run_id, etype, data: controller.emit_external(
                    run_id, etype, data, mode="benchmark"
                ),
            )
        except ScenarioNotFound as e:
            return _error_response(404, "NOT_FOUND", str(e), retryable=False)
        except AlreadyRunning:
            return _error_response(409, "BENCHMARK_IN_PROGRESS", "a benchmark is already running",
                                    retryable=True)
        return JSONResponse(status_code=202, content={"benchmark_id": benchmark_id})

    @app.get("/benchmarks/{benchmark_id}")
    async def get_benchmark(benchmark_id: str):
        status = bench_runner.get_status(benchmark_id)
        if status is None:
            return _error_response(404, "NOT_FOUND", f"unknown benchmark_id {benchmark_id!r}",
                                    retryable=False)
        results_csv_url = None
        if status["status"] == "done":
            path = bench_runner.results_csv_path
            try:
                results_csv_url = str(path.relative_to(store.REPO_ROOT))
            except ValueError:
                results_csv_url = str(path)
        return {
            "status": status["status"],
            "completed": status["completed"],
            "total": status["total"],
            "skipped": status.get("skipped", []),           # runs that could not run honestly (never stubbed)
            "error": status.get("error"),
            "results_csv_url": results_csv_url,
        }

    async def _run_decision_point(session: NegotiationSession, dp_id: str, state_version: int,
                                   locked: list | None = None) -> None:
        """Backgrounds `start_decision_point`, which blocks until the whole DP resolves --
        results arrive via `session`'s sink (already wired to `controller.emit_external`),
        not via this task's return value."""
        try:
            await session.service.start_decision_point(state_version, dp_id=dp_id, locked=locked)
        except Exception as e:  # service's own sink already reports round-level failures;
            controller.emit_external(session.run_id, "error", {  # this is the last-resort net.
                "code": "INTERNAL", "message": str(e), "retryable": False,
            })

    def _schedule_decision_point(session: NegotiationSession, dp_id: str, state_version: int,
                                 locked: list | None = None) -> None:
        previous = decision_tasks.get(session.run_id)

        async def run_after_previous() -> None:
            if previous is not None:
                await previous  # an injected event cancels the old round before the new one starts
            if session.run_id == controller.active_run_id and controller.mode == "live":
                await _run_decision_point(session, dp_id, state_version, locked)

        decision_tasks[session.run_id] = asyncio.create_task(run_after_previous())

    @app.post("/negotiate")
    async def negotiate(body: NegotiateRequest):
        """PRD §8.2. `NegotiationService.start_decision_point` blocks until the decision point
        resolves, so this backgrounds it and returns `202 {dp_id}` immediately, per spec."""
        if not controller.is_active:
            return _error_response(404, "NOT_FOUND", "no active run", retryable=False)
        if body.run_id != controller.active_run_id:
            return _error_response(409, "RUN_MISMATCH", f"run_id {body.run_id!r} is not the active run",
                                    retryable=True, run_id=body.run_id)
        if controller.mode == "replay":
            return _error_response(409, "REPLAY_READ_ONLY", "cannot negotiate during replay",
                                   retryable=False, run_id=body.run_id)
        current_version = controller.snapshot().world.state_version
        if body.expected_state_version != current_version:
            return _error_response(409, "STATE_VERSION_MISMATCH",
                                    f"expected_state_version {body.expected_state_version} but current is {current_version}",
                                    retryable=True, run_id=body.run_id, state_version=current_version)
        try:
            session = _get_or_create_session(body.run_id, controller.snapshot().world.scenario_id)
        except ProviderError as e:
            return _error_response(503, "MODEL_UNAVAILABLE", str(e), retryable=True)
        task = decision_tasks.get(body.run_id)
        if session.service.in_progress or (task is not None and not task.done()):
            return _error_response(409, "NEGOTIATION_IN_PROGRESS", "a decision point is already running",
                                    retryable=True, run_id=body.run_id)
        dp_id = session.service.next_dp_id()
        locked = controller.simulator.locked_legs() if controller.simulator else None
        _schedule_decision_point(session, dp_id, body.expected_state_version, locked)
        return JSONResponse(status_code=202, content={"dp_id": dp_id})

    @app.post("/negotiate/cancel")
    async def negotiate_cancel(body: NegotiateCancelRequest):
        session = negotiation_sessions.get(body.run_id)
        if session is None:
            return _error_response(404, "NOT_FOUND", "no negotiation session for this run", retryable=False)
        session.service.cancel(body.reason or "cancelled by operator")
        return {"cancelled": True}

    @app.post("/events/inject")
    async def events_inject(body: EventsInjectRequest):
        """Apply the named disruption at the current step on the authoritative world."""
        if not controller.is_active or body.run_id != controller.active_run_id:
            return _error_response(409, "RUN_MISMATCH", f"run_id {body.run_id!r} is not the active run",
                                    retryable=True, run_id=body.run_id)
        if controller.mode == "replay":
            return _error_response(409, "REPLAY_READ_ONLY", "cannot inject during replay",
                                   retryable=False, run_id=body.run_id)
        if controller.simulator is not None:
            sources = ("wind_shift", "road_closure") if body.event == "wind_shift_road_closure" else (body.event,)
            version = controller.snapshot().world.state_version
            events = []
            for source in sources:
                for event in load_scenario(source).events:
                    item = event.model_dump(mode="json")
                    item["event_id"] = f"injected-{source}-{version}-{len(events)}"
                    item["step"] = controller.snapshot().world.step
                    events.append(item)
            try:
                result = await controller.inject_events(body.run_id, body.expected_state_version,
                                                        events, request_id=body.request_id)
            except (RunMismatch, StateVersionMismatch) as e:
                code = "RUN_MISMATCH" if isinstance(e, RunMismatch) else "STATE_VERSION_MISMATCH"
                return _error_response(409, code, str(e), retryable=True, run_id=body.run_id,
                                       state_version=controller.snapshot().world.state_version)
            session = negotiation_sessions.get(body.run_id)
            if session is not None:
                session.service.on_event_applied(result["state_version"])
            controller._negotiation_status = "idle"
            if body.auto_negotiate:
                try:
                    session = _get_or_create_session(body.run_id, controller.snapshot().world.scenario_id)
                except ProviderError:
                    return result  # physical event remains applied; no provider to negotiate
                dp_id = session.service.next_dp_id()
                _schedule_decision_point(session, dp_id, result["state_version"],
                                         controller.simulator.locked_legs())
            return {"state_version": result["state_version"], "applied_events": [body.event]}
        try:
            session = _get_or_create_session(body.run_id, controller.snapshot().world.scenario_id)
        except ProviderError as e:
            return _error_response(503, "MODEL_UNAVAILABLE", str(e), retryable=True)
        current_version = session.sim.world["state_version"]
        if body.expected_state_version != current_version:
            return _error_response(409, "STATE_VERSION_MISMATCH",
                                    f"expected_state_version {body.expected_state_version} but current is {current_version}",
                                    retryable=True, run_id=body.run_id, state_version=current_version)
        if body.event not in INJECT_EVENT_CATALOG:
            return _error_response(422, "INVALID_REQUEST", f"unknown event {body.event!r}", retryable=False)
        new_version = session.apply_inject_event(body.event)
        session.service.on_event_applied(new_version)
        if body.auto_negotiate:
            dp_id = session.service.next_dp_id()
            _schedule_decision_point(session, dp_id, new_version)
        return {"state_version": new_version, "applied_events": [body.event]}

    @app.post("/environment/command")
    async def environment_command(body: EnvironmentCommandRequest):
        """Forward a WS-A controls command (§12.2 `EnvironmentalControls.onCommand`) as a public event."""
        if not controller.is_active or body.run_id != controller.active_run_id:
            return _error_response(409, "RUN_MISMATCH", f"run_id {body.run_id!r} is not the active run",
                                    retryable=True, run_id=body.run_id)
        if controller.mode == "replay":
            return _error_response(409, "REPLAY_READ_ONLY", "cannot change conditions during replay",
                                   retryable=False, run_id=body.run_id)
        if controller.simulator is None:
            return _error_response(422, "INVALID_REQUEST", "controls need a simulator preset run", retryable=False,
                                   run_id=body.run_id)
        world = controller.snapshot().world
        try:
            events = _command_events(body.command, world.step, world.state_version)
        except ValueError as e:
            return _error_response(422, "INVALID_REQUEST", str(e), retryable=False, run_id=body.run_id)
        try:
            result = await controller.inject_events(body.run_id, body.expected_state_version, events,
                                                    request_id=body.request_id)
        except (RunMismatch, StateVersionMismatch) as e:
            code = "RUN_MISMATCH" if isinstance(e, RunMismatch) else "STATE_VERSION_MISMATCH"
            return _error_response(409, code, str(e), retryable=True, run_id=body.run_id,
                                   state_version=controller.snapshot().world.state_version)
        except KeyError as e:
            return _error_response(422, "INVALID_REQUEST", f"unknown target {e}", retryable=False,
                                   run_id=body.run_id)
        session = negotiation_sessions.get(body.run_id)
        if session is not None:
            session.service.on_event_applied(result["state_version"])
        controller._negotiation_status = "idle"
        if body.auto_negotiate:
            try:
                session = _get_or_create_session(body.run_id, controller.snapshot().world.scenario_id)
                dp_id = session.service.next_dp_id()
                _schedule_decision_point(session, dp_id, result["state_version"], controller.simulator.locked_legs())
            except ProviderError:
                pass                                         # the physical change stands; no provider to negotiate
        return {"state_version": result["state_version"], "applied_events": [e["kind"] for e in events]}

    @app.post("/escalations/{dp_id}/resolve")
    async def resolve_escalation(dp_id: str, body: EscalationResolveRequest):
        if body.run_id != controller.active_run_id:
            return _error_response(409, "RUN_MISMATCH", "run is no longer active", retryable=True)
        if controller.mode == "replay":
            return _error_response(409, "REPLAY_READ_ONLY", "cannot resolve during replay", retryable=False)
        if controller.simulator and body.expected_state_version != controller.simulator.world.state_version:
            return _error_response(409, "STATE_VERSION_MISMATCH", "stale escalation", retryable=True,
                                   run_id=body.run_id, state_version=controller.simulator.world.state_version)
        session = negotiation_sessions.get(body.run_id)
        if session is None:
            return _error_response(404, "NOT_FOUND", "no negotiation session for this run", retryable=False)
        revisions = None
        if body.target_revisions:
            revisions = [ws_b_contracts.TargetRevision.model_validate(r.model_dump())
                        for r in body.target_revisions]
        try:
            result = session.service.resolve(
                dp_id, body.choice, expected_state_version=body.expected_state_version,
                plan_hash=body.plan_hash, target_revisions=revisions,
            )
        except NoActiveEscalation as e:
            return _error_response(409, "NO_ACTIVE_ESCALATION", str(e), retryable=False, run_id=body.run_id)
        except PlanInfeasible as e:
            return _error_response(422, "PLAN_INFEASIBLE", str(e), retryable=False, run_id=body.run_id)
        except ValueError as e:
            return _error_response(422, "INVALID_REQUEST", str(e), retryable=False, run_id=body.run_id)

        if isinstance(result, NewDecisionPoint):
            return JSONResponse(status_code=202, content={"dp_id": result.dp_id})
        return {"commit": result.model_dump(mode="json")}

    @app.get("/proposals")
    async def get_proposals(dp_id: str | None = None):
        """PRD §8.2: defaults to the current decision point."""
        session = next(iter(negotiation_sessions.values()), None)
        if session is None:
            return _error_response(404, "NOT_FOUND", "no negotiation session", retryable=False)
        rec = None
        if dp_id:
            result = session.service.results.get(dp_id)
            if result is not None:
                rec = result.record
            elif session.service.router.current and session.service.router.current.dp_id == dp_id:
                rec = session.service.router.current
        else:
            rec = session.service.router.current
        if rec is None:
            return _error_response(404, "NOT_FOUND", f"unknown dp_id {dp_id!r}", retryable=False)
        return {
            "plans": [pr.plan.model_dump(mode="json") for pr in rec.plans.values()],
            "evaluations": [ev.model_dump(mode="json") for pr in rec.plans.values()
                            for ev in pr.evaluations.values()],
            "acceptances": [a.model_dump(mode="json") for a in rec.acceptances],
        }

    return app


app = create_app()
