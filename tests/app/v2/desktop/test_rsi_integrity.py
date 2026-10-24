"""Temporary stores and mocked admission; never start a live RSI experiment."""
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace

import pytest

from app.v2.desktop.backend.rsi import DesktopRsiMixin, RsiStore
from app.v2.desktop.backend.rsi_evaluation import ScorerImport, EvaluationPlan
from tests.sagents.v2.test_python_scorer import request as scoring_request


class Host(DesktopRsiMixin):
    def __init__(self, root):
        self.runtime_root = root
        self.rsi_store = RsiStore(root / 'rsi.sqlite3')
    async def _agent(self, identity, owner):
        return SimpleNamespace(agent_id=identity, user_id=owner)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['scorer', 'evaluation_plan'])
@pytest.mark.parametrize('second_owner', [('alice', 'agent-B'), ('bob', 'agent-A')])
async def test_identical_imports_preserve_each_owner(tmp_path, kind, second_owner):
    host = Host(tmp_path)
    if kind == 'scorer':
        fixture = {'request': scoring_request().model_dump(mode='json'), 'expected_score': 1, 'expected_passed': True}
        value = ScorerImport(name='shared.py', source="def score(request):\n return {'score': 1, 'passed': True, 'rationale': 'fixed'}\nSCORER_TEST_CASES = " + repr([fixture]))
        operation = host.import_rsi_scorer
    else:
        value, operation = EvaluationPlan(name='shared'), host.import_rsi_evaluation_plan
    first = await operation('agent-A', value, 'alice')
    owner, agent = second_owner
    second = await operation(agent, value, owner)
    assert first['id'] != second['id']
    assert host.rsi_store.get(first['id'], 'alice', 'agent-A', kind)
    assert host.rsi_store.get(second['id'], owner, agent, kind)
    assert await operation('agent-A', value, 'alice') == first


def test_store_never_replaces_another_owner_even_with_a_legacy_id(tmp_path):
    store = RsiStore(tmp_path / 'rsi.sqlite3')
    original = {'id': 'legacy-shared', 'name': 'first'}
    store.put(original, 'alice', 'agent-A', 'scorer')
    with pytest.raises(ValueError, match='another owner'):
        store.put({'id': 'legacy-shared', 'name': 'replacement'}, 'bob', 'agent-B', 'scorer')
    assert store.get('legacy-shared', 'alice', 'agent-A', 'scorer') == original


def test_live_owner_survives_reopening_and_pid_reuse_is_detected(tmp_path):
    store = RsiStore(tmp_path / 'rsi.sqlite3')
    store.put({'id': 'live', 'status': 'running'}, 'alice', 'agent-A', 'run')
    second = RsiStore(tmp_path / 'rsi.sqlite3')
    assert second.get('live', 'alice', 'agent-A', 'run')['status'] == 'running'
    assert '_host_owner' not in second.get('live', 'alice', 'agent-A', 'run')
    with store.connect() as db:
        db.execute("UPDATE records SET body=json_set(body, '$._host_owner.started', 0) WHERE id='live'")
    reopened = RsiStore(tmp_path / 'rsi.sqlite3')
    assert reopened.get('live', 'alice', 'agent-A', 'run')['status'] == 'interrupted'


def test_other_live_host_cannot_cancel_or_overwrite_owned_run(tmp_path, monkeypatch):
    store = RsiStore(tmp_path / 'rsi.sqlite3')
    store.put({'id': 'live', 'status': 'running'}, 'alice', 'agent-A', 'run')
    second = RsiStore(tmp_path / 'rsi.sqlite3')
    second.owner = {**store.owner, 'started': store.owner['started'] + 1}
    with pytest.raises(PermissionError, match='another live host'):
        second.put({'id': 'live', 'status': 'cancelled'}, 'alice', 'agent-A', 'run')
    assert store.get('live', 'alice', 'agent-A', 'run')['status'] == 'running'


def test_live_legacy_sidecar_blocks_recovery_and_writes(tmp_path, monkeypatch):
    store = RsiStore(tmp_path / 'rsi.sqlite3', recover_interrupted=False)
    with store.connect() as db:
        body = json.dumps({'id': 'legacy-live', 'status': 'running'})
        db.execute('INSERT INTO records(id,user,agent,kind,body,summary) VALUES(?,?,?,?,?,?)',
            ('legacy-live', 'alice', 'agent-A', 'run', body, body))
    monkeypatch.setattr('app.v2.desktop.backend.rsi.legacy_sidecar_alive', lambda _: True)
    other = RsiStore(tmp_path / 'rsi.sqlite3')
    assert other.get('legacy-live', 'alice', 'agent-A', 'run')['status'] == 'running'
    with pytest.raises(PermissionError):
        other.put({'id': 'legacy-live', 'status': 'interrupted'}, 'alice', 'agent-A', 'run')


@pytest.mark.asyncio
async def test_plan_keeps_environment_through_admission_without_executing(tmp_path, monkeypatch):
    from app.v2.desktop.backend.catalog import DesktopMcpRecord
    from app.v2.desktop.backend.schemas import AgentSettingsPatch
    from sagents.v2.optimization.dataset import OptimizationDataset
    from sagents.v2.optimization.environment import ISOLATION_ENV, CASE_PROTOCOL
    from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request
    model = RsiModel()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    class Admitted(Exception):
        pass
    try:
        class Session:
            async def list_tools(self):
                return {'tools': [{'name': 'increment', 'description': 'mock', 'inputSchema': {'type': 'object', 'properties': {}}}]}
        @asynccontextmanager
        async def session(config):
            yield Session()
        monkeypatch.setattr('sagents.v2.tool.plugins.mcp._sdk_session', session)
        await service.catalog.save_mcp(DesktopMcpRecord(user_id='alice', name='simulation', protocol='stdio',
            command='never-executed', env={ISOLATION_ENV: CASE_PROTOCOL}))
        await service.patch_agent_settings(agent, AgentSettingsPatch(available_tools=['mcp_simulation_increment']), 'alice')
        dataset = OptimizationDataset(name='Counter', cases=start_request().suite.cases,
            environment={'mcp_servers': ['simulation']})
        plan = await service.import_rsi_evaluation_plan(agent, EvaluationPlan(name='Counter plan', dataset=dataset), 'alice')
        observed = []
        original = service._rsi_case_environment
        async def inspect(request, owner):
            observed.append(request.dataset.environment if request.dataset else None)
            return await original(request, owner)
        async def stop_before_job(*args, **kwargs):
            raise Admitted()
        monkeypatch.setattr(service, '_rsi_case_environment', inspect)
        monkeypatch.setattr(service, '_record_agent_version', stop_before_job)
        request = start_request().model_copy(update={'suite': None, 'evaluation_plan_id': plan['id']})
        with pytest.raises(Admitted):
            await service.start_rsi(agent, request, 'alice')
        assert observed and all(binding == dataset.environment for binding in observed)
        assert not model.requests and not service._rsi_tasks
    finally:
        await service.close()
