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
        completed = service.rsi_store.get(started['id'], 'alice', agent, 'run')
        assert completed['status'] == 'completed' and completed['stage'] == 'result_completed'
        assert completed['resumable'] is False
        assert 'exit_reason' not in completed
        root = service.runtime_root / 'rsi' / started['id']
        with (root/'audit.jsonl').open() as stream:
            operation = json.loads(next(stream))['data']
        assert operation['package']['manifest']['agents'] == before.model_dump(mode='json')['manifest']['agents']
        assert operation['package']['files'] == before.model_dump(mode='json')['files']
        assert (await service._agent_bundle(await service._agent(agent, 'alice'))).model_dump(mode='json') == before.model_dump(mode='json')
        assert 'reviewer' not in operation['internal_agents']
        assert 'suite_reviewer' not in operation['internal_agents']
        for role in ('evaluator','tuner','test_designer'):
            item = operation['internal_agents'][role]
            instructions = item['package']['manifest']['agents'][item['agent_id']]['instructions']['inline']
            assert 'Host target execution semantics:' in instructions
            assert 'sage.agent.continuation.deterministic' in instructions
            assert 'separate tool/model steps are not separate user turns' in instructions
            assert 'Use reusable improvements' not in instructions
            if role == 'tuner':
                assert 'Use training evidence to improve' in instructions
            elif role == 'evaluator':
                assert 'Independently grade or diagnose' in instructions
            else:
                assert 'Design only the requested test cases' in instructions
    finally:
        await service.close()
