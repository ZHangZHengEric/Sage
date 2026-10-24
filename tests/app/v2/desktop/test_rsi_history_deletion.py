"""Human-owned history deletion preserves experiment evidence and versions."""
import asyncio

import httpx
import pytest

from app.v2.desktop.backend.app import create_app
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service


def record(service, agent, identity, status='failed'):
    value = {'id': identity, 'status': status, 'goal': 'Archived failed experiment',
        'created_at': '2026-10-23T12:00:00Z', 'rounds': 8, 'iteration': 0,
        'dataset_manifest': {'active_count': 18, 'exclusions': []}}
    service.rsi_store.put(value, 'alice', agent, 'run')
    return value


@pytest.mark.asyncio
async def test_delete_history_is_scoped_idempotent_and_retains_frozen_data_and_versions(tmp_path, monkeypatch):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        before = record(service, agent, 'old-run')
        version = {'id': 'old-run.0', 'run_id': 'old-run', 'iteration': 0, 'source': 'rsi', 'created_at': before['created_at']}
        service.rsi_store.put(version, 'alice', agent, 'version')
        folder = service.runtime_root / 'rsi' / 'old-run'
        folder.mkdir(parents=True)
        evidence = folder / 'audit.jsonl'
        evidence.write_text('immutable original evidence\n')
        with pytest.raises(ValueError):
            await service.delete_rsi_run(agent, 'old-run', 'bob')
        assert not service.rsi_store.get('old-run', 'alice', agent, 'run').get('deleted_at')
        result = await service.delete_rsi_run(agent, 'old-run', 'alice')
        assert result == {'id': 'old-run', 'deleted': True}
        deleted = service.rsi_store.get('old-run', 'alice', agent, 'run')
        assert deleted['deleted_by'] == 'alice' and deleted['deleted_at']
        assert deleted['dataset_manifest'] == before['dataset_manifest']
        assert all(deleted[key] == value for key, value in before.items())
        assert evidence.read_text() == 'immutable original evidence\n'
        assert service.rsi_store.get('old-run.0', 'alice', agent, 'version') == version
        assert not (await service.rsi_history(agent, 'alice'))['runs']
        await service.delete_rsi_run(agent, 'old-run', 'alice')
        assert service.rsi_store.get('old-run', 'alice', agent, 'run') == deleted
        for resume in (service.resume_rsi, service.resume_rsi_tests):
            with pytest.raises(ValueError, match='deleted from history'):
                await resume(agent, 'old-run', 'alice')
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['queued', 'running'])
async def test_delete_history_refuses_active_experiments(tmp_path, monkeypatch, status):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        before = record(service, agent, 'active-run', status)
        with pytest.raises(ValueError, match='Stop the running experiment'):
            await service.delete_rsi_run(agent, 'active-run', 'alice')
        assert service.rsi_store.get('active-run', 'alice', agent, 'run') == before
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_delete_history_checks_live_task_and_http_authentication(tmp_path, monkeypatch):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    monkeypatch.setattr('app.v2.desktop.backend.app.get_desktop_user_id', lambda request: 'alice')
    try:
        record(service, agent, 'race-run')
        task = asyncio.create_task(asyncio.Event().wait())
        service._rsi_tasks['race-run'] = task
        app = create_app(service=service, auth_token='human-only')
        path = f'/api/v2/agents/{agent}/rsi/runs/race-run'
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            assert (await client.delete(path)).status_code == 401
            headers = {'Authorization': 'Bearer human-only'}
            response = await client.delete(path, headers=headers)
            assert response.status_code == 400 and 'Stop the running experiment' in response.text
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            response = await client.delete(path, headers=headers)
            assert response.status_code == 200 and response.json()['data']['deleted'] is True
            response = await client.get(f'/api/v2/agents/{agent}/rsi', headers=headers)
            assert response.json()['data']['runs'] == []
    finally:
        await service.close()
