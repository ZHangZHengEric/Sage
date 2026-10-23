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

@pytest.mark.asyncio
@pytest.mark.parametrize('recover', [True, False])
@pytest.mark.parametrize('tool_name', ['read_value', 'write_value'])
async def test_new_classification_uses_native_bounded_retry_without_tool_replay(monkeypatch, recover, tool_name):
    import tests.sagents.v2.test_agent_loop_matrix as native
    monkeypatch.setattr(native.AgentLoopEngine, '_PROVIDER_RETRY_BASE_SECONDS', 0)
    failure = ProviderStreamFailure('response stream could not be completed', code='invalid_provider_response')
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
    assert result.state == (native.RunState.COMPLETED if recover else native.RunState.SUSPENDED)
    assert len([e for e in events if e.type == 'step.retry_scheduled']) == 3
    assert len([e for e in events if e.type == 'tool.call.started']) == 1
