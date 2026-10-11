"""Headless real-method benchmark runner (PRD §4.7, §8, §11.3; C6)."""

from __future__ import annotations

import asyncio
import json
import time
from uuid import uuid4
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Callable

from .. import models as m
from .. import run
from .. import store
from . import methods, report

OnEnvelope = Callable[[str, str, dict], None]

PRD_PRESETS = ("normal", "wind_shift", "road_closure", "compound_failure")   # scenarios/*.json (§5.11)

STUB_NOTE = (
    "STUB run (queue C6): no real negotiation (rescuemesh), fixed-rule policy (A4), or "
    "single-agent baseline (B6) exists yet -- every method ran the identical stub loop "
    "(reset + jump to horizon, zero model calls). Not a comparative result."
)


class AlreadyRunning(Exception):
    pass


class BenchmarkNotFound(Exception):
    def __init__(self, benchmark_id: str):
        self.benchmark_id = benchmark_id
        super().__init__(f"unknown benchmark_id {benchmark_id!r}")


def _new_benchmark_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"bench-{ts}-{uuid4().hex[:8]}"


class BenchmarkRunner:
    def __init__(self, results_csv_path, summary_json_path):
        self._results_csv_path = results_csv_path
        self._summary_json_path = summary_json_path
        self._running_id: str | None = None
        self._status: "OrderedDict[str, dict]" = OrderedDict()

    @property
    def is_running(self) -> bool:
        return self._running_id is not None

    @property
    def results_csv_path(self):
        return self._results_csv_path

    def get_status(self, benchmark_id: str) -> dict | None:
        return self._status.get(benchmark_id)

    async def start(
        self,
        presets: list[str] | None,
        seeds: list[int] | None,
        methods: list[str] | None,
        budget: dict | None,
        on_envelope: OnEnvelope,
    ) -> str:
        if self.is_running:
            raise AlreadyRunning()

        presets = presets or list(PRD_PRESETS)                       # §11.3: the four benchmark presets
        for preset in presets:
            if preset not in run.SCENARIO_FIXTURES and preset not in PRD_PRESETS:
                raise run.ScenarioNotFound(preset)
        seeds = seeds or [1]
        methods = methods or ["rescuemesh", "fixed_rule", "single_agent"]
        budget = budget or {}

        benchmark_id = _new_benchmark_id()
        total = len(presets) * len(seeds) * len(methods)
        self._status[benchmark_id] = {"status": "running", "completed": 0, "total": total}
        self._running_id = benchmark_id

        asyncio.create_task(
            self._run_all(benchmark_id, presets, seeds, methods, budget, on_envelope)
        )
        return benchmark_id

    async def _run_all(
        self,
        benchmark_id: str,
        presets: list[str],
        seeds: list[int],
        methods: list[str],
        budget: dict,
        on_envelope: OnEnvelope,
    ) -> None:
        results: list[m.RunResult] = []
        status = self._status[benchmark_id]
        try:
            for preset in presets:
                for seed in seeds:
                    for method in methods:
                        result = await self._run_one(benchmark_id, preset, seed, method, budget)
                        if result is not None:
                            results.append(result)
                            report.append_result_row(self._results_csv_path, result)
                        status["completed"] += 1
                        on_envelope(
                            benchmark_id,
                            "benchmark.progress",
                            {"benchmark_id": benchmark_id, "completed": status["completed"],
                             "total": status["total"]},
                        )
                        await asyncio.sleep(0.05)

            report.write_summary_json(self._summary_json_path, results)
            status["status"] = "done"
            on_envelope(
                benchmark_id, "benchmark.done",
                {"benchmark_id": benchmark_id, "completed": status["completed"], "total": status["total"]},
            )
        except Exception:
            # A failed background task must not leave every future benchmark stuck at 409.
            status["status"] = "failed"
            status["error"] = "BENCHMARK_FAILED"
            on_envelope(benchmark_id, "benchmark.failed", {
                "benchmark_id": benchmark_id, "completed": status["completed"],
                "total": status["total"], "error": "BENCHMARK_FAILED",
            })
        finally:
            self._running_id = None

    async def _run_one(self, benchmark_id: str, preset: str, seed: int, method: str, budget: dict) -> m.RunResult | None:
        """One real paired run. Returns None (and records why) when the method can't run honestly here — no stub
        rows are ever written (AGENTS.md invariant 9)."""
        run_id = f"{benchmark_id}-{preset}-s{seed}-{method}"
        store.start_run(run_id)
        start = time.monotonic()
        seq = 0

        def emit(envelope_type: str, data: dict) -> None:
            nonlocal seq
            seq += 1
            if envelope_type == "state.snapshot":
                data = {**data, "last_seq": seq}
            world = data.get("world") if isinstance(data, dict) else None
            store.append_event(run_id, {
                "seq": seq, "run_id": run_id, "mode": "benchmark", "type": envelope_type,
                "ts": run._now_iso_ms(),
                "step": world["step"] if world else data.get("step", 0),
                "state_version": world["state_version"] if world else data.get("state_version", 0),
                "dp_id": data.get("dp_id"),
                "trace_id": f"{run_id}/{data.get('dp_id') or '-'}/-/-", "data": data,
            })

        emit("run.reset", {"scenario_id": preset, "seed": seed, "method": method})
        try:
            if method == "fixed_rule":
                outcome = methods.run_fixed_rule(preset, seed, run_id, emit)
            elif method in methods.MODEL_METHODS:
                outcome = await methods.run_model_method(method, preset, seed, run_id, emit, budget)
            else:
                raise methods.MethodUnavailable(f"unknown method {method!r}")
        except (methods.MethodUnavailable, FileNotFoundError, KeyError, ValueError) as e:
            emit("run.closed", {"skipped": True, "reason": str(e)})
            self._status[benchmark_id].setdefault("skipped", []).append(
                {"preset": preset, "seed": seed, "method": method, "reason": str(e)})
            return None
        except Exception:
            emit("run.closed", {"failed": True, "error": "BENCHMARK_FAILED"})
            raise
        emit("run.closed", {"final_state_hash": outcome.final_state_hash})
        wall_ms = int((time.monotonic() - start) * 1000)
        return m.RunResult(
            run_id=run_id, preset=preset, seed=seed, method=method, model=outcome.model,
            budget_calls=budget.get("calls"), budget_tokens=budget.get("tokens"),
            metrics=outcome.metrics, decision_points=outcome.decision_points, commits=outcome.commits,
            escalations=outcome.escalations, human_decisions=0,
            inappropriate_consensus=outcome.inappropriate_consensus,
            justified_escalations=outcome.justified_escalations,
            adaptation_wall_ms=outcome.adaptation_wall_ms, model_calls=outcome.model_calls,
            tokens_in=outcome.tokens_in, tokens_out=outcome.tokens_out, wall_ms_total=wall_ms,
            cost_usd_estimate=None,                                        # §10.5: null unless prices are verified
            notes=outcome.notes,
        )
