import pytest
from sagents.v2.model.plugins._shared.wire import ProviderStreamFailure, provider_error

@pytest.mark.parametrize('started,status,message,expected', [
    (False, None, 'response stream could not be completed', True),
    (False, 200, 'response stream could not be completed', True),
    (False, None, 'Response stream could not be completed.', True),
    (False, None, 'request was rejected', False),
    (False, None, 'invalid configuration', False),
    (False, 400, 'response stream could not be completed', False),
    (False, 401, 'response stream could not be completed', False),
    (False, 403, 'response stream could not be completed', False),
    (True, None, 'request was rejected', True),
    (True, 200, 'response stream could not be completed', True),
    (True, 401, 'response stream could not be completed', False),
])
def test_precise_stream_failure_classification(started, status, message, expected):
    failure = ProviderStreamFailure(message, code='invalid_provider_response', status_code=status)
    info = provider_error(failure, response_started=started).info
    assert info.retryable is expected
    assert info.code == ('model.provider_transient' if expected else 'model.provider_permanent')
    assert info.safe_to_resume is True

def test_message_alone_cannot_promote_unknown_error():
    failure = RuntimeError('response stream could not be completed')
    assert provider_error(failure).info.retryable is False

def test_structured_other_rejection_stays_permanent():
    failure = ProviderStreamFailure('response stream could not be completed', code='invalid_request')
    assert provider_error(failure).info.retryable is False


@pytest.mark.parametrize('code', ['server_is_overloaded', 'no_capacity'])
@pytest.mark.parametrize('status', [None, 200, 503])
@pytest.mark.parametrize('started', [False, True])
def test_capacity_errors_are_transient(code, status, started):
    failure = ProviderStreamFailure(
        'The system is currently experiencing high demand and cannot process your request. '
        'Your request exceeds the maximum usage size allowed during peak load. '
        'For improved capacity reliability, consider switching to Provisioned Throughput.',
        code=code, status_code=status,
    )
    info = provider_error(failure, response_started=started).info
    assert info.code == 'model.provider_transient'
    assert info.retryable is True
    assert info.safe_to_resume is True
    assert info.metadata['response_started'] is started

@pytest.mark.asyncio
@pytest.mark.parametrize('recover', [True, False])
@pytest.mark.parametrize('tool_name', ['read_value', 'write_value'])
@pytest.mark.parametrize('code', ['invalid_provider_response', 'server_is_overloaded', 'no_capacity'])
async def test_new_classification_uses_native_bounded_retry_without_tool_replay(monkeypatch, recover, tool_name, code):
    import tests.sagents.v2.test_agent_loop_matrix as native
    monkeypatch.setattr(native.AgentLoopEngine, '_PROVIDER_RETRY_BASE_SECONDS', 0)
    failure = ProviderStreamFailure('response stream could not be completed', code=code)
    info = provider_error(failure, response_started=False).info
    steps = [native.ScriptedModelStep(events=(native.completed(calls=(native.tool_call(tool_name),)),))]
    steps += [native.ScriptedModelStep(events=(), error=info)] * (3 if recover else 4)
    if recover:
        steps.append(native.ScriptedModelStep(events=(native.completed('done'),)))
    model = native.ScriptedModelProvider(tuple(steps))
    runtime, handle, loop, _ = await native.setup_loop(model, transient_retry_limit=3,
        tool_policy=native.DefaultToolPolicy(approval_strategy=native.ApprovalStrategy.AUTO_APPROVE))
    result = await loop.execute(handle.run_id, native.CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    assert result.state == (native.RunState.COMPLETED if recover else native.RunState.FAILED)
    assert len([e for e in events if e.type == 'step.retry_scheduled']) == 3
    assert len([e for e in events if e.type == 'tool.call.started']) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('protocol', ['chat', 'responses'])
@pytest.mark.parametrize('code', ['server_is_overloaded', 'no_capacity'])
@pytest.mark.parametrize('started', [False, True])
@pytest.mark.parametrize('recover', [False, True])
async def test_capacity_sse_retries_through_real_sdk_and_agent_loop(
    monkeypatch, protocol, code, started, recover,
):
    import json
    import httpx
    from openai import AsyncOpenAI
    from sagents.v2.model import (
        OpenAIChatCompletionsConfig, OpenAIChatCompletionsModelProvider,
        OpenAIResponsesConfig, OpenAIResponsesModelProvider,
    )
    from tests.sagents.v2.model_fixture import FULL_MODEL_CAPABILITIES
    import tests.sagents.v2.test_agent_loop_matrix as native

    monkeypatch.setattr(native.AgentLoopEngine, '_PROVIDER_RETRY_BASE_SECONDS', 0)
    requests = []
    responses = []

    def text_event(text):
        if protocol == 'responses':
            return {'type': 'response.output_text.delta', 'delta': text}
        return {
            'id': 'chat-test', 'object': 'chat.completion.chunk',
            'created': 1, 'model': 'test-model',
            'choices': [{'index': 0, 'delta': {'content': text}, 'finish_reason': None}],
        }

    def handler(request):
        requests.append(request)
        events = []
        if recover and len(requests) == 2:
            events.append(text_event('done'))
            if protocol == 'responses':
                events.append({'type': 'response.completed', 'response': {
                    'id': 'resp-test', 'status': 'completed', 'output': [],
                }})
            else:
                final = text_event('')
                final['choices'][0]['finish_reason'] = 'stop'
                events.append(final)
        else:
            if started:
                events.append(text_event('partial'))
            # The user's data-only frame: no SSE event name or JSON type.
            events.append({'error': {'code': code, 'message': (
                'The system is currently experiencing high demand and cannot process your request. '
                'Your request exceeds the maximum usage size allowed during peak load. '
                'For improved capacity reliability, consider switching to Provisioned Throughput.'
            )}})
        body = ''.join(f'data: {json.dumps(event)}\n\n' for event in events)
        response = httpx.Response(200, text=body, headers={'content-type': 'text/event-stream'})
        responses.append(response)
        return response

    async with AsyncOpenAI(
        api_key='test-key', base_url='https://provider.invalid/v1', max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    ) as client:
        config_type, provider_type = (
            (OpenAIResponsesConfig, OpenAIResponsesModelProvider)
            if protocol == 'responses'
            else (OpenAIChatCompletionsConfig, OpenAIChatCompletionsModelProvider)
        )
        provider = provider_type(config_type(
            model='test-model', base_url='https://provider.invalid/v1',
            capabilities=FULL_MODEL_CAPABILITIES,
        ), client=client)
        runtime, handle, loop, _ = await native.setup_loop(
            provider, tools=(), transient_retry_limit=1,
        )
        result = await loop.execute(handle.run_id, native.CONTEXT)
        events = await runtime.session_store.read_events(handle.run_id)

    assert len(requests) == 2
    assert all(request.url.path == (
        '/v1/responses' if protocol == 'responses' else '/v1/chat/completions'
    ) for request in requests)
    retries = [event for event in events if event.type == 'step.retry_scheduled']
    assert len(retries) == 1
    assert retries[0].data.error.code == 'model.provider_transient'
    assert retries[0].data.error.provider_code == code
    assert retries[0].data.error.metadata['response_started'] is started
    assert result.state == (native.RunState.COMPLETED if recover else native.RunState.FAILED)
    assert all(response.is_closed for response in responses)
