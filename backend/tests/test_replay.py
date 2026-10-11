"""PRD §4.7/§8.2/§13.3 replay endpoints and stored run retrieval (queue item C5)."""

import shutil
import time
from datetime import datetime, timedelta, timezone

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


def test_replay_unknown_run_returns_404():
    client = TestClient(create_app())
    response = client.post("/replay/no-such-run", json={"speed": 1})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_replay_switches_mode_and_relabels_envelopes():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]
    client.post("/simulation/step", json={"run_id": run_id, "expected_state_version": 0, "steps": 2})

    response = client.post(f"/replay/{run_id}", json={"speed": 2})
    assert response.status_code == 200
    body = response.json()
    assert body == {"run_id": f"replay-of-{run_id}", "mode": "replay"}

    events = client.get("/events", params={"run_id": body["run_id"], "after_seq": 0}).json()
    assert [e["type"] for e in events] == ["run.reset", "state.snapshot", "state.step"]
    assert all(e["run_id"] == body["run_id"] and e["mode"] == "replay" for e in events)


def test_state_reflects_replay_mode_and_rehydrated_world():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]
    client.post("/replay/{}".format(run_id), json={"speed": 1})

    state = client.get("/state").json()
    assert state["mode"] == "replay"
    assert state["run_id"] == f"replay-of-{run_id}"
    assert state["world"]["roads"]["R1"]["id"] == "R1"


def test_step_during_replay_returns_409_replay_read_only():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]
    replay_run_id = client.post(f"/replay/{run_id}", json={"speed": 1}).json()["run_id"]

    response = client.post(
        "/simulation/step",
        json={"run_id": replay_run_id, "expected_state_version": 0, "steps": 1},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REPLAY_READ_ONLY"


def test_reset_cancels_replay_and_returns_to_live():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]
    client.post(f"/replay/{run_id}", json={"speed": 1})

    fresh = client.post("/scenarios/hello-fixture/reset", json={"seed": 2}).json()
    state = client.get("/state").json()
    assert state["mode"] == "live"
    assert state["run_id"] == fresh["run_id"]


def test_runs_list_shows_open_then_closed_final_state_hash():
    client = TestClient(create_app())
    first_run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]

    runs = {r["run_id"]: r for r in client.get("/runs").json()}
    assert runs[first_run_id]["final_state_hash"] is None
    assert runs[first_run_id]["preset"] == "hello-fixture"
    assert runs[first_run_id]["seed"] == 1
    assert runs[first_run_id]["method"] == "rescuemesh"

    # A second reset closes the first run (emits run.closed to its own file).
    client.post("/scenarios/hello-fixture/reset", json={"seed": 2})
    runs_after = {r["run_id"]: r for r in client.get("/runs").json()}
    assert runs_after[first_run_id]["final_state_hash"] is not None


def test_get_run_detail_and_events_and_404():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]

    detail = client.get(f"/runs/{run_id}").json()
    assert detail["summary"]["run_id"] == run_id
    assert detail["result"] is None
    assert detail["events_url"] == f"/runs/{run_id}/events"

    events = client.get(detail["events_url"]).json()
    assert [e["type"] for e in events] == ["run.reset", "state.snapshot"]

    assert client.get("/runs/no-such-run").status_code == 404
    assert client.get("/runs/no-such-run/events").status_code == 404


def _ts(seconds_offset: float) -> str:
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds_offset)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def test_replay_pacing_respects_speed():
    client = TestClient(create_app())
    run_id = client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]
    client.post("/simulation/step", json={"run_id": run_id, "expected_state_version": 0, "steps": 1})

    # Rewrite timestamps to known, evenly spaced values so pacing is deterministic.
    events = store.read_events(run_id)
    for i, e in enumerate(events):
        e["ts"] = _ts(0.15 * i)
    store.start_run(run_id)
    for e in events:
        store.append_event(run_id, e)

    def _run_replay(speed: int) -> float:
        c = TestClient(create_app())
        c.post(f"/replay/{run_id}", json={"speed": speed})
        start = time.monotonic()
        with c.stream("GET", "/events/stream") as response:
            list(response.iter_text())
        return time.monotonic() - start

    elapsed_speed1 = _run_replay(1)
    elapsed_speed4 = _run_replay(4)

    assert elapsed_speed1 >= 0.25  # 3 envelopes, 2 gaps of 0.15s at speed 1
    assert elapsed_speed4 < elapsed_speed1 / 2
