"""PRD §8 C4: negotiation, injection and replay share the authoritative world."""
import time
import pytest
from fastapi.testclient import TestClient
from app import store
from app.main import create_app
from tests.test_negotiate import COMMIT_SCRIPT

@pytest.fixture(autouse=True)
def fake_provider(monkeypatch, tmp_path):
    monkeypatch.setenv('RESCUEMESH_TEST', '1')
    monkeypatch.setenv('RESCUEMESH_PROVIDER', 'fake')
    monkeypatch.setattr(store, 'RUNS_DIR', tmp_path / 'runs')

def _wait(client, run_id, event_type):
    for _ in range(120):
        events = client.get('/events', params={'run_id': run_id}).json()
        if any(e['type'] == event_type for e in events):
            return events
        time.sleep(.01)
    raise AssertionError(f'{event_type} missing')

def test_real_commit_changes_same_world_and_persists_snapshot():
    with TestClient(create_app(negotiation_script=COMMIT_SCRIPT)) as client:
        initial = client.post('/scenarios/normal/reset', json={'seed': 1}).json()
        run_id = initial['run_id']
        assert client.post('/negotiate', json={'run_id': run_id, 'expected_state_version': 0}).status_code == 202
        events = _wait(client, run_id, 'plan.committed')
        committed = next(e for e in events if e['type'] == 'plan.committed')
        assert committed['data']['authority'] == 'unanimous'
        assert committed['data']['state_version_before'] == 0
        world = client.get('/state').json()['world']
        assert world['committed_plan_hash'] == committed['data']['plan_hash']
        assert world['state_version'] == 1
        assert client.get('/state').json()['negotiation_status'] == 'committed'
        assert any(e['type'] == 'state.snapshot' and e['data']['world']['state_version'] == 1 for e in events)
        moved = client.post('/simulation/step', json={
            'run_id': run_id, 'expected_state_version': 1, 'steps': 3})
        assert moved.status_code == 200
        assert client.get('/state').json()['world']['step'] == 3

def test_inject_changes_authority_and_rejects_stale_version():
    with TestClient(create_app(negotiation_script={})) as client:
        initial = client.post('/scenarios/normal/reset', json={'seed': 1}).json()
        run_id = initial['run_id']
        changed = client.post('/events/inject', json={
            'run_id': run_id, 'expected_state_version': 0,
            'event': 'wind_shift_road_closure', 'auto_negotiate': False})
        assert changed.status_code == 200
        assert changed.json()['state_version'] == 2
        world = client.get('/state').json()['world']
        assert world['wind'] == {'direction': 'SE', 'speed': 3}
        assert world['roads']['R3']['status_override'] == 'CLOSED_HARD'
        assert client.post('/events/inject', json={
            'run_id': run_id, 'expected_state_version': 0,
            'event': 'road_closure', 'auto_negotiate': False}).status_code == 409
        events = client.get('/events', params={'run_id': run_id}).json()
        assert len([e for e in events if e['type'] == 'event.applied']) == 2
        assert events[-1]['data']['world'] == world


def test_injection_cancels_old_round_and_starts_new_version():
    with TestClient(create_app(negotiation_script={}, negotiation_delay_s=.15)) as client:
        run_id = client.post('/scenarios/normal/reset', json={'seed': 1}).json()['run_id']
        first = client.post('/negotiate', json={'run_id': run_id, 'expected_state_version': 0})
        assert first.status_code == 202
        changed = client.post('/events/inject', json={
            'run_id': run_id, 'expected_state_version': 0, 'event': 'road_closure'})
        assert changed.status_code == 200
        assert changed.json()['state_version'] == 1
        events = _wait(client, run_id, 'negotiation.cancelled')
        for _ in range(100):
            events = client.get('/events', params={'run_id': run_id}).json()
            if any(e['type'] == 'negotiation.started' and e['data']['state_version'] == 1 for e in events):
                break
            time.sleep(.01)
        assert any(e['type'] == 'negotiation.started' and e['data']['state_version'] == 1 for e in events)
        assert not any(e['type'] == 'plan.committed' and e['data']['state_version_before'] == 0 for e in events)

def test_replay_rejects_negotiation_and_injection():
    with TestClient(create_app(negotiation_script={})) as client:
        run_id = client.post('/scenarios/normal/reset', json={'seed': 1}).json()['run_id']
        replay_id = client.post(f'/replay/{run_id}', json={'speed': 4}).json()['run_id']
        assert client.post('/negotiate', json={
            'run_id': replay_id, 'expected_state_version': 0}).status_code == 409
        assert client.post('/events/inject', json={
            'run_id': replay_id, 'expected_state_version': 0,
            'event': 'wind_shift'}).status_code == 409


def test_real_escalation_fallback_updates_authority_and_snapshot():
    with TestClient(create_app(negotiation_script={})) as client:
        run_id = client.post('/scenarios/normal/reset', json={'seed': 1}).json()['run_id']
        dp_id = client.post('/negotiate', json={
            'run_id': run_id, 'expected_state_version': 0}).json()['dp_id']
        _wait(client, run_id, 'escalation.opened')
        before = client.get('/state').json()
        assert before['negotiation_status'] == 'escalated'
        assert before['escalation']['dp_id'] == dp_id
        resolved = client.post(f'/escalations/{dp_id}/resolve', json={
            'run_id': run_id, 'expected_state_version': 0, 'choice': 'fallback'})
        assert resolved.status_code == 200
        commit = resolved.json()['commit']
        assert commit['authority'] == 'human_choice'
        after = client.get('/state').json()
        assert after['world']['state_version'] == 1
        assert after['world']['committed_plan_hash'] == commit['plan_hash']


def test_ac012_full_commit_disruption_replay_preserves_final_world():
    """A recorded real-world commit and disruption replay to the same final state."""
    with TestClient(create_app(negotiation_script=COMMIT_SCRIPT)) as client:
        initial = client.post('/scenarios/normal/reset', json={'seed': 1}).json()
        run_id = initial['run_id']
        assert client.post('/negotiate', json={
            'run_id': run_id, 'expected_state_version': 0,
        }).status_code == 202
        _wait(client, run_id, 'plan.committed')
        assert client.post('/simulation/step', json={
            'run_id': run_id, 'expected_state_version': 1, 'steps': 3,
        }).status_code == 200
        changed = client.post('/events/inject', json={
            'run_id': run_id, 'expected_state_version': 1,
            'event': 'road_closure', 'auto_negotiate': False,
        })
        assert changed.status_code == 200
        live = client.get('/state').json()
        assert live['world']['roads']['R3']['status_override'] == 'CLOSED_HARD'

        replay = client.post(f'/replay/{run_id}', json={'speed': 4})
        assert replay.status_code == 200
        replay_id = replay.json()['run_id']
        replayed = client.get('/state').json()
        assert replayed['mode'] == 'replay'
        assert replayed['world'] == {**live['world'], 'run_id': replay_id}
        events = client.get('/events', params={'run_id': replay_id}).json()
        assert all(event['mode'] == 'replay' for event in events)
        assert any(event['type'] == 'plan.committed' for event in events)
        assert any(event['type'] == 'event.applied' for event in events)
