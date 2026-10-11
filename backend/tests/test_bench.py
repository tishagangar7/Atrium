"""PRD §8.2/§4.7/§11.3 benchmark runner and report export (queue item C6).

Methods are real now (fixed_rule runs on the simulator; single_agent / rescuemesh need a live model provider and
are *skipped*, never stubbed, when none is configured -- which is the case in tests). No comparative outcome is
asserted here: these tests check dispatch and honesty, not which method wins.

All tests use `with TestClient(...) as client:`, not a bare `TestClient(...)`: the benchmark
runner's work happens in a background `asyncio.create_task`, which needs the *same* event
loop to stay alive across the `POST /benchmarks/run` call and the later `GET
/benchmarks/{id}` polls. Starlette's `TestClient` only keeps one persistent loop (a
"blocking portal") alive across calls when used as a context manager; a bare `TestClient()`
spins up and tears down a fresh loop for every single call, which silently orphans any
background task scheduled on the previous one (it never gets a chance to run again).
"""

import csv
import json
import shutil
import time
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import run, store
from app.models import WorldState
from app.bench import report
from app.main import create_app


@pytest.fixture(autouse=True)
def _clean_test_runs():
    before = {p.name for p in store.RUNS_DIR.iterdir()} if store.RUNS_DIR.exists() else set()
    yield
    if not store.RUNS_DIR.exists():
        return
    for p in store.RUNS_DIR.iterdir():
        if p.name in before or p.name in ("fixtures", "results.csv"):
            continue
        shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)


def _poll_until_done(client: TestClient, benchmark_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/benchmarks/{benchmark_id}").json()
        if status["status"] == "done":
            return status
        time.sleep(0.02)
    raise AssertionError("benchmark did not finish in time")


def test_unknown_preset_returns_404(tmp_path):
    with TestClient(create_app(
        results_csv_path=tmp_path / "results.csv", summary_json_path=tmp_path / "summary.json",
    )) as client:
        response = client.post("/benchmarks/run", json={"presets": ["not-a-real-preset"]})
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_benchmark_runs_fixed_rule_for_real_and_skips_model_methods_without_a_provider(tmp_path, monkeypatch):
    for var in ("RESCUEMESH_PROVIDER", "MODEL_PROVIDER", "RESCUEMESH_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("app.agents.provider.load_backend_env", lambda: None)   # never read a developer's .env here
    results_csv = tmp_path / "results.csv"
    with TestClient(create_app(
        results_csv_path=results_csv, summary_json_path=tmp_path / "summary.json",
    )) as client:
        response = client.post(
            "/benchmarks/run",
            json={"presets": ["normal"], "seeds": [1, 2], "methods": ["rescuemesh", "fixed_rule"]},
        )
        assert response.status_code == 202
        benchmark_id = response.json()["benchmark_id"]

        status = _poll_until_done(client, benchmark_id)
        assert status["completed"] == status["total"] == 4  # 1 preset x 2 seeds x 2 methods attempted
        assert status["results_csv_url"] == str(results_csv)
        assert len(status["skipped"]) == 2
        assert {item["method"] for item in status["skipped"]} == {"rescuemesh"}
        assert all(item["reason"] for item in status["skipped"])

    with results_csv.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 2                                   # only the runs that really ran
    assert {r["method"] for r in rows} == {"fixed_rule"}
    assert {r["seed"] for r in rows} == {"1", "2"}
    assert all("STUB" not in r["notes"] for r in rows)
    assert all(r["model_calls"] == "0" and int(r["decision_points"]) >= 1 for r in rows)
    assert all(json.loads(r["metrics"])["invalid_executed"] == 0 for r in rows)
    for row in rows:
        events = store.read_events(row["run_id"])
        snapshots = [event for event in events if event["type"] == "state.snapshot"]
        assert len(snapshots) >= 2
        assert all(event["data"]["last_seq"] == event["seq"] for event in snapshots)
        final_world = WorldState.model_validate(snapshots[-1]["data"]["world"])
        assert events[-1]["type"] == "run.closed"
        assert events[-1]["data"]["final_state_hash"] == run._state_hash(final_world)
    loaded = report.read_results_csv(results_csv)
    markdown = report.render_markdown(loaded)
    assert len(loaded) == 2
    assert "Coverage: 2 of 36" in markdown
    assert "The paired comparison is incomplete" in markdown
    assert "Exposure (person-steps)" in markdown
    assert "Escalations" in markdown
    assert "Estimated cost USD" in markdown
    assert "Forecast-versus-realized differences require" in markdown


def test_report_generator_writes_only_recorded_rows(tmp_path):
    source = tmp_path / "results.csv"
    source.write_text(",".join(report.RUNRESULT_FIELDS) + "\n")
    destination = tmp_path / "results.md"
    report.write_markdown_from_csv(source, destination)
    assert "No recorded runs" in destination.read_text()
    assert "no comparison" in destination.read_text().lower()


def test_model_dispatch_awaits_async_method_in_running_server_loop(tmp_path, monkeypatch):
    from app.bench import methods

    async def unavailable(*_args):
        raise methods.MethodUnavailable("live model unavailable in this test")

    monkeypatch.setattr(methods, "run_model_method", unavailable)
    with TestClient(create_app(
        results_csv_path=tmp_path / "results.csv", summary_json_path=tmp_path / "summary.json",
    )) as client:
        response = client.post(
            "/benchmarks/run",
            json={"presets": ["normal"], "seeds": [1], "methods": ["rescuemesh"]},
        )
        assert response.status_code == 202
        status = _poll_until_done(client, response.json()["benchmark_id"])
        assert status["skipped"] == [{
            "preset": "normal", "seed": 1, "method": "rescuemesh",
            "reason": "live model unavailable in this test",
        }]


def test_unexpected_model_failure_releases_benchmark_slot(tmp_path, monkeypatch):
    from app.bench import methods

    async def broken(*_args):
        raise RuntimeError("provider failed unexpectedly")

    monkeypatch.setattr(methods, "run_model_method", broken)
    with TestClient(create_app(
        results_csv_path=tmp_path / "results.csv", summary_json_path=tmp_path / "summary.json",
    )) as client:
        first = client.post(
            "/benchmarks/run",
            json={"presets": ["normal"], "seeds": [1], "methods": ["rescuemesh"]},
        )
        assert first.status_code == 202
        benchmark_id = first.json()["benchmark_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = client.get(f"/benchmarks/{benchmark_id}").json()
            if status["status"] == "failed":
                break
            time.sleep(0.02)
        assert status["status"] == "failed"
        assert status["error"] == "BENCHMARK_FAILED"
        second = client.post(
            "/benchmarks/run",
            json={"presets": ["normal"], "seeds": [1], "methods": ["fixed_rule"]},
        )
        assert second.status_code == 202
        assert _poll_until_done(client, second.json()["benchmark_id"])["status"] == "done"


def test_consensus_quality_uses_same_decision_point_authoritative_forecasts():
    from app.bench.methods import Outcome, _record_consensus_quality
    from app.models import Metrics

    def forecast(meets_floor):
        return SimpleNamespace(valid=True, target_checks=[SimpleNamespace(meets_floor=meets_floor)])

    def record(*pairs):
        return SimpleNamespace(plans={
            plan_hash: SimpleNamespace(evaluations={"authoritative": forecast(meets_floor)})
            for plan_hash, meets_floor in pairs
        })

    metrics = Metrics(
        civilian_exposure=0, assisted_completion=1, assisted_sheltered=1,
        assisted_demand=1, evacuation_completion_step=0, fire_extent=0,
        burning_cell_steps=0, crew_risk_steps=0, logistics_risk=0,
        invalid_attempted=0, invalid_executed=0,
    )
    outcome = Outcome(metrics=metrics)
    _record_consensus_quality(SimpleNamespace(
        status="committed", commit=SimpleNamespace(plan_hash="chosen"),
        record=record(("chosen", False), ("alternative", True)),
    ), outcome)
    assert outcome.inappropriate_consensus == 1
    _record_consensus_quality(SimpleNamespace(
        status="escalated", commit=None, record=record(("only", False)),
    ), outcome)
    assert outcome.justified_escalations == 1
    _record_consensus_quality(SimpleNamespace(
        status="escalated", commit=None, record=record(("only", True)),
    ), outcome)
    assert outcome.justified_escalations == 1


@pytest.mark.parametrize("method", ["rescuemesh", "single_agent"])
def test_model_method_runs_in_an_existing_event_loop_with_test_provider(monkeypatch, method):
    """Exercise the async service wiring without recording TEST PROVIDER output as a result."""
    from app.agents.provider_fake import FakeProvider
    from app.bench import methods

    monkeypatch.setenv("RESCUEMESH_TEST", "1")
    provider = FakeProvider(script={})
    settings = SimpleNamespace(provider="fake", model="test-provider", turn_deadline_s=1)
    monkeypatch.setattr(methods, "live_provider", lambda: (provider, settings))
    emitted = []

    async def exercise():
        return await methods.run_model_method(
            method, "normal", 1, "test-benchmark-method", lambda kind, data: emitted.append((kind, data)), {},
        )

    outcome = asyncio.run(exercise())
    assert outcome.decision_points >= 1
    if method == "rescuemesh":
        assert outcome.escalations >= 1
        assert outcome.commits == 0  # benchmark F0 after escalation is not unanimous consensus
    assert outcome.model_calls == len(provider.requests) > 0
    assert outcome.final_state_hash
    assert any(kind == "state.snapshot" for kind, _ in emitted)


def test_second_benchmark_while_running_returns_409(tmp_path):
    with TestClient(create_app(
        results_csv_path=tmp_path / "results.csv", summary_json_path=tmp_path / "summary.json",
    )) as client:
        first = client.post("/benchmarks/run", json={"seeds": [1, 2, 3], "methods": ["rescuemesh"]})
        assert first.status_code == 202

        second = client.post("/benchmarks/run", json={})
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "BENCHMARK_IN_PROGRESS"

        _poll_until_done(client, first.json()["benchmark_id"])


def test_get_benchmark_unknown_id_returns_404(tmp_path):
    with TestClient(create_app(
        results_csv_path=tmp_path / "results.csv", summary_json_path=tmp_path / "summary.json",
    )) as client:
        response = client.get("/benchmarks/no-such-benchmark")
        assert response.status_code == 404


def test_summary_json_written_on_completion(tmp_path):
    summary_path = tmp_path / "summary.json"
    with TestClient(create_app(
        results_csv_path=tmp_path / "results.csv", summary_json_path=summary_path,
    )) as client:
        benchmark_id = client.post("/benchmarks/run", json={"presets": ["normal"], "seeds": [1]}).json()["benchmark_id"]
        _poll_until_done(client, benchmark_id)

    summary = json.loads(summary_path.read_text())
    assert summary["run_count"] == 1          # fixed_rule ran; the two model methods were skipped (no provider)
    assert set(summary["by_method"]) == {"fixed_rule"}


def test_benchmark_envelopes_appear_on_stream(tmp_path):
    with TestClient(create_app(
        results_csv_path=tmp_path / "results.csv", summary_json_path=tmp_path / "summary.json",
    )) as client:
        benchmark_id = client.post("/benchmarks/run", json={"seeds": [1]}).json()["benchmark_id"]
        _poll_until_done(client, benchmark_id)

        with client.stream("GET", "/events/stream") as response:
            body = "".join(response.iter_text())

    assert "benchmark.progress" in body
    assert "benchmark.done" in body
    assert benchmark_id in body
