import json

import pytest

from app.v2.desktop.backend.rsi import RsiStart
from sagents.v2 import BuiltinScoring
from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request


class UsageModel(RsiModel):
    async def _stream(self, request):
        from sagents.v2.contracts.items import UsageSummary
        async for event in super()._stream(request):
            if event.response is not None:
                event = event.model_copy(update={'response': event.response.model_copy(update={
                    'usage': UsageSummary(reported=True, input_tokens=20, output_tokens=10,
                                          cached_input_tokens=5, reasoning_tokens=2)})})
            yield event


@pytest.mark.asyncio
async def test_builtin_selection_is_frozen_and_reaches_native_optimizer(tmp_path, monkeypatch):
    service, agent_id = await setup_service(tmp_path, monkeypatch, UsageModel())
    try:
        request = start_request().model_copy(update={'rounds': 1,
            'builtin_scoring': BuiltinScoring(mode='quality_tokens')})
        run = await service.start_rsi(agent_id, request, 'alice')
        await service._rsi_tasks[run['id']]
        finished = await service.rsi_run(agent_id, run['id'], 'alice')
        assert finished['status'] == 'completed', finished.get('error')
        assert finished['builtin_scoring']['mode'] == 'quality_tokens'
        result = json.loads((service.runtime_root / 'rsi' / run['id'] / 'result.json').read_text())
        assert result['report']['builtin_scoring']['mode'] == 'quality_tokens'
        assert all(c['objective_score'] is not None for c in result['report']['baseline']['cases'])
        for case in result['report']['baseline']['cases']:
            usage = case['observation']
            assert usage['usage_reported'] is True
            assert (usage['input_tokens'], usage['output_tokens'], usage['cached_input_tokens'], usage['reasoning_tokens']) == (20, 10, 5, 2)
        assert RsiStart.model_validate({'goal': 'Quality', 'request_id': 'default'}).builtin_scoring.mode == 'quality'
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_missing_cost_is_a_specific_failure_without_quality_fallback(tmp_path, monkeypatch):
    service, agent_id = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        request = start_request().model_copy(update={'rounds': 1,
            'builtin_scoring': BuiltinScoring(mode='quality_cost')})
        run = await service.start_rsi(agent_id, request, 'alice')
        await service._rsi_tasks[run['id']]
        finished = await service.rsi_run(agent_id, run['id'], 'alice')
        assert finished['status'] == 'failed' and finished['error_code'] == 'rsi.cost_unavailable'
        assert not (service.runtime_root / 'rsi' / run['id'] / 'result.json').exists()
    finally:
        await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('kind,expected', [('cost', 'rsi.cost_unavailable'),
    ('tokens', 'rsi.tokens_unavailable'), ('mixed_codes', None), ('unrelated', None)])
async def test_grouped_scoring_failure_keeps_only_unambiguous_public_code(tmp_path, monkeypatch, kind, expected):
    from sagents.v2.optimization.builtin_scoring import BuiltinScoringUnavailable
    from sagents.v2.optimization.optimizer import AgentPackageOptimizer

    async def grouped(*args, **kwargs):
        code = 'rsi.tokens_unavailable' if kind == 'tokens' else 'rsi.cost_unavailable'
        second = (RuntimeError('unrelated failure') if kind == 'unrelated' else
            BuiltinScoringUnavailable('missing metric', code='rsi.tokens_unavailable' if kind == 'mixed_codes' else code))
        raise ExceptionGroup('concurrent teardown', [
            BuiltinScoringUnavailable('missing metric', code=code),
            ExceptionGroup('nested task', [second]),
        ])

    monkeypatch.setattr(AgentPackageOptimizer, 'optimize', grouped)
    service, agent_id = await setup_service(tmp_path, monkeypatch, RsiModel())
    try:
        request = start_request().model_copy(update={'rounds': 1,
            'builtin_scoring': BuiltinScoring(mode='quality_cost')})
        run = await service.start_rsi(agent_id, request, 'alice')
        await service._rsi_tasks[run['id']]
        finished = await service.rsi_run(agent_id, run['id'], 'alice')
        assert finished['status'] == 'failed'
        assert finished['error_type'] == 'ExceptionGroup'
        assert finished.get('error_code') == expected
        assert not (service.runtime_root / 'rsi' / run['id'] / 'result.json').exists()
    finally:
        await service.close()
