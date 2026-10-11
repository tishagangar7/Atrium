"""PRD §8.2 GET /health."""

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_no_live_provider_yet():
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "model_available": False,
        "provider": None,
        "mode": "live",
    }


def test_health_labels_guarded_test_provider(monkeypatch):
    monkeypatch.setenv("RESCUEMESH_TEST", "1")
    monkeypatch.setenv("RESCUEMESH_PROVIDER", "fake")
    body = TestClient(create_app()).get("/health").json()
    assert body["model_available"] is True
    assert body["provider"] == "TEST PROVIDER"


def test_health_refuses_unguarded_fake_provider(monkeypatch):
    monkeypatch.delenv("RESCUEMESH_TEST", raising=False)
    monkeypatch.setenv("RESCUEMESH_PROVIDER", "fake")
    body = TestClient(create_app()).get("/health").json()
    assert body["model_available"] is False
    assert body["provider"] is None
