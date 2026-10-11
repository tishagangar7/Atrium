"""PRD §8.4 reconnection/resume, §8.2 GET /events polling fallback, NFR-010 bounds
(queue item C3). `GET /state`-based snapshot reconciliation is exercised end-to-end here
too, since C2 only unit-tested the snapshot shape, not the reconnect flow around it."""

import json
import shutil

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import HELLO_FIXTURE_RUN_ID, create_app
from app.run import MAX_ENVELOPE_BUFFER, RunController


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


def _parse_sse(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        data_lines = [line[len("data: "):] for line in block.splitlines() if line.startswith("data: ")]
        if data_lines:
            events.append(json.loads("".join(data_lines)))
    return events


def test_stale_last_event_id_before_any_reset_triggers_snapshot_required():
    client = TestClient(create_app())
    with client.stream(
        "GET", "/events/stream", headers={"Last-Event-ID": "some-other-run:3"}
    ) as response:
        body = "".join(response.iter_text())
    events = _parse_sse(body)
    assert [e["type"] for e in events] == ["snapshot.required"]
    assert events[0]["data"]["active_run_id"] is None


def test_matching_hello_fixture_run_id_still_resumes_by_seq():
    # Preserves C1's original contract: before any reset, the hello fixture is the
    # addressable "run" for Last-Event-ID purposes.
    client = TestClient(create_app())
    with client.stream(
        "GET", "/events/stream", headers={"Last-Event-ID": f"{HELLO_FIXTURE_RUN_ID}:1"}
    ) as response:
        body = "".join(response.iter_text())
    events = _parse_sse(body)
    assert [e["seq"] for e in events] == [2]


def test_stale_last_event_id_after_reset_triggers_snapshot_required_with_new_run_id():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]

    with client.stream(
        "GET", "/events/stream", headers={"Last-Event-ID": "a-previous-run:9"}
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert [e["type"] for e in events] == ["snapshot.required"]
    assert events[0]["data"]["active_run_id"] == run_id


def test_matching_run_id_resumes_backlog_after_reset():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]
    client.post(
        "/simulation/step", json={"run_id": run_id, "expected_state_version": 0, "steps": 1}
    )

    with client.stream(
        "GET", "/events/stream", headers={"Last-Event-ID": f"{run_id}:1"}
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse(body)
    assert [e["type"] for e in events] == ["state.snapshot", "state.step"]
    assert [e["seq"] for e in events] == [2, 3]


def test_get_events_happy_path_and_after_seq_filtering():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]
    client.post(
        "/simulation/step", json={"run_id": run_id, "expected_state_version": 0, "steps": 1}
    )

    full = client.get("/events", params={"run_id": run_id, "after_seq": 0})
    assert full.status_code == 200
    assert [e["type"] for e in full.json()] == ["run.reset", "state.snapshot", "state.step"]

    partial = client.get("/events", params={"run_id": run_id, "after_seq": 2})
    assert [e["type"] for e in partial.json()] == ["state.step"]


def test_get_events_wrong_run_id_returns_409():
    client = TestClient(create_app())
    client.post("/scenarios/hello-fixture/reset", json={"seed": 1})

    response = client.get("/events", params={"run_id": "not-the-active-run", "after_seq": 0})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_MISMATCH"


def test_get_events_with_no_active_run_returns_409():
    client = TestClient(create_app())
    response = client.get("/events", params={"run_id": "anything", "after_seq": 0})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_MISMATCH"


def test_snapshot_reconciliation_flow():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]

    state = client.get("/state").json()
    last_seq = state["last_seq"]

    nothing_yet = client.get("/events", params={"run_id": run_id, "after_seq": last_seq})
    assert nothing_yet.json() == []

    client.post(
        "/simulation/step", json={"run_id": run_id, "expected_state_version": 0, "steps": 5}
    )

    new_events = client.get("/events", params={"run_id": run_id, "after_seq": last_seq}).json()
    assert len(new_events) == 1
    assert new_events[0]["type"] == "state.step"
    assert new_events[0]["data"]["step"] == 5


def test_envelope_buffer_is_bounded_per_nfr_010():
    rc = RunController()
    assert rc._envelopes.maxlen == MAX_ENVELOPE_BUFFER == 10_000
