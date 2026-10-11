"""PRD §8.3/§8.4 SSE hello stream (queue item C1/T06). Fixture, not live agent output
(AGENTS.md invariant 8) -- app.run (C2) replaces the fixture source."""

import json

from fastapi.testclient import TestClient

from app.main import HELLO_STREAM_FIXTURE, create_app


def _parse_sse_data_events(body: str) -> list[dict]:
    events = []
    for block in body.strip().split("\n\n"):
        data_lines = [line[len("data: "):] for line in block.splitlines() if line.startswith("data: ")]
        if data_lines:
            events.append(json.loads("".join(data_lines)))
    return events


def test_hello_stream_replays_fixture_in_order():
    client = TestClient(create_app())
    with client.stream("GET", "/events/stream") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"
        body = "".join(response.iter_text())

    fixture = json.loads(HELLO_STREAM_FIXTURE.read_text())
    assert _parse_sse_data_events(body) == fixture


def test_hello_stream_resumes_after_last_event_id():
    client = TestClient(create_app())
    with client.stream(
        "GET", "/events/stream", headers={"Last-Event-ID": "run-fixture-hello-s1:1"}
    ) as response:
        body = "".join(response.iter_text())

    events = _parse_sse_data_events(body)
    assert [e["seq"] for e in events] == [2]
    assert events[0]["type"] == "state.snapshot"
