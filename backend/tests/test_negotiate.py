"""PRD §8.2 negotiation endpoints, wired to Ali's (WS-B) real `NegotiationService` (queue item
C4). Runs under the labeled TEST PROVIDER (`RESCUEMESH_TEST=1`, `RESCUEMESH_PROVIDER=fake`),
exactly how Ali's own 150 protocol tests work -- never presented as live output (AGENTS.md
invariant 8, AC-026). No live model credentials exist anywhere (OPEN-05); this is the PRD's own
sanctioned way to integration-test the wiring without them.

Negotiation runs against its own `StubSim`, decoupled from `RunController`'s live-run world
(see `app/negotiation_session.py`'s module docstring for why) -- `GET /state` is not asserted
here; `GET /proposals` and the negotiation envelopes on `/events/stream` are.
"""

import re
import time

import pytest
from fastapi.testclient import TestClient

from app.agents.schema import INT_SENTINEL
from app.main import create_app

NO_OBJ = {"kind": "none", "metric": "", "evaluation_id": "", "proposed_amendment": ""}
NO_REV = {"metric": "", "old_aspiration": 0, "new_aspiration": 0, "reason": ""}
SILENT = {"messages": [], "target_revision": NO_REV}


@pytest.fixture(autouse=True)
def test_mode(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_TEST", "1")
    monkeypatch.setenv("RESCUEMESH_PROVIDER", "fake")


def _draft(resource="B1", dest="VJ", routes=("R1", "R3"), start=0, task="drive", **kw):
    d = {"resource_id": resource, "task": task, "origin": "BASE", "destination": dest,
         "route_ids": list(routes), "start_step": start, "people_count": INT_SENTINEL,
         "zone_id": "", "shelter_id": "", "crew_id": "", "target_cells": [], "edge_id": "",
         "duration_steps": INT_SENTINEL}
    d.update(kw)
    return d


def _msg(message_type="PROPOSE", **kw):
    m = {"message_type": message_type, "recipients": [], "plan": [], "parent_plan_id": "",
         "target_plan_id": "", "target_plan_hash": "", "objection": NO_OBJ, "evidence_ids": [],
         "caused_by": [], "requested_evidence_id": "", "requested_topic": "",
         "shared_evidence_ids": [], "reason": "", "blocking": [], "rationale": "ok"}
    m.update(kw)
    return m


def _turn(*messages, revision=None):
    return {"messages": list(messages), "target_revision": revision or NO_REV}


def _hash_in(req, n=0):
    text = " ".join(str(getattr(item, "text", "")) for item in req.messages)
    hashes = re.findall(r'"plan_hash":"([0-9a-f]{64})"', text)
    return hashes[n] if len(hashes) > n else ""


def _accept(n=0):
    return lambda req: _turn(_msg("ACCEPT", target_plan_hash=_hash_in(req, n)))


EVAC_PLAN = _turn(_msg(plan=[_draft("B1")]))

COMMIT_SCRIPT = {
    ("EVAC", 1): EVAC_PLAN, ("FIRE", 1): SILENT, ("LOG", 1): SILENT,
    ("EVAC", 2): SILENT, ("FIRE", 2): _accept(), ("LOG", 2): _accept(),
}


def _reset(client: TestClient) -> str:
    return client.post("/scenarios/hello-fixture/reset", json={"seed": 1}).json()["run_id"]


TERMINAL_EVENT_TYPES = {"plan.committed", "escalation.opened"}


def _wait_for_resolution(client: TestClient, timeout: float = 3.0) -> str:
    """Polls `/events/stream` for a terminal event type. An all-silent decision point has
    *zero* plans when it escalates (nobody proposed), so `/proposals`'s plan list can't be
    used to detect completion -- the stream's own event types are the only reliable signal."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with client.stream("GET", "/events/stream") as response:
            body = "".join(response.iter_text())
        for event_type in TERMINAL_EVENT_TYPES:
            if f'"type": "{event_type}"' in body:
                return event_type
        time.sleep(0.02)
    raise AssertionError("decision point did not resolve in time")


def _poll_dp(client: TestClient, dp_id: str, timeout: float = 3.0) -> dict:
    """For the commit case: waits for resolution, then returns `/proposals`'s snapshot."""
    _wait_for_resolution(client, timeout)
    response = client.get("/proposals", params={"dp_id": dp_id})
    assert response.status_code == 200
    return response.json()


def test_negotiate_no_active_run_returns_404():
    with TestClient(create_app()) as client:
        response = client.post("/negotiate", json={"run_id": "x", "expected_state_version": 0})
    assert response.status_code == 404


def test_negotiate_wrong_run_id_returns_409():
    with TestClient(create_app()) as client:
        _reset(client)
        response = client.post("/negotiate", json={"run_id": "not-the-run", "expected_state_version": 0})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUN_MISMATCH"


def test_negotiate_wrong_state_version_returns_409():
    with TestClient(create_app()) as client:
        run_id = _reset(client)
        response = client.post("/negotiate", json={"run_id": run_id, "expected_state_version": 99})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STATE_VERSION_MISMATCH"


def test_negotiate_without_provider_configured_returns_503(monkeypatch):
    monkeypatch.delenv("RESCUEMESH_PROVIDER", raising=False)
    monkeypatch.delenv("RESCUEMESH_TEST", raising=False)
    with TestClient(create_app()) as client:
        run_id = _reset(client)
        response = client.post("/negotiate", json={"run_id": run_id, "expected_state_version": 0})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_UNAVAILABLE"


def test_negotiate_reaches_committed_and_proposals_reflects_it():
    with TestClient(create_app(negotiation_script=COMMIT_SCRIPT)) as client:
        run_id = _reset(client)
        response = client.post("/negotiate", json={"run_id": run_id, "expected_state_version": 0})
        assert response.status_code == 202
        dp_id = response.json()["dp_id"]

        result = _poll_dp(client, dp_id)
        committed = [p for p in result["plans"] if p["state"] == "COMMITTED"]
        assert len(committed) == 1
        assert {a["agent_id"] for a in result["acceptances"]} == {"EVAC", "FIRE", "LOG"}


def test_negotiate_commit_envelope_reaches_stream():
    with TestClient(create_app(negotiation_script=COMMIT_SCRIPT)) as client:
        run_id = _reset(client)
        dp_id = client.post(
            "/negotiate", json={"run_id": run_id, "expected_state_version": 0}
        ).json()["dp_id"]
        _poll_dp(client, dp_id)
        with client.stream("GET", "/events/stream") as response:
            body = "".join(response.iter_text())
    assert "plan.committed" in body
    assert "negotiation.started" in body


def test_negotiate_already_in_progress_returns_409():
    with TestClient(create_app(negotiation_script={}, negotiation_delay_s=0.1)) as client:
        run_id = _reset(client)
        first = client.post("/negotiate", json={"run_id": run_id, "expected_state_version": 0})
        assert first.status_code == 202

        second = client.post("/negotiate", json={"run_id": run_id, "expected_state_version": 0})
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "NEGOTIATION_IN_PROGRESS"

        _poll_dp(client, first.json()["dp_id"])


def test_negotiate_cancel():
    with TestClient(create_app(negotiation_script={}, negotiation_delay_s=0.2)) as client:
        run_id = _reset(client)
        client.post("/negotiate", json={"run_id": run_id, "expected_state_version": 0})
        response = client.post("/negotiate/cancel", json={"run_id": run_id})
        assert response.status_code == 200
        assert response.json() == {"cancelled": True}


def test_escalation_reached_then_resolved_with_fallback():
    with TestClient(create_app(negotiation_script={})) as client:  # all-silent -> escalates
        run_id = _reset(client)
        dp_id = client.post(
            "/negotiate", json={"run_id": run_id, "expected_state_version": 0}
        ).json()["dp_id"]
        _poll_dp(client, dp_id)

        resolve = client.post(
            f"/escalations/{dp_id}/resolve",
            json={"run_id": run_id, "expected_state_version": 0, "choice": "fallback"},
        )
        assert resolve.status_code == 200
        commit = resolve.json()["commit"]
        assert commit["authority"] == "human_choice"
        assert commit["plan_id"] == f"{dp_id}:F0"


def test_resolve_unknown_dp_returns_409_no_active_escalation():
    with TestClient(create_app(negotiation_script={})) as client:
        run_id = _reset(client)
        dp_id = client.post(
            "/negotiate", json={"run_id": run_id, "expected_state_version": 0}
        ).json()["dp_id"]
        _poll_dp(client, dp_id)

        response = client.post(
            f"/escalations/{dp_id}/resolve",
            json={"run_id": run_id, "expected_state_version": 99, "choice": "fallback"},
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_ACTIVE_ESCALATION"


def test_events_inject_applies_and_auto_negotiates():
    with TestClient(create_app(negotiation_script={})) as client:
        run_id = _reset(client)
        # Any negotiation-family call lazily builds the session at version 0.
        client.post("/negotiate/cancel", json={"run_id": run_id})

        response = client.post(
            "/events/inject",
            json={"run_id": run_id, "expected_state_version": 0, "event": "wind_shift_road_closure"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["state_version"] == 2
        assert body["applied_events"] == ["wind_shift_road_closure"]


def test_events_inject_rejects_a_name_outside_the_catalog():
    # The request schema's Literal already restricts `event` to the 4 known names (§8.2) --
    # FastAPI's own request validation rejects anything else with 422 before this reaches
    # the handler at all.
    with TestClient(create_app(negotiation_script={})) as client:
        run_id = _reset(client)
        response = client.post(
            "/events/inject",
            json={"run_id": run_id, "expected_state_version": 0, "event": "not-a-real-event"},
        )
    assert response.status_code == 422


def test_proposals_unknown_dp_returns_404():
    with TestClient(create_app(negotiation_script={})) as client:
        run_id = _reset(client)
        client.post("/negotiate", json={"run_id": run_id, "expected_state_version": 0})
        response = client.get("/proposals", params={"dp_id": "dp-999"})
    assert response.status_code == 404
