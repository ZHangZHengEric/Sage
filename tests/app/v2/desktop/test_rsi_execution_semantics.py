import json
import pytest
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request

@pytest.mark.asyncio
async def test_host_execution_semantics_reach_internal_roles_without_changing_baseline(tmp_path, monkeypatch):
    service, agent = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        before = await service._agent_bundle(await service._agent(agent, 'alice'))
        started = await service.start_rsi(agent, start_request(), 'alice')
        await service._rsi_tasks[started['id']]
        root = service.runtime_root / 'rsi' / started['id']
        with (root/'audit.jsonl').open() as stream:
            operation = json.loads(next(stream))['data']
        assert operation['package']['manifest']['agents'] == before.model_dump(mode='json')['manifest']['agents']
        assert operation['package']['files'] == before.model_dump(mode='json')['files']
        assert (await service._agent_bundle(await service._agent(agent, 'alice'))).model_dump(mode='json') == before.model_dump(mode='json')
        for role in ('evaluator','tuner','reviewer','suite_reviewer'):
            item = operation['internal_agents'][role]
            instructions = item['package']['manifest']['agents'][item['agent_id']]['instructions']['inline']
            assert 'Host target execution semantics:' in instructions
            assert 'sage.agent.continuation.deterministic' in instructions
            assert 'separate tool/model steps are not separate user turns' in instructions
    finally:
        await service.close()
