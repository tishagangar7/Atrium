"""Environment controls endpoint, public targets in the Snapshot, collision-free run ids (PRD §5.8, §6.1, §7, §8.2,
§9.3, §9.7, invariant 7)."""

import asyncio
import pytest
from fastapi.testclient import TestClient

from app import run, store
from app.main import create_app


@pytest.fixture(autouse=True)
def isolated_runs(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "RUNS_DIR", tmp_path / "runs")
    for var in ("RESCUEMESH_PROVIDER", "MODEL_PROVIDER", "RESCUEMESH_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("app.agents.provider.load_backend_env", lambda: None)


def _reset(client):
    return client.post("/scenarios/normal/reset", json={"seed": 1}).json()


def _command(client, run_id, version, command, **kw):
    return client.post("/environment/command", json={"run_id": run_id, "expected_state_version": version,
                                                     "command": command, "auto_negotiate": False, **kw})


def test_snapshot_carries_public_targets_for_each_agent():
    with TestClient(create_app()) as client:
        snap = _reset(client)["snapshot"]
        assert set(snap["targets"]) == {"EVAC", "FIRE", "LOG"}
        metrics = {t["metric"] for ts in snap["targets"].values() for t in ts}
        assert {"assisted_completion", "fire_extent", "logistics_risk"} <= metrics
        assert client.get("/state").json()["targets"] == snap["targets"]


def test_set_wind_and_close_road_apply_as_public_events_and_bump_the_version():
    with TestClient(create_app()) as client:
        run_id = _reset(client)["run_id"]
        r = _command(client, run_id, 0, {"type": "set_wind", "direction": "SW", "speed": 3})
        assert r.status_code == 200 and r.json()["state_version"] == 1
        world = client.get("/state").json()["world"]
        assert world["wind"] == {"direction": "SW", "speed": 3}
        r = _command(client, run_id, 1, {"type": "set_road_status", "road_id": "R5", "status": "CLOSED_HARD"})
        assert r.status_code == 200
        assert client.get("/state").json()["world"]["roads"]["R5"]["status_override"] == "CLOSED_HARD"


@pytest.mark.parametrize("command", [
    {"type": "set_road_status", "road_id": "R2", "status": "OPEN"},            # no opening roads by fiat
    {"type": "set_resource_available", "resource_id": "B2", "available": True},  # no adding / restoring resources
    {"type": "set_wind", "direction": "CALM", "speed": 0},
    {"type": "open_shelter"},
])
def test_controls_can_never_waive_hard_constraints(command):
    """Invariant 7 / AC-033 parity: a road reopens only through clear_road; resources are never added."""
    with TestClient(create_app()) as client:
        run_id = _reset(client)["run_id"]
        r = _command(client, run_id, 0, command)
        assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_REQUEST"
        assert client.get("/state").json()["world"]["state_version"] == 0


def test_stale_version_is_rejected_and_changes_nothing():
    with TestClient(create_app()) as client:
        run_id = _reset(client)["run_id"]
        r = _command(client, run_id, 7, {"type": "set_wind", "direction": "N", "speed": 1})
        assert r.status_code == 409 and r.json()["error"]["code"] == "STATE_VERSION_MISMATCH"
        assert client.get("/state").json()["world"]["wind"]["direction"] != "N"


def test_taking_a_vehicle_out_of_service():
    with TestClient(create_app()) as client:
        run_id = _reset(client)["run_id"]
        r = _command(client, run_id, 0, {"type": "set_resource_available", "resource_id": "B2", "available": False})
        assert r.status_code == 200
        assert client.get("/state").json()["world"]["resources"]["B2"]["available"] is False


def test_same_preset_and_seed_twice_in_a_minute_never_reuse_a_run_id():
    first = run._new_run_id("normal", 1)
    store.start_run(first)
    second = run._new_run_id("normal", 1)
    store.start_run(second)
    third = run._new_run_id("normal", 1)
    assert len({first, second, third}) == 3
    assert second == f"{first}-r2" and third == f"{first}-r3"


def test_public_target_revision_survives_snapshot_and_replay():
    async def exercise():
        controller = run.RunController()
        run_id = (await controller.reset("normal", seed=1))["run_id"]
        original = controller.snapshot().targets["EVAC"][0].aspiration
        revised = original - 0.05
        controller.revise_target("assisted_completion", revised)
        controller.publish_simulator_snapshot()
        assert controller.snapshot().targets["EVAC"][0].aspiration == revised
        assert controller.simulator.scenario.targets["EVAC"][0].aspiration == original

        await controller.start_replay(run_id, speed=4)
        replayed = controller.snapshot()
        assert replayed.mode == "replay"
        assert replayed.targets["EVAC"][0].aspiration == revised

    asyncio.run(exercise())
