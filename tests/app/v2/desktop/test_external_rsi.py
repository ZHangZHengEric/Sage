import json
from types import SimpleNamespace

import pytest

from app.v2.cli.rsi_visibility import review_view
from app.v2.desktop.backend.catalog import DesktopAgentRecord
from app.v2.desktop.backend.rsi import DesktopRsiMixin, RsiStore
from examples.v2.desktop_optimization_mirror import DesktopOptimizationMirror
from tests.sagents.v2.test_package_optimizer import bundle


@pytest.mark.asyncio
async def test_external_training_workspace_registration_uses_desktop_api_and_keeps_credentials_private(tmp_path, monkeypatch):
    import httpx

    owner = DesktopAgentRecord(agent_id='agent', user_id='owner', name='Experiment')
    mirror = DesktopOptimizationMirror(tmp_path, owner, goal='Improve', rounds=4,
        validation_count=3, repeats=2, concurrency=6, scope=('instructions',), test_count=0,
        input_visibility='opaque_fixture')
    assert mirror.value['input_visibility'] == 'opaque_fixture'
    workspace = tmp_path / 'experiment/workspace'
    (tmp_path / 'desktop-v2-sidecar.json').write_text(json.dumps({
        'host': '127.0.0.1', 'port': 1234, 'auth_token': 'private-workspace-token'}))
    def respond(request):
        assert request.url.path == '/api/v2/projects'
        assert request.headers['Authorization'] == 'Bearer private-workspace-token'
        assert json.loads(request.content)['path'] == str(workspace)
        return httpx.Response(200, json={'data': {'id': 'project-test', 'path': str(workspace)}})
    client_type = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
        client_type(transport=httpx.MockTransport(respond), **kwargs))
    await mirror.register_workspace(workspace)
    assert mirror.value['workspace_id'] == 'project-test'
    assert 'private-workspace-token' not in json.dumps(mirror.value)
    (tmp_path / 'desktop-v2-sidecar.json').unlink()
    await mirror.register_workspace(workspace)
    assert mirror.value['workspace_registration_error'] == 'FileNotFoundError'
    assert mirror.value['status'] == 'running'


@pytest.mark.asyncio
async def test_external_host_events_and_human_scores_are_visible_without_resetting_other_runs(tmp_path):
    store = RsiStore(tmp_path / 'rsi.sqlite3')
    store.put({'id': 'other', 'status': 'running'}, 'another-user', 'another-agent', 'run')
    owner = DesktopAgentRecord(agent_id='agent', user_id='owner', name='Experiment')
    mirror = DesktopOptimizationMirror(tmp_path, owner, goal='Improve tasks', rounds=8,
        validation_count=24, repeats=3, concurrency=6, scope=('instructions', 'skills', 'tools'), test_count=40)
    assert store.get('other', 'another-user', 'another-agent', 'run')['status'] == 'running'
    event = {'sequence': 1, 'event': 'operation_started', 'timestamp': 'now',
             'data': {'package': bundle().model_dump(mode='json')}}
    mirror.observe(event)
    reopened = RsiStore(tmp_path / 'rsi.sqlite3')
    assert reopened.get(mirror.run_id, 'owner', 'agent', 'run')['status'] == 'running'
    assert reopened.external_active()
    records = [{'round': 0, 'scores': {'training': .5, 'validation': .6, 'test': .7},
                'cases': [{'input': 'HUMAN-ONLY-TEST'}]}]
    mirror.tests(records)
    service = SimpleNamespace(runtime_root=tmp_path, rsi_store=store, _rsi_cursors={}, _rsi_usage_readers={})
    async def agent(agent_id, user_id):
        assert (agent_id, user_id) == ('agent', 'owner')
        return owner
    service._agent = agent
    displayed = await DesktopRsiMixin.rsi_run(service, 'agent', mirror.run_id, 'owner')
    assert displayed['events'] == [event]
    assert displayed['test_observations'] == records
    assert len(displayed['iterations']) == 1
    assert not store.get(mirror.run_id + '.0', 'owner', 'agent', 'version')['ready']
    mirror.observe({'sequence': 2, 'event': 'agent_call_started', 'data': {
        'call_id': 'summary', 'role': 'evaluation', 'activity': 'diagnosis_summary', 'round': 1}})
    phase = store.get(mirror.run_id, 'owner', 'agent', 'run')
    assert phase['role'] == 'evaluation' and phase['activity'] == 'diagnosis_summary'
    mirror.finish({'candidate': {'pass^1': .9}})
    public = store.get(mirror.run_id, 'owner', 'agent', 'run')
    assert public['status'] == 'completed'
    private_view = json.dumps(review_view(public))
    assert 'HUMAN-ONLY-TEST' not in private_view and 'benchmark_measurement' not in private_view
    assert store.list('another-user', 'agent', 'run') == []


def test_backfill_attaches_only_terminal_empty_test_run_and_preserves_result_and_versions(tmp_path):
    owner = DesktopAgentRecord(agent_id='agent', user_id='owner', name='Experiment')
    mirror = DesktopOptimizationMirror(tmp_path, owner, goal='Improve', rounds=2,
        validation_count=3, repeats=2, concurrency=3, scope=('instructions',), test_count=0)
    with pytest.raises(ValueError):
        DesktopOptimizationMirror.for_completed_tests(tmp_path, owner, mirror.run_id, 6)
    mirror.version(0, bundle().model_dump(mode='json'))
    mirror.finish()
    before = mirror.store.get(f'{mirror.run_id}.0', 'owner', 'agent', 'version')
    attached = DesktopOptimizationMirror.for_completed_tests(tmp_path, owner, mirror.run_id, 6)
    attached.tests([{'round': 0, 'scores': {'test': .5}}])
    assert attached.value['status'] == 'completed'
    assert attached.store.get(f'{mirror.run_id}.0', 'owner', 'agent', 'version') == before
    with pytest.raises(ValueError):
        DesktopOptimizationMirror.for_completed_tests(tmp_path, owner, mirror.run_id, 6)


def test_external_resume_keeps_run_identity_and_monotonic_events(tmp_path):
    owner = DesktopAgentRecord(agent_id='agent', user_id='owner', name='Experiment')
    mirror = DesktopOptimizationMirror(tmp_path, owner, goal='Improve', rounds=8,
        validation_count=12, repeats=3, concurrency=3, scope=('instructions',), test_count=6)
    package = bundle()
    original = {'sequence': 1, 'event': 'operation_started', 'data': {'package': package.model_dump(mode='json')}}
    mirror.observe(original)
    mirror.finish(error=RuntimeError('temporary'))
    restored = DesktopOptimizationMirror.for_resume(tmp_path, owner, mirror.run_id, package.content_hash)
    restored.observe({'sequence': 1, 'event': 'suite_fixed', 'data': {'round': 0}})
    assert restored.run_id == mirror.run_id and restored.value['status'] == 'running'
    assert [json.loads(line)['sequence'] for line in restored.journal.read_text().splitlines()] == [1, 2]
    assert original['sequence'] == 1
    assert restored.value['resume_history'][0]['previous_error'] == 'RuntimeError'
