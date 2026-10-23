import asyncio
import hashlib
import json

import httpx
import pytest

from app.v2.desktop.backend.scorer_model_api import ScorerModelGateway
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import UsageSummary
from sagents.v2.model.contracts import ModelCapabilities, ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.model.plugins.concurrency_budget import ModelConcurrencyBudget
from sagents.v2.optimization.python_scorer import PythonExecutionScorer
from sagents.v2.optimization.scoring import ScorerDescriptor
from tests.sagents.v2.test_python_scorer import request


class Model:
    def __init__(self, error=None):
        self.requests, self.active, self.maximum, self.error = [], 0, 0, error
    async def capabilities(self, binding):
        return ModelCapabilities(supports_streaming=True, supports_tools=True,
            supports_parallel_tool_calls=True, supports_reasoning=True,
            supports_multimodal_input=True, supports_structured_output=True,
            max_output_tokens=2000)
    async def stream(self, value):
        self.requests.append(value)
        self.active += 1
        self.maximum = max(self.maximum, self.active)
        try:
            await asyncio.sleep(.01)
            if self.error:
                error, self.error = self.error, None
                raise error
            yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=ModelResponse(
                response_id='resp_fixture', text='{"score": 0.25}', finish_reason='stop',
                usage=UsageSummary(reported=True, input_tokens=10, output_tokens=5)))
        finally:
            self.active -= 1


def gateway(model=None, audit=None):
    return ScorerModelGateway(provider=model or Model(), model='fixture', model_binding='selected-provider',
        run_id='rsi-test', concurrency=asyncio.Semaphore(2), model_budget=ModelConcurrencyBudget(1),
        max_output_tokens=1000, audit=audit, redact=('remote-secret',))


@pytest.mark.asyncio
async def test_scorer_sdk_uses_sage_provider_and_keeps_prompts_and_grade_in_the_scorer(tmp_path):
    model, audits = Model(), []
    proxy = gateway(model, audits.append)
    source = '''from openai import OpenAI
from sagents.v2.optimization.scorer_runtime import get_model_api
def score(request):
    api = get_model_api()
    assert api.base_url.startswith('http://127.0.0.1:')
    assert api.api_key.get_secret_value() != 'remote-secret'
    with OpenAI(base_url=api.base_url, api_key=api.api_key.get_secret_value(), max_retries=0) as client:
        result = client.responses.create(model=api.model, input=[
            {'role': 'system', 'content': 'My official scoring instructions'},
            {'role': 'user', 'content': request['observation']['output']}], max_output_tokens=100)
    import json
    # Scorer parsing and numerical decision; no framework evaluator is involved.
    return {'score': json.loads(result.output_text)['score'], 'passed': False, 'rationale': 'Scorer-owned judgment'}
'''
    path = tmp_path / 'score.py'
    path.write_text(source)
    try:
        await proxy.start()
        scorer = PythonExecutionScorer(path=path, source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            descriptor=ScorerDescriptor(id='fixture', name='Fixture', version='1'), model_api_factory=proxy.bind)
        result = await scorer.score(request())
        assert result.grade.score == .25
        assert len(model.requests) == 1
        native = model.requests[0]
        assert native.model_binding == 'selected-provider'
        assert [(m.role, ''.join(b.text for b in m.content)) for m in native.messages] == [
            ('system', 'My official scoring instructions'), ('user', '42')]
        assert not native.tools and native.metadata['purpose'] == 'scorer'
        assert not proxy._leases
        assert audits[0]['usage']['input_tokens'] == 10
        assert audits[0]['split'] == 'training'
        assert 'My official scoring instructions' not in json.dumps(audits)
        assert 'remote-secret' not in json.dumps(audits)
    finally:
        await proxy.close()
    assert proxy.task.done() and proxy.base_url is None


@pytest.mark.asyncio
@pytest.mark.parametrize('transient', [False, True])
async def test_native_scorer_failure_is_bounded_and_never_becomes_a_grade(tmp_path, transient):
    from sagents.v2.model.plugins._shared.wire import ProviderStreamFailure, provider_error
    from sagents.v2.optimization.python_scorer import ScorerExecutionError
    from sagents.v2.optimization.recovery import OptimizationTransientFailure
    error = provider_error(ProviderStreamFailure(
        'response stream could not be completed' if transient else 'invalid API key',
        code='invalid_provider_response' if transient else 'invalid_api_key'))

    class FailingModel(Model):
        async def stream(self, value):
            self.error = error
            async for event in super().stream(value):
                yield event

    model, audits = FailingModel(), []
    proxy = gateway(model, audits.append)
    path = tmp_path / 'scorer.py'
    path.write_text('''from sagents.v2.optimization.scorer_runtime import get_model_provider
from sagents.v2.model.contracts import ModelRequest, ModelMessage
from sagents.v2.contracts.items import TextBlock
async def score(request):
    model = get_model_provider()
    async for event in model.stream(ModelRequest(request_id='score', run_id='scorer',
            model_binding=model.model_binding,
            messages=(ModelMessage(role='user', content=(TextBlock(text='Evaluate saved execution'),)),))):
        pass
    raise AssertionError('An exhausted model call must not return a score')
''')
    try:
        await proxy.start()
        scorer = PythonExecutionScorer(path=path, source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            descriptor=ScorerDescriptor(id='fixture', name='Fixture', version='1'), model_api_factory=proxy.bind)
        with pytest.raises(OptimizationTransientFailure if transient else ScorerExecutionError):
            await scorer.score(request())
        assert len(model.requests) == (3 if transient else 1)
        assert all(row['status'] == 'failed' for row in audits)
        assert not proxy._leases and proxy.model_budget.active == 0
    finally:
        await proxy.close()
    assert proxy.task.done() and proxy.base_url is None


@pytest.mark.asyncio
async def test_api_auth_scope_expiry_input_budget_and_request_fields_are_enforced():
    proxy = gateway()
    proxy.base_url = 'http://127.0.0.1:1/v1'
    transport = httpx.ASGITransport(app=proxy.app)
    payload = {'model': 'fixture', 'input': 'Score this', 'max_output_tokens': 100}
    async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1:1') as client:
        assert (await client.post('/v1/responses', json=payload)).status_code == 401
        async with proxy.bind(request()) as api:
            headers = {'Authorization': 'Bearer ' + api.api_key.get_secret_value()}
            assert (await client.post('/v1/responses', headers=headers, json=payload)).status_code == 200
            for update in ({'model': 'another-model'}, {'max_output_tokens': 1001}, {'stream': True},
                           {'tools': [{'type': 'function'}]}, {'input': [{'role': 'tool', 'content': 'no'}]}):
                assert (await client.post('/v1/responses', headers=headers, json={**payload, **update})).status_code == 400
            assert (await client.post('/v1/responses', headers=headers, content=b'x' * (2 * 1024 * 1024 + 1))).status_code == 413
        assert (await client.post('/v1/responses', headers=headers, json=payload)).status_code == 401


@pytest.mark.asyncio
async def test_requests_share_the_native_model_budget_and_keep_test_metadata_separate():
    model, audit = Model(), []
    proxy = gateway(model, audit.append)
    proxy.base_url = 'http://127.0.0.1:1/v1'
    test = request().model_copy(update={'case': request().case.model_copy(update={'id': 'private-test', 'split': 'test'})})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy.app), base_url='http://127.0.0.1:1') as client:
        async with proxy.bind(request()) as a, proxy.bind(test) as b:
            async def call(api):
                return await client.post('/v1/chat/completions', headers={'Authorization': 'Bearer ' + api.api_key.get_secret_value()},
                    json={'model': 'fixture', 'messages': [{'role': 'user', 'content': 'Raw scorer prompt'}]})
            responses = await asyncio.gather(call(a), call(b))
            assert all(r.status_code == 200 for r in responses)
    assert model.maximum == 1
    assert {r['split'] for r in audit} == {'training', 'test'}
    assert 'Raw scorer prompt' not in json.dumps(audit)


@pytest.mark.asyncio
async def test_provider_transient_error_is_exposed_for_sdk_retry_and_secrets_are_redacted():
    error = SageV2Error(RuntimeErrorInfo(code='model.provider_transient', category=ErrorCategory.PROVIDER_TRANSIENT,
        message='502 remote-secret upstream failure', retryable=True))
    model, audit = Model(error), []
    proxy = gateway(model, audit.append)
    proxy.base_url = 'http://127.0.0.1:1/v1'
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=proxy.app), base_url='http://127.0.0.1:1') as client:
        async with proxy.bind(request()) as api:
            headers = {'Authorization': 'Bearer ' + api.api_key.get_secret_value()}
            value = {'model': 'fixture', 'input': 'Score'}
            failed = await client.post('/v1/responses', headers=headers, json=value)
            assert failed.status_code == 503 and failed.json()['error']['retryable']
            assert 'remote-secret' not in failed.text
            passed = await client.post('/v1/responses', headers=headers, json=value)
            assert passed.status_code == 200
    assert [r['status'] for r in audit] == ['failed', 'completed']
    assert audit[0]['error_message'] == '502 [redacted] upstream failure'
    assert audit[0]['retryable'] is True
    assert 'remote-secret' not in json.dumps(audit)
    assert proxy.model_budget.active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('stream_interrupted', [False, True])
async def test_scoring_code_receives_a_ready_model_provider_not_credentials(tmp_path, stream_interrupted):
    from sagents.v2.model.plugins._shared.wire import ProviderStreamFailure, provider_error
    failure = provider_error(ProviderStreamFailure('response stream could not be completed',
        code='invalid_provider_response'), response_started=False) if stream_interrupted else None
    model, audits = Model(failure), []
    proxy = gateway(model, audits.append)
    source = '''import json
from sagents.v2.optimization.scorer_runtime import get_model_provider
from sagents.v2.model.contracts import ModelRequest, ModelMessage, ModelEventKind
from sagents.v2.contracts.items import TextBlock
async def score(request):
    model = get_model_provider()
    capabilities = await model.capabilities(model.model_binding)
    assert capabilities.supports_structured_output
    assert not capabilities.supports_streaming
    assert capabilities.max_output_tokens == 1000
    async for event in model.stream(ModelRequest(request_id='my-score', run_id='scorer',
            model_binding=model.model_binding, temperature=.2, response_format='json_object',
            messages=(ModelMessage(role='system', content=(TextBlock(text='Exact scorer prompt'),)),),
            max_output_tokens=100)):
        if event.kind == ModelEventKind.COMPLETED:
            value = json.loads(event.response.text)['score']
    return {'score': value, 'passed': False, 'rationale': 'Scorer parses its own result'}
'''
    path = tmp_path / 'scorer.py'
    path.write_text(source)
    try:
        await proxy.start()
        module = PythonExecutionScorer(path=path, source_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
            descriptor=ScorerDescriptor(id='proxy', name='Proxy', version='1'), model_api_factory=proxy.bind)
        result = await module.score(request())
        assert result.grade.score == .25
        assert len(model.requests) == (2 if stream_interrupted else 1)
        if stream_interrupted:
            assert [row['status'] for row in audits] == ['failed', 'completed']
            assert audits[0]['retryable'] is True
            assert audits[0]['provider_code'] == 'invalid_provider_response'
            assert audits[0]['response_started'] is False
            assert model.requests[0].messages == model.requests[1].messages
        native = model.requests[0]
        assert native.response_format == 'json_object' and native.temperature == .2
        assert native.messages[0].content[0].text == 'Exact scorer prompt'
        assert native.model_binding == 'selected-provider' and native.run_id == 'rsi-test'
        assert not proxy._leases
    finally:
        await proxy.close()
