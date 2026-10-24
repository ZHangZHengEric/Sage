import json
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from app.v2.desktop.backend.catalog import DesktopMcpRecord
from app.v2.desktop.backend.schemas import AgentSettingsPatch
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.optimization.dataset import OptimizationDataset
from sagents.v2.optimization.environment import CASE_CONTEXT_ENV, CASE_PROTOCOL, ISOLATION_ENV
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request


@pytest.mark.asyncio
async def test_standard_desktop_rsi_runs_mcp_cases_without_a_dataset_specific_host(tmp_path, monkeypatch):
    observed = []
    class Session:
        def __init__(self, config):
            self.config = config
        async def list_tools(self):
            return {'tools': [{'name': 'increment', 'description': 'Increment isolated test state',
                'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]}
        async def call_tool(self, name, arguments):
            context = json.loads(Path(self.config.env[CASE_CONTEXT_ENV]).read_text())
            state = Path(context['state_directory']) / 'count'
            state.parent.mkdir(parents=True, exist_ok=True)
            value = int(state.read_text()) + 1 if state.exists() else 1
            state.write_text(str(value))
            observed.append((context['case_id'], value))
            return {'content': [{'type': 'text', 'text': str(value)}], 'isError': False}
    @asynccontextmanager
    async def session(config):
        yield Session(config)
    monkeypatch.setattr('sagents.v2.tool.plugins.mcp._sdk_session', session)
    class Model(RsiModel):
        async def _stream(self, request):
            if any(t.name == 'mcp_simulation_increment' for t in request.tools) and not any(m.role == 'tool' for m in request.messages):
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                    response_id='increment', finish_reason='tool_calls', tool_calls=(ModelToolCall(
                        tool_call_id='increment', name='mcp_simulation_increment', arguments={}),)))
                return
            async for event in super()._stream(request):
                yield event
    service, agent = await setup_service(tmp_path, monkeypatch, Model())
    try:
        await service.catalog.save_mcp(DesktopMcpRecord(user_id='alice', name='simulation', protocol='stdio',
            command='python', env={ISOLATION_ENV: CASE_PROTOCOL}))
        await service.patch_agent_settings(agent, AgentSettingsPatch(available_tools=['mcp_simulation_increment']), 'alice')
        original = (await service._agent(agent, 'alice')).config
        request = start_request().model_copy(update={'rounds': 1, 'grow_training': False, 'suite': None,
            'dataset': OptimizationDataset(name='Counter', cases=start_request().suite.cases,
                environment={'mcp_servers': ['simulation']})})
        started = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent, started['id'], 'alice')
        assert run['status'] == 'completed', run.get('error')
        assert {case for case, value in observed} == {'training', 'validation'}
        assert len(observed) >= 4 and all(value == 1 for case, value in observed)
        assert (await service._agent(agent, 'alice')).config == original
        assert run['environment_fingerprint']
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_bound_environment_terminal_result_ends_target_before_another_model_call(tmp_path, monkeypatch):
    observed = []
    class Session:
        async def list_tools(self):
            return {'tools': [{'name': 'step', 'description': 'Advance official simulation',
                'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}}]}
        async def call_tool(self, name, arguments):
            observed.append(name)
            return {'content': [{'type': 'text', 'text': json.dumps({'done': True})}], 'isError': False}
    @asynccontextmanager
    async def session(config):
        yield Session()
    monkeypatch.setattr('sagents.v2.tool.plugins.mcp._sdk_session', session)
    class Model(RsiModel):
        async def _stream(self, request):
            if any(t.name == 'mcp_simulation_step' for t in request.tools):
                assert not any(m.role == 'tool' for m in request.messages), 'Target must not call the model after done'
                yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                    response_id='step', finish_reason='tool_calls', tool_calls=(ModelToolCall(
                        tool_call_id='step', name='mcp_simulation_step', arguments={}),)))
                return
            async for event in super()._stream(request):
                yield event
    service, agent = await setup_service(tmp_path, monkeypatch, Model())
    try:
        await service.catalog.save_mcp(DesktopMcpRecord(user_id='alice', name='simulation', protocol='stdio',
            command='python', env={ISOLATION_ENV: CASE_PROTOCOL}))
        await service.patch_agent_settings(agent, AgentSettingsPatch(available_tools=['mcp_simulation_step']), 'alice')
        cases = start_request().suite.cases
        sealed = cases[0].model_copy(update={'id': 'sealed', 'input': 'A separate held-out task', 'split': 'test'})
        request = start_request().model_copy(update={'rounds': 1, 'grow_training': False, 'suite': None,
            'human_test_count': 1,
            'dataset': OptimizationDataset(name='Terminal simulation', cases=(*cases, sealed),
                environment={'mcp_servers': ['simulation'], 'terminal_on_done': True})})
        started = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[started['id']]
        run = await service.rsi_run(agent, started['id'], 'alice')
        assert run['status'] == 'completed', run.get('error_type')
        assert observed
        assert run['test_observations']
        assert all(record['status'] == 'completed' for record in run['test_observations'])
        audit = (service.runtime_root/'rsi'/started['id']/'audit.jsonl').read_text()
        assert 'rsi_case_terminal' in audit
    finally:
        await service.close()
