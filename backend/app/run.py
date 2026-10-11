"""Single-run transport and persistence (PRD §8.1–8.5).

The four PRD presets delegate physics to SimulatorService. `hello-fixture` remains
an explicitly named transport harness; it is never used for real scenario physics.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from . import models as m
from . import store
from .sim.service import SimulatorService
from .sim.scenario import PRESETS

FIXTURES_DIR = Path(__file__).parent / "fixtures"
MAX_ENVELOPE_BUFFER = 10_000  # NFR-010: in-memory stream buffer <= 10k events
SCENARIO_FIXTURES: dict[str, Path] = {
    "hello-fixture": FIXTURES_DIR / "scenario_stub.json",
}

IDEMPOTENCY_CACHE_SIZE = 200


class ScenarioNotFound(Exception):
    def __init__(self, scenario_id: str):
        self.scenario_id = scenario_id
        super().__init__(f"unknown scenario_id {scenario_id!r}")


class NoActiveRun(Exception):
    pass


class RunMismatch(Exception):
    def __init__(self, expected_run_id: str | None, got_run_id: str):
        self.expected_run_id = expected_run_id
        self.got_run_id = got_run_id
        super().__init__(f"run_id {got_run_id!r} does not match active run {expected_run_id!r}")


class StateVersionMismatch(Exception):
    def __init__(self, expected: int, current: int):
        self.expected = expected
        self.current = current
        super().__init__(f"expected_state_version {expected} but current is {current}")


class InvalidRequest(Exception):
    pass


class RunNotFound(Exception):
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"no recorded run {run_id!r}")


class ReplayReadOnly(Exception):
    def __init__(self):
        super().__init__("cannot step during replay (PRD §4.7: replay does not call the simulator)")


def _now_iso_ms() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _new_run_id(scenario_id: str, seed: int) -> str:
    """PRD §7 format `run-{UTC yyyymmddThhmmZ}-{preset}-s{seed}`. The format has minute resolution, so a second reset
    of the same preset and seed in the same minute would reuse an id and overwrite its stored run (replay, results).
    Such a repeat gets a `-r2`, `-r3`, ... suffix; the first run in a minute keeps the exact PRD form."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
    base = f"run-{ts}-{scenario_id}-s{seed}"
    taken = set(store.list_run_ids())
    if base not in taken:
        return base
    n = 2
    while f"{base}-r{n}" in taken:
        n += 1
    return f"{base}-r{n}"


def _state_hash(world: m.WorldState) -> str:
    """A plain content fingerprint for `run.closed`'s `final_state_hash` -- NOT the
    canonical plan hash (PRD §6.7, Ali/WS-B's algorithm). No negotiation concept here."""
    payload = world.model_dump_json()
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def _build_world(scenario: m.Scenario, run_id: str, seed: int) -> m.WorldState:
    return m.WorldState(
        run_id=run_id,
        scenario_id=scenario.scenario_id,
        seed=seed,
        step=0,
        state_version=0,
        roads={r.id: r for r in scenario.roads},
        zones={z.id: z for z in scenario.zones},
        shelters={s.id: s for s in scenario.shelters},
        cells={c.id: c for c in scenario.cells},
        resources={res.id: res for res in scenario.resources},
        wind=scenario.wind,
        committed_plan_hash=None,
        active_legs=[],
        metrics_so_far=m.Metrics(
            civilian_exposure=0,
            assisted_completion=None,
            assisted_sheltered=0,
            assisted_demand=sum(z.assisted_initial for z in scenario.zones),
            evacuation_completion_step=None,
            fire_extent=0,
            burning_cell_steps=0,
            crew_risk_steps=0,
            logistics_risk=0,
            invalid_attempted=0,
            invalid_executed=0,
        ),
        paused=False,
    )


class RunController:
    """One instance per app (see `app.main.create_app`); not a module-level singleton,
    so tests get isolated state."""

    def __init__(self) -> None:
        self._lock = None  # created lazily; see _get_lock
        self._world: m.WorldState | None = None
        self.simulator: SimulatorService | None = None
        self._run_id: str | None = None
        self._mode: m.RunMode = "live"
        self._replay_speed: int = 1
        self._seq = 0
        self._envelopes: deque[dict] = deque(maxlen=MAX_ENVELOPE_BUFFER)
        self._idempotency: "OrderedDict[str, dict]" = OrderedDict()
        self._dp_id: str | None = None
        self._negotiation_status: Literal["idle", "running", "committed", "escalated", "cancelled"] = "idle"
        self._committed_plan: m.Plan | None = None
        self._escalation: m.EscalationPackage | None = None
        self._targets: dict[m.AgentId, list[m.Target]] | None = None

    def _get_lock(self):
        import asyncio

        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _remember(self, request_id: str | None, response: dict) -> None:
        if not request_id:
            return
        self._idempotency[request_id] = response
        while len(self._idempotency) > IDEMPOTENCY_CACHE_SIZE:
            self._idempotency.popitem(last=False)

    def _emit(self, envelope_type: str, data: dict, *, seq: int | None = None) -> dict:
        if seq is None:
            self._seq += 1
            seq = self._seq
        else:
            self._seq = seq
        envelope = {
            "seq": seq,
            "run_id": self._run_id,
            "mode": "live",
            "type": envelope_type,
            "ts": _now_iso_ms(),
            "step": self._world.step if self._world else 0,
            "state_version": self._world.state_version if self._world else 0,
            "dp_id": None,
            # No negotiation yet (no dp/round/agent) -- placeholder per PRD §8.3 trace_id shape.
            "trace_id": f"{self._run_id}/-/-/-",
            "data": data,
        }
        self._envelopes.append(envelope)
        if self._mode != "replay":
            # Replay re-serves an existing recording; it never creates a new one (PRD §4.7).
            store.append_event(self._run_id, envelope)
        return envelope

    def _close_active_run(self) -> None:
        """Emit `run.closed` for whatever run is currently active, if any. Shared by
        `reset()` and `start_replay()`, both of which replace the active run."""
        if self._world is not None:
            self._emit("run.closed", {"final_state_hash": _state_hash(self._world)})

    def emit_external(self, run_id: str, envelope_type: str, data: dict, *, mode: m.RunMode = "live") -> dict:
        """For producers outside the live-run state machine -- the benchmark runner (C6,
        mode="benchmark") and the negotiation session (C4, mode="live", the default) -- to
        push an envelope into this controller's shared buffer so `/events/stream` delivers
        it alongside whatever else is flowing, without touching the active live run's own
        state. Persisted to the *given* `run_id`'s own events.jsonl, not the live run's.

        Known limitation: if a client's `Last-Event-ID` happens to reference one of these
        externally-emitted envelopes, this controller's reconnect check
        (`app.main.events_stream`) will treat it as a stale/mismatched run and send
        `snapshot.required`, since that check only knows about the one live run. Per PRD
        §8.4, tracking these separately from the live run is explicitly the client's job
        ("drop any envelope whose run_id differs ... except benchmark.*"), so this isn't
        solved server-side here.
        """
        self._seq += 1
        is_live_run = run_id == self._run_id and self._world is not None and mode == "live"
        envelope = {
            "seq": self._seq,
            "run_id": run_id,
            "mode": mode,
            "type": envelope_type,
            "ts": _now_iso_ms(),
            "step": self._world.step if is_live_run else 0,
            "state_version": self._world.state_version if is_live_run else 0,
            "dp_id": data.get("dp_id"),
            "trace_id": f"{run_id}/{data.get('dp_id') or '-'}/{data.get('round') or '-'}/{data.get('agent') or '-'}",
            "data": data,
        }
        self._envelopes.append(envelope)
        store.append_event(run_id, envelope)
        return envelope

    def publish_simulator_snapshot(self) -> None:
        """Publish the authoritative world after a synchronous gate commit or event."""
        if self.simulator is None or self._world is not self.simulator.world:
            return
        seq = self._seq + 1
        self._emit("state.snapshot", self.snapshot(last_seq=seq).model_dump(mode="json"), seq=seq)

    def revise_target(self, metric: str, aspiration: float) -> None:
        """Mirror a validated, public target revision into subsequent snapshots."""
        if self._targets is None:
            return
        for targets in self._targets.values():
            for index, target in enumerate(targets):
                if target.metric == metric:
                    targets[index] = target.model_copy(update={"aspiration": aspiration})
                    return

    async def inject_events(self, run_id: str, expected_state_version: int,
                            events: list[dict], request_id: str | None = None) -> dict:
        async with self._get_lock():
            if request_id and request_id in self._idempotency:
                return self._idempotency[request_id]
            if self._mode == "replay":
                raise ReplayReadOnly()
            if self.simulator is None or run_id != self._run_id:
                raise RunMismatch(self._run_id, run_id)
            if expected_state_version != self._world.state_version:
                raise StateVersionMismatch(expected_state_version, self._world.state_version)
            self.simulator.last_changes = []
            for event in events:
                self.simulator.apply_event(event)
                self._emit("event.applied", event)
            self.publish_simulator_snapshot()
            response = {"state_version": self._world.state_version,
                        "applied_events": [e["event_id"] for e in events]}
            self._remember(request_id, response)
            return response

    @property
    def active_run_id(self) -> str | None:
        return self._run_id

    @property
    def is_active(self) -> bool:
        return self._world is not None

    @property
    def mode(self) -> m.RunMode:
        return self._mode

    @property
    def replay_speed(self) -> int:
        return self._replay_speed

    @property
    def has_buffered_envelopes(self) -> bool:
        """True once anything has been emitted into the shared buffer -- a live run
        *or* an external producer (`emit_external`, e.g. a benchmark or a negotiation
        session) with no live run ever started. `/events/stream` uses this, not just
        `is_active`, to decide whether to serve the buffer or fall back to the pre-reset
        hello fixture."""
        return len(self._envelopes) > 0

    def envelopes_after(self, last_seq: int) -> list[dict]:
        return [e for e in self._envelopes if e["seq"] > last_seq]

    def snapshot(self, *, last_seq: int | None = None) -> m.Snapshot:
        if self._world is None:
            raise NoActiveRun()
        return m.Snapshot(
            run_id=self._run_id,
            mode=self._mode,
            last_seq=last_seq if last_seq is not None else self._seq,
            world=self._world,
            evidence_holders=self.simulator.evidence_holders() if self.simulator else {},
            dp_id=self._dp_id,
            negotiation_status=self._negotiation_status,
            committed_plan=self._committed_plan,
            escalation=self._escalation,
            label="Synthetic simulation",
            targets=self._targets,
        )

    async def reset(self, scenario_id: str, seed: int = 1, request_id: str | None = None) -> dict:
        async with self._get_lock():
            if request_id and request_id in self._idempotency:
                return self._idempotency[request_id]
            if scenario_id not in SCENARIO_FIXTURES and scenario_id not in PRESETS:
                raise ScenarioNotFound(scenario_id)

            # Validate/build before closing the current run: a failed reset changes nothing.
            run_id = _new_run_id(scenario_id, seed)
            simulator = SimulatorService(scenario_id, seed, run_id) if scenario_id in PRESETS else None
            world = simulator.world if simulator else _build_world(
                m.Scenario.model_validate(json.loads(SCENARIO_FIXTURES[scenario_id].read_text())),
                run_id, seed,
            )
            self._close_active_run()
            self._run_id = run_id
            self.simulator = simulator
            self._mode = "live"
            self._seq = 0
            self._envelopes = deque(maxlen=MAX_ENVELOPE_BUFFER)
            self._world = world
            self._dp_id = None
            self._negotiation_status = "idle"
            self._committed_plan = None
            self._escalation = None
            self._targets = ({agent: [target.model_copy(deep=True) for target in targets]
                              for agent, targets in simulator.scenario.targets.items()}
                             if simulator else None)
            store.start_run(self._run_id)

            self._emit("run.reset", {"scenario_id": scenario_id, "seed": seed})
            # Reserve the state.snapshot envelope's own seq before building the snapshot,
            # so the embedded `last_seq` is this envelope's seq, not the one before it.
            self._seq += 1
            snapshot_seq = self._seq
            snap = self.snapshot(last_seq=snapshot_seq)
            self._emit("state.snapshot", snap.model_dump(mode="json"), seq=snapshot_seq)

            response = {
                "run_id": self._run_id,
                "state_version": 0,
                "snapshot": snap.model_dump(mode="json"),
            }
            self._remember(request_id, response)
            return response

    async def step(
        self,
        run_id: str,
        expected_state_version: int,
        steps: int = 1,
        until: str | None = None,
        request_id: str | None = None,
    ) -> dict:
        async with self._get_lock():
            if request_id and request_id in self._idempotency:
                return self._idempotency[request_id]
            if self._mode == "replay":
                raise ReplayReadOnly()
            if until is not None and self.simulator is None:
                raise InvalidRequest("'until' requires a real simulation preset")
            if until not in (None, "next_event", "horizon"):
                raise InvalidRequest("until must be next_event or horizon")
            if self._world is None:
                raise NoActiveRun()
            if run_id != self._run_id:
                raise RunMismatch(self._run_id, run_id)
            if expected_state_version != self._world.state_version:
                raise StateVersionMismatch(expected_state_version, self._world.state_version)

            n = steps
            if not (1 <= n <= 60):
                raise InvalidRequest("steps must be between 1 and 60")

            if self.simulator is None:
                self._world.step += n
                self._emit("state.step", {"step": self._world.step, "changes": []})
            else:
                if until is not None:
                    n = max(0, self.simulator.scenario.horizon - self._world.step)
                    # Include an extra service iteration to apply an event at the boundary.
                    due = [e.step for e in self.simulator.scenario.events
                           if e.event_id not in self.simulator.applied_event_ids
                           and e.step >= self._world.step]
                    if until == "next_event" and due:
                        n = min(n, min(due) - self._world.step + 1)
                self.simulator.step(n)
                self._world = self.simulator.world
                for change in self.simulator.last_changes:
                    if change["kind"] == "event.applied":
                        self._emit("event.applied", change["data"])
                self._emit("state.step", {"step": self._world.step,
                                          "changes": self.simulator.last_changes})
                # Full snapshots keep reconnect/replay clients aligned with real physics.
                seq = self._seq + 1
                self._emit("state.snapshot", self.snapshot(last_seq=seq).model_dump(mode="json"), seq=seq)

            response = {
                "step": self._world.step,
                "state_version": self._world.state_version,
                "paused": self._world.paused,
            }
            self._remember(request_id, response)
            return response

    async def start_replay(self, run_id: str, speed: int = 1) -> dict:
        """PRD §4.7/§8.2: replaces the active run with a labeled replay of a saved
        recording. Never calls the simulator or the model -- just re-serves the
        already-recorded envelopes (relabeled `mode: "replay"`) from a new virtual
        `replay-of-{run_id}`."""
        async with self._get_lock():
            events = store.read_events(run_id)
            last_snapshot = next(
                (e for e in reversed(events) if e.get("type") == "state.snapshot"), None
            )
            if last_snapshot is None:
                raise RunNotFound(run_id)

            self._close_active_run()

            replay_run_id = f"replay-of-{run_id}"
            relabeled = [{**e, "run_id": replay_run_id, "mode": "replay"} for e in events]

            self.simulator = None  # replay must never retain an executable simulator
            self._world = m.WorldState.model_validate(last_snapshot["data"]["world"])
            self._world.run_id = replay_run_id
            self._dp_id = last_snapshot["data"].get("dp_id")
            self._negotiation_status = last_snapshot["data"].get("negotiation_status", "idle")
            self._committed_plan = (m.Plan.model_validate(last_snapshot["data"]["committed_plan"])
                                    if last_snapshot["data"].get("committed_plan") else None)
            self._escalation = (m.EscalationPackage.model_validate(last_snapshot["data"]["escalation"])
                                if last_snapshot["data"].get("escalation") else None)
            recorded_targets = last_snapshot["data"].get("targets")
            self._targets = ({agent: [m.Target.model_validate(target) for target in targets]
                              for agent, targets in recorded_targets.items()}
                             if recorded_targets is not None else None)
            self._run_id = replay_run_id
            self._mode = "replay"
            self._replay_speed = speed
            self._seq = relabeled[-1]["seq"]
            self._envelopes = deque(relabeled, maxlen=MAX_ENVELOPE_BUFFER)

            return {"run_id": replay_run_id, "mode": "replay"}
