"""The framework shares a connection, never implements model judging."""
import json

import pytest

from sagents.v2.optimization.scorer_runtime import MODEL_API_ENV, ScorerModelAPI, get_model_api
from tests.sagents.v2.test_python_scorer import scorer, request


def api():
    return ScorerModelAPI(protocol='openai-responses', base_url='https://example.invalid/v1',
        model='gpt-6.1-sol', api_key='test-private-credential')


def test_model_api_is_explicit_and_secret_safe_by_default(monkeypatch):
    value = api()
    assert 'test-private-credential' not in repr(value)
    assert 'test-private-credential' not in value.model_dump_json()
    monkeypatch.delenv(MODEL_API_ENV, raising=False)
    with pytest.raises(RuntimeError, match='No scorer model API'):
        get_model_api()
    monkeypatch.setenv(MODEL_API_ENV, value.worker_environment())
    assert get_model_api().api_key.get_secret_value() == 'test-private-credential'


@pytest.mark.asyncio
async def test_worker_gets_selected_api_but_not_ambient_keys_or_request_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'ambient-unrelated-secret')
    module = scorer(tmp_path, '''import os
from sagents.v2.optimization.scorer_runtime import get_model_api
def score(request):
    api = get_model_api()
    assert api.api_key.get_secret_value() == 'test-private-credential'
    assert 'OPENAI_API_KEY' not in os.environ
    assert 'test-private-credential' not in str(request)
    return {'grade': {'score': .6, 'passed': False, 'rationale': 'Scorer decides'},
            'details': {'model': api.model, 'protocol': api.protocol}}
''')
    module.model_api = api()
    result = await module.score(request())
    assert result.grade.score == .6
    assert result.details == {'model': 'gpt-6.1-sol', 'protocol': 'openai-responses'}
    assert 'test-private-credential' not in result.model_dump_json()


@pytest.mark.asyncio
async def test_import_self_tests_do_not_receive_live_model_credentials(tmp_path):
    cases = [{'request': request().model_dump(mode='json'), 'expected_score': 1, 'expected_passed': True}]
    module = scorer(tmp_path, '''import os
def score(request):
    assert 'SAGE_RSI_SCORER_MODEL_API' not in os.environ
    return {'score': 1, 'passed': True, 'rationale': 'Offline contract fixture'}
SCORER_TEST_CASES = ''' + repr(cases))
    module.model_api = api()
    assert (await module.validate())['status'] == 'passed'


def test_tau_transport_preserves_official_messages_through_model_provider(monkeypatch):
    from evaluation_datasets.tau_bench.runtime import activate
    activate()
    from tau2.data_model.message import SystemMessage, UserMessage
    from evaluation_datasets.tau_bench.scorer import generate_official_assertion
    from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
    import sagents.v2.optimization.scorer_runtime as runtime
    calls = []
    class Provider:
        model_binding = 'gpt-6.1-sol'
        async def stream(self, request):
            calls.append(request)
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                response_id='official', text=json.dumps({'results': [{'metExpectation': True}]}), finish_reason='stop'))
    monkeypatch.setattr(runtime, 'get_model_provider', lambda: Provider())
    messages = [SystemMessage(role='system', content='Official system'), UserMessage(role='user', content='Official assertions')]
    result = generate_official_assertion(model='official-default', messages=messages,
        temperature=0, call_name='nl_assertions_eval')
    assert json.loads(result.content)['results'][0]['metExpectation']
    assert calls[0].model_binding == 'gpt-6.1-sol'
    assert calls[0].temperature == 0
    assert [(m.role, m.content[0].text) for m in calls[0].messages] == [
        ('system', 'Official system'), ('user', 'Official assertions')]


@pytest.mark.asyncio
async def test_scorer_contract_is_validated_and_discovered_from_the_single_file(tmp_path):
    cases = [{'request': request().model_dump(mode='json'), 'expected_score': 1, 'expected_passed': True}]
    module = scorer(tmp_path, '''SCORER_CONTRACT = 'Compare normalized output to the supplied answer; exact match scores 1.'
def score(request):
    return {'score': 1, 'passed': True, 'rationale': 'Fixture'}
SCORER_TEST_CASES = ''' + repr(cases))
    validated = await module.validate()
    assert validated['scoring_contract'].startswith('Compare normalized output')


@pytest.mark.asyncio
async def test_invalid_scorer_contract_cannot_be_imported(tmp_path):
    cases = [{'request': request().model_dump(mode='json'), 'expected_score': 1, 'expected_passed': True}]
    module = scorer(tmp_path, '''SCORER_CONTRACT = {'not': 'text'}
def score(request):
    return {'score': 1, 'passed': True, 'rationale': 'Fixture'}
SCORER_TEST_CASES = ''' + repr(cases))
    from sagents.v2.optimization.python_scorer import ScorerExecutionError
    with pytest.raises(ScorerExecutionError, match='SCORER_CONTRACT'):
        await module.validate()


@pytest.mark.asyncio
async def test_model_provider_transient_failure_remains_recoverable_across_the_worker(tmp_path):
    from sagents.v2.optimization.recovery import OptimizationTransientFailure
    module = scorer(tmp_path, '''from sagents.v2.contracts.errors import SageV2Error, RuntimeErrorInfo, ErrorCategory
def score(request):
    raise SageV2Error(RuntimeErrorInfo(code='model.provider_transient',
        category=ErrorCategory.PROVIDER_TRANSIENT, message='Private provider message', retryable=True))
''')
    with pytest.raises(OptimizationTransientFailure, match='Scorer ModelProvider transport interrupted'):
        await module.score(request())


@pytest.mark.asyncio
async def test_model_scoring_import_uses_recorded_provider_responses_not_live_credentials(tmp_path):
    source = '''import json
from sagents.v2.optimization.scorer_runtime import get_model_provider
from sagents.v2.model.contracts import ModelRequest, ModelMessage, ModelEventKind
from sagents.v2.contracts.items import TextBlock
async def score(request):
    model = get_model_provider()
    async for event in model.stream(ModelRequest(request_id='score', run_id='scorer', model_binding=model.model_binding,
            messages=(ModelMessage(role='user', content=(TextBlock(text='Scorer-owned prompt'),)),))):
        if event.kind == ModelEventKind.COMPLETED:
            return json.loads(event.response.text)
'''
    cases = [{'request': request().model_dump(mode='json'), 'model_responses': [{'response_id': 'offline',
        'finish_reason': 'stop', 'text': json.dumps({'score': .7, 'passed': False, 'rationale': 'Recorded judgment'})}],
        'expected_score': .7, 'expected_passed': False}]
    module = scorer(tmp_path, source + '\nSCORER_TEST_CASES = ' + repr(cases))
    module.model_api = api()
    assert (await module.validate())['status'] == 'passed'
