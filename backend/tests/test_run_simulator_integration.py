"""Real simulator transport: PRD §8, AC-014 determinism, AC-012 replay/reset."""
import pytest
from fastapi.testclient import TestClient
from app import store
from app.main import create_app
from app.sim.service import SimulatorService

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'RUNS_DIR', tmp_path / 'runs')
    with TestClient(create_app()) as client:
        yield client

def reset(client, preset='normal'):
    response = client.post(f'/scenarios/{preset}/reset', json={'seed': 1})
    assert response.status_code == 200
    return response.json()

def step(client, initial, **kwargs):
    return client.post('/simulation/step', json={
        'run_id': initial['run_id'], 'expected_state_version': initial['state_version'], **kwargs})

@pytest.mark.parametrize('preset', ['normal', 'wind_shift', 'road_closure', 'compound_failure'])
def test_reset_real_presets_matches_simulator(client, preset):
    initial = reset(client, preset)
    direct = SimulatorService(preset, 1, initial['run_id'])
    assert initial['snapshot']['world'] == direct.world.model_dump(mode='json')
    assert initial['snapshot']['evidence_holders'] == direct.evidence_holders()
    assert len(initial['snapshot']['world']['cells']) == 60

def test_ac014_steps_match_real_engine_and_persist_snapshot(client):
    initial = reset(client)
    direct = SimulatorService('normal', 1, initial['run_id'])
    direct.step(10)
    assert step(client, initial, steps=10).status_code == 200
    snapshot = client.get('/state').json()
    assert snapshot['world'] == direct.world.model_dump(mode='json')
    assert snapshot['world']['cells'] != initial['snapshot']['world']['cells']
    events = client.get(f"/runs/{initial['run_id']}/events").json()
    assert events[-1]['type'] == 'state.snapshot'
    assert events[-1]['data'] == snapshot
    assert events[-1]['seq'] == snapshot['last_seq']
    assert [e['seq'] for e in events] == list(range(1, len(events) + 1))

def test_scheduled_event_pauses_and_rejects_old_version(client):
    initial = reset(client, 'road_closure')
    result = step(client, initial, until='next_event')
    assert result.status_code == 200
    assert result.json() == {'step': 15, 'state_version': 1, 'paused': True}
    assert client.get('/state').json()['world']['roads']['R3']['status_override'] == 'CLOSED_HARD'
    assert step(client, initial, steps=1).status_code == 409
    events = client.get(f"/runs/{initial['run_id']}/events").json()
    assert any(e['type'] == 'event.applied' for e in events)

def test_horizon_stops_early_at_disruption(client):
    initial = reset(client, 'compound_failure')
    assert step(client, initial, until='horizon').json() == {
        'step': 15, 'state_version': 4, 'paused': True}

def test_normal_horizon_is_bounded(client):
    initial = reset(client)
    assert step(client, initial, until='horizon').json()['step'] == 60
    assert step(client, initial, steps=60).json()['step'] == 60

def test_ac012_replay_rehydrates_latest_real_snapshot(client):
    initial = reset(client)
    step(client, initial, steps=10)
    before = client.get('/state').json()['world']
    replay_id = client.post(f"/replay/{initial['run_id']}", json={'speed': 4}).json()['run_id']
    after = client.get('/state').json()
    assert after['mode'] == 'replay'
    assert after['world'] == {**before, 'run_id': replay_id}
    assert step(client, {'run_id': replay_id, 'state_version': 0}, steps=1).status_code == 409

def test_invalid_step_count_does_not_mutate(client):
    initial = reset(client)
    for count in (0, -1, 61):
        assert step(client, initial, steps=count).status_code == 422
    assert client.get('/state').json() == initial['snapshot']

def test_real_preset_negotiation_starts_on_authoritative_world(client, monkeypatch):
    monkeypatch.setenv('RESCUEMESH_TEST', '1')
    monkeypatch.setenv('RESCUEMESH_PROVIDER', 'fake')
    initial = reset(client)
    response = client.post('/negotiate', json={
        'run_id': initial['run_id'], 'expected_state_version': 0})
    assert response.status_code == 202
    assert response.json()['dp_id'] == 'dp-1'
