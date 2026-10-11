"""PRD §8.1/§8.2 run controller: reset/state/step, version/run guards, idempotency,
and the live-run-aware SSE stream (queue item C2, T12)."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app import store
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


def _parse_sse_data_events(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        data_lines = [line[len("data: "):] for line in block.splitlines() if line.startswith("data: ")]
        if data_lines:
            events.append(json.loads("".join(data_lines)))
    return events


def test_reset_unknown_scenario_returns_404():
    client = TestClient(create_app())
    response = client.post("/scenarios/not-a-real-scenario/reset", json={"seed": 1})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_reset_known_scenario_returns_snapshot_and_writes_jsonl():
    client = TestClient(create_app())
    response = client.post("/scenarios/hello-fixture/reset", json={"seed": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["state_version"] == 0
    assert body["run_id"].startswith("run-")
    assert body["snapshot"]["label"] == "Synthetic simulation"
    assert body["snapshot"]["world"]["roads"]["R1"]["id"] == "R1"

    events_path = store.events_path(body["run_id"])
    assert events_path.exists()
    lines = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert [e["type"] for e in lines] == ["run.reset", "state.snapshot"]


def test_state_returns_404_before_any_reset():
    client = TestClient(create_app())
    response = client.get("/state")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_state_matches_last_reset_snapshot():
    client = TestClient(create_app())
    reset_body = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()
    state = client.get("/state").json()
    assert state == reset_body["snapshot"]


def test_step_with_correct_version_advances_step_not_state_version():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]

    response = client.post(
        "/simulation/step",
        json={"run_id": run_id, "expected_state_version": 0, "steps": 3},
    )
    assert response.status_code == 200
    assert response.json() == {"step": 3, "state_version": 0, "paused": False}


def test_step_with_wrong_state_version_returns_409():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]

    response = client.post(
        "/simulation/step",
        json={"run_id": run_id, "expected_state_version": 99, "steps": 1},
    )
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "STATE_VERSION_MISMATCH"
    assert error["state_version"] == 0


def test_step_with_wrong_run_id_returns_409():
    client = TestClient(create_app())
    client.post("/scenarios/hello-fixture/reset", json={"seed": 1})

    response = client.post(
        "/simulation/step",
        json={"run_id": "some-other-run", "expected_state_version": 0, "steps": 1},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_MISMATCH"


def test_step_until_param_not_implemented_returns_422():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]

    response = client.post(
        "/simulation/step",
        json={"run_id": run_id, "expected_state_version": 0, "until": "horizon"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_reset_is_idempotent_with_request_id():
    client = TestClient(create_app())
    first = client.post(
        "/scenarios/hello-fixture/reset", json={"seed": 1, "request_id": "req-1"}
    ).json()
    second = client.post(
        "/scenarios/hello-fixture/reset", json={"seed": 1, "request_id": "req-1"}
    ).json()
    assert first == second


def test_events_stream_serves_live_run_after_reset():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]

    with client.stream("GET", "/events/stream") as response:
        body = "".join(response.iter_text())

    events = _parse_sse_data_events(body)
    assert [e["type"] for e in events] == ["run.reset", "state.snapshot"]
    assert all(e["run_id"] == run_id for e in events)
