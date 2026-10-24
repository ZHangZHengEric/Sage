import json

import pytest

from app.v2.desktop.backend.rsi_usage import MeteredRsiModel, RsiUsageReader, stage_for_package
from sagents.v2.contracts.items import UsageSummary
from sagents.v2.model.contracts import ModelEventKind, ModelRequest, ModelResponse, ModelStreamEvent


def append(path, record):
    with path.open('a') as stream:
        stream.write(json.dumps(record) + '\n')


def usage(i, c, o):
    return {'reported': True, 'input_tokens': i, 'cached_input_tokens': c, 'output_tokens': o}


def observation(identity, counters):
    return {'evidence': {'run_id': identity, 'execution_usage_scope': {'after_sequence': 0, 'through_sequence': 10},
        'execution_usage': counters}}


def test_usage_deduplicates_checkpoints_and_recovery_and_counts_actual_retries(tmp_path):
    audit = tmp_path / 'audit.jsonl'
    append(audit, {'event': 'target_call_completed', 'data': {'call_id': 'old', 'observation': observation('legacy', usage(100, 40, 10))}})
    append(audit, {'event': 'target_call_completed', 'data': {'call_id': 'new', 'observation': observation('new', usage(400, 200, 40))}})
    append(audit, {'event': 'agent_call_started', 'data': {'call_id': 'user', 'role': 'test_dialogue'}})
    append(audit, {'event': 'agent_call_completed', 'data': {'call_id': 'user', 'observation': observation('dialogue', usage(30, 0, 3))}})
    append(tmp_path / 'audit-resume-a.jsonl', {'event': 'target_call_completed', 'data': {'call_id': 'old-again', 'observation': observation('legacy', usage(100, 40, 10))}})
    primary = tmp_path / 'token-usage.jsonl'
    for identity in ['attempt-one', 'attempt-two']:
        record = {'id': identity, 'native_run_id': 'new', 'stage': 'execution', 'usage': usage(200, 100, 20)}
        append(primary, record)
        append(primary, record)  # Duplicate journal entry, not another provider call.
    append(primary, {'id': 'failure', 'native_run_id': 'failed', 'stage': 'tuning', 'usage': None})
    append(tmp_path / 'scorer-model-calls.jsonl', {'request_id': 'scorer', 'usage': usage(80, 60, 8)})
    trial = {'conversation': [{'target': observation('human-test', usage(50, 10, 5))}]}
    value = {'test_observations': [{'round': n, 'cases': [{'id': 'case', 'trials': [trial]}]} for n in range(2)]}
    reader = RsiUsageReader()
    snapshot = reader.read(tmp_path, value)
    total = snapshot['total']
    assert total['input_tokens'] == 660
    assert total['cached_input_tokens'] == 310
    assert total['output_tokens'] == 66
    assert total['total_tokens'] == 726  # Cache is NOT added to total input again.
    assert total['cache_rate'] == pytest.approx(310 / 660)
    assert total['unreported_records'] == 1
    assert snapshot['stages']['dialogue']['input_tokens'] == 30
    assert snapshot['stages']['evaluation']['input_tokens'] == 80
    assert snapshot['coverage'] == 'partial_legacy'
    assert reader.read(tmp_path, value) == snapshot
    assert RsiUsageReader().read(tmp_path, value) == snapshot
    append(primary, {'id': 'later', 'native_run_id': 'tuner', 'stage': 'tuning', 'usage': usage(20, 0, 2)})
    assert reader.read(tmp_path, value)['total']['total_tokens'] == 748


def test_reader_defers_partial_lines_and_zero_usage_is_distinct_from_missing(tmp_path):
    path = tmp_path / 'token-usage.jsonl'
    raw = json.dumps({'id': 'zero', 'native_run_id': 'native', 'stage': 'execution', 'usage': usage(0, 0, 0)})
    path.write_text(raw[:20])
    reader = RsiUsageReader()
    assert reader.read(tmp_path, {})['coverage'] == 'pending'
    with path.open('a') as stream:
        stream.write(raw[20:] + '\n')
    total = reader.read(tmp_path, {})['total']
    assert total['reported_records'] == 1 and total['unreported_records'] == 0
    assert total['total_tokens'] == 0 and total['cache_rate'] is None


def test_historical_observation_reuse_does_not_bill_source_tokens_again(tmp_path):
    old = observation('historical', usage(1000, 300, 100))
    old['evidence']['measurement_reuse'] = {'protocol': 'sage.rsi.historical-observation/v1',
                                          'billed_provider_calls': 0, 'source_run_id': 'old'}
    append(tmp_path / 'audit.jsonl', {'event': 'target_call_completed',
                                    'data': {'call_id': 'imported', 'observation': old}})
    append(tmp_path / 'token-usage.jsonl', {'id': 'fresh', 'native_run_id': 'fresh',
           'stage': 'evaluation', 'usage': usage(20, 0, 5)})
    total = RsiUsageReader().read(tmp_path, {})['total']
    assert total['input_tokens'] == 20 and total['output_tokens'] == 5


@pytest.mark.asyncio
async def test_model_meter_records_every_invocation_and_preserves_provider_contract(tmp_path):
    class Provider:
        capabilities = 'delegated'
        fail = False
        async def stream(self, request):
            if self.fail:
                raise RuntimeError('provider failure with private content')
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                response_id='response', text='private answer', finish_reason='stop', usage=UsageSummary(**usage(100, 40, 10))))
    provider = Provider()
    model = MeteredRsiModel(provider, tmp_path, 'execution')
    request = ModelRequest(request_id='request', run_id='native', model_binding='model', messages=())
    assert model.capabilities == 'delegated'
    for _ in range(2):
        assert len([event async for event in model.stream(request)]) == 1
    provider.fail = True
    with pytest.raises(RuntimeError):
        _ = [event async for event in model.stream(request)]
    snapshot = RsiUsageReader().read(tmp_path, {})
    assert snapshot['total']['input_tokens'] == 200
    assert snapshot['total']['total_tokens'] == 220
    assert snapshot['total']['unreported_records'] == 1
    assert 'private' not in (tmp_path / 'token-usage.jsonl').read_text()


def test_role_classification_separates_question_generation_and_user_simulation():
    from tests.sagents.v2.test_package_optimizer import bundle
    from sagents.v2.optimization.principles import DIALOGUE_USER_PRINCIPLES
    package = bundle()
    assert stage_for_package(package) == 'execution'
    data = package.model_dump(mode='json')
    data['manifest']['metadata']['id'] = 'desktop.rsi.designer'
    assert stage_for_package(type(package).model_validate(data)) == 'design'
    agent = next(iter(data['manifest']['agents'].values()))
    agent['instructions'] = {'inline': DIALOGUE_USER_PRINCIPLES}
    assert stage_for_package(type(package).model_validate(data)) == 'dialogue'


@pytest.mark.asyncio
@pytest.mark.parametrize('human_test', [False, True])
async def test_desktop_run_exposes_live_stage_usage_without_changing_scores(tmp_path, monkeypatch, human_test):
    from tests.app.v2.desktop.test_rsi import RsiModel, setup_service, start_request
    class MeteredFixture(RsiModel):
        async def _stream(self, request):
            async for event in super()._stream(request):
                if event.kind == ModelEventKind.COMPLETED:
                    event = event.model_copy(update={'response': event.response.model_copy(update={'usage': UsageSummary(**usage(100, 40, 10))})})
                yield event
    model = MeteredFixture()
    service, agent = await setup_service(tmp_path, monkeypatch, model)
    try:
        request = start_request().model_copy(update={'rounds': 1})
        if human_test:
            from sagents.v2.optimization.contracts import OptimizationTestSuite, OptimizationCase
            request = request.model_copy(update={'human_test_count': 1, 'human_test_suite': OptimizationTestSuite(cases=(
                OptimizationCase(id='private-test', input='What is 6*7?', rubric='42', split='test'),))})
        run = await service.start_rsi(agent, request, 'alice')
        await service._rsi_tasks[run['id']]
        result = await service.rsi_run(agent, run['id'], 'alice')
        assert result['status'] == 'completed'
        stats = result['token_usage']
        assert stats['coverage'] == 'provider_calls'
        assert stats['stages']['execution']['input_tokens'] > 0
        assert stats['stages']['evaluation']['input_tokens'] > 0
        assert stats['stages']['review']['input_tokens'] == 0
        assert stats['total']['cache_rate'] == pytest.approx(.4)
        assert stats['total']['input_tokens'] == len(model.requests) * 100
        if human_test:
            assert result['test_observations']
        assert stats == (await service.rsi_run(agent, run['id'], 'alice'))['token_usage']
        assert 'token_usage' not in result['result']['report']
    finally:
        await service.close()
