"""Cross-provider semantic recovery contract and sanitized session regression."""

from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.contracts.commands import RunConfig
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.model_recovery import (
    ModelFailure,
    ModelFailureKind as K,
    ModelRecoveryAction as A,
    ModelRecoveryConfig,
    ModelRecoveryState,
    ModelTermination as T,
)
from sagents.v2.model.contracts import ModelResponse
from sagents.v2.model.plugins._shared.wire import ProviderStreamFailure, provider_error
from sagents.v2.model.recovery_policy import (
    ModelRecoveryPolicy,
    checked_response,
    failure_from_error,
    reserve_recovery,
)

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "status,code,kind,retry",
    [
        (429, "insufficient_quota", K.QUOTA, False),
        (429, "rate_limit_exceeded", K.RATE_LIMIT, True),
        (401, "timeout", K.AUTHENTICATION, False),
        (403, "server_error", K.PERMISSION, False),
        (404, "model_not_found", K.ROUTE, False),
        (413, None, K.PAYLOAD, False),
        (400, "context_length_exceeded", K.CONTEXT, True),
        (200, "prompt_too_long", K.CONTEXT, True),
        (200, "overloaded_error", K.OVERLOADED, True),
        (200, "rate_limit_exceeded", K.RATE_LIMIT, True),
        (503, None, K.OVERLOADED, True),
        (501, None, K.UNSUPPORTED, False),
        (400, "invalid_request_error", K.INVALID_REQUEST, False),
        (200, "content_filter", K.REFUSED, False),
        (200, "new_unknown_error", K.UNKNOWN, False),
    ],
)
def test_failure_mapping(status, code, kind, retry):
    error = provider_error(
        ProviderStreamFailure("safe fixture", code=code, status_code=status)
    ).info
    failure = failure_from_error(error)
    assert failure.kind == kind
    assert failure.http_status == status
    assert failure.native_code == code
    assert error.retryable is retry


@pytest.mark.parametrize(
    "provider",
    [
        "openai-chat-completions",
        "openai-responses",
        "anthropic-messages",
        "gemini-generate-content",
    ],
)
@pytest.mark.parametrize(
    "reason,text,termination",
    [
        ("stop", "done", T.COMPLETE),
        ("completed", "", T.EMPTY),
        ("end_turn", " ", T.EMPTY),
        ("max_tokens", "part", T.TRUNCATED),
        ("refusal", "", T.REFUSED),
        ("content_filter", "", T.REFUSED),
        ("pause_turn", "", T.PAUSED),
        ("new_reason", "answer", T.UNKNOWN),
    ],
)
def test_provider_independent_termination(provider, reason, text, termination):
    response = ModelResponse(
        response_id="r",
        finish_reason=reason,
        text=text,
        provider_metadata={"provider_id": provider},
    )
    assert response.termination == termination
    if termination in {T.EMPTY, T.REFUSED, T.PAUSED, T.UNKNOWN}:
        with pytest.raises(SageV2Error) as caught:
            checked_response(response)
        assert failure_from_error(caught.value.info).provider == provider
    else:
        assert checked_response(response) == response


def empty_error():
    return RuntimeErrorInfo(
        code="model.empty_semantic_response",
        category=ErrorCategory.VALIDATION,
        message="empty",
        safe_to_resume=True,
    )


def test_empty_has_exactly_one_guided_attempt():
    config, state, policy = (
        ModelRecoveryConfig(),
        ModelRecoveryState(),
        ModelRecoveryPolicy(),
    )
    decision = policy.decide(empty_error(), state, config, now=NOW)
    assert decision.action == A.REGENERATE_WITH_GUIDANCE
    state = reserve_recovery(
        state, decision, config, now=NOW, logical_call_id="call", error=empty_error()
    )
    restored = ModelRecoveryState.model_validate_json(state.model_dump_json())
    assert (
        policy.decide(empty_error(), restored, config, now=NOW).action
        == A.STOP_WITH_EXPLANATION
    )
    assert restored.run_requests == 1
    assert restored.next_call().run_requests == 1


@pytest.mark.parametrize(
    "blocked,side_effect", [(True, "not_applied"), (False, "unknown")]
)
def test_execution_barrier_prevents_recovery(blocked, side_effect):
    error = empty_error().model_copy(
        update={
            "metadata": {
                "model_failure": ModelFailure(
                    kind=K.EMPTY, side_effect_state=side_effect
                ).model_dump(mode="json")
            }
        }
    )
    assert (
        ModelRecoveryPolicy()
        .decide(
            error, ModelRecoveryState(), ModelRecoveryConfig(), now=NOW, blocked=blocked
        )
        .action
        == A.STOP_WITH_EXPLANATION
    )


def test_retry_after_is_minimum_and_deadline_wins():
    error = empty_error().model_copy(
        update={
            "metadata": {
                "model_failure": ModelFailure(
                    kind=K.RATE_LIMIT, retry_after_seconds=60
                ).model_dump(mode="json")
            }
        }
    )
    policy, config = ModelRecoveryPolicy(), ModelRecoveryConfig()
    assert (
        policy.decide(error, ModelRecoveryState(), config, now=NOW).delay_seconds == 60
    )
    result = policy.decide(
        error, ModelRecoveryState(deadline=NOW + timedelta(seconds=10)), config, now=NOW
    )
    assert result.action == A.STOP_WITH_EXPLANATION


def test_legacy_config_defaults_are_finite_and_conflicts_rejected():
    assert RunConfig(transient_retry_limit=None).model_recovery.transient_retries == 2
    assert RunConfig(transient_retry_limit=0).model_recovery.transient_retries == 0
    with pytest.raises(ValueError, match="conflicts"):
        RunConfig(
            transient_retry_limit=1,
            model_recovery=ModelRecoveryConfig(transient_retries=2),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [True, False])
async def test_sanitized_completed_tool_empty_final_response(recover):
    from tests.sagents.v2 import test_agent_loop_matrix as native

    steps = [
        native.ScriptedModelStep(
            events=(native.completed(calls=(native.tool_call("write_value"),)),)
        ),
        native.ScriptedModelStep(events=(native.completed(""),)),
        native.ScriptedModelStep(
            events=(native.completed("Delivered saved result." if recover else ""),)
        ),
    ]
    model = native.ScriptedModelProvider(tuple(steps))
    runtime, handle, loop, executor = await native.setup_loop(
        model,
        tool_policy=native.DefaultToolPolicy(
            approval_strategy=native.ApprovalStrategy.AUTO_APPROVE
        ),
    )
    result = await loop.execute(handle.run_id, native.CONTEXT)
    assert result.state == (
        native.RunState.COMPLETED if recover else native.RunState.FAILED
    )
    assert len(executor.calls) == 1
    assert len(model.requests) == 3
    guidance = [
        m
        for m in model.requests[-1].messages
        if m.metadata.get("runtime_continuation_guidance")
    ]
    assert len(guidance) == 1
    assert "do not repeat completed operations" in guidance[0].content[0].text
    events = await runtime.session_store.read_events(handle.run_id)
    assert sum(e.type == "tool.call.started" for e in events) == 1
    if not recover:
        summary = (await runtime.get_run_result(handle.run_id)).error.metadata[
            "failure_summary"
        ]
        assert summary["preserved_tool_call_ids"]
        assert summary["kind"] == "empty"


@pytest.mark.parametrize(
    "category,code,expected",
    [
        (ErrorCategory.CANCELLED, "cancelled", K.CANCELLED),
        (ErrorCategory.VALIDATION, "budget.deadline", K.BUDGET),
        (ErrorCategory.UNCERTAIN_SIDE_EFFECT, "tool.unknown", K.STATE),
    ],
)
def test_host_barriers_override_provider_retry_claim(category, code, expected):
    error = RuntimeErrorInfo(
        code=code,
        category=category,
        message="stop",
        retryable=True,
        metadata={
            "model_failure": ModelFailure(kind=K.TRANSPORT).model_dump(mode="json")
        },
    )
    assert failure_from_error(error).kind == expected
    assert (
        ModelRecoveryPolicy()
        .decide(error, ModelRecoveryState(), ModelRecoveryConfig(), now=NOW)
        .action
        == A.STOP_WITH_EXPLANATION
    )


@pytest.mark.parametrize(
    "header,minimum,maximum",
    [
        ("12", 12, 12),
        ("garbage", None, None),
        ("-2", None, None),
        ("nan", None, None),
        ("inf", None, None),
        ("date", 28, 30),
    ],
)
def test_retry_after_wire_headers(header, minimum, maximum):
    from types import SimpleNamespace
    from email.utils import format_datetime

    if header == "date":
        header = format_datetime(
            datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True
        )
    exc = ProviderStreamFailure("limited", status_code=429)
    exc.response = SimpleNamespace(status_code=429, headers={"retry-after": header})
    delay = failure_from_error(provider_error(exc).info).retry_after_seconds
    if minimum is None:
        assert delay is None
    else:
        assert minimum <= delay <= maximum


@pytest.mark.parametrize("reason", ["length", "max_tokens", "max_output_tokens"])
def test_truncated_response_never_executes_even_parseable_tool_arguments(reason):
    from sagents.v2.model.contracts import ModelToolCall

    response = ModelResponse(
        response_id="r",
        finish_reason=reason,
        tool_calls=(ModelToolCall(tool_call_id="c", name="write", arguments={"x": 1}),),
    )
    with pytest.raises(SageV2Error) as caught:
        checked_response(response)
    assert failure_from_error(caught.value.info).kind == K.ARGUMENTS


@pytest.mark.asyncio
async def test_auxiliary_nested_failures_share_budget_and_cancellation_gate(
    monkeypatch,
):
    from sagents.v2.model.recovery import collect_response
    from sagents.v2.model.recovery_scope import RecoveryScope, recovery_scope
    from tests.sagents.v2 import test_agent_loop_matrix as native
    from tests.sagents.v2.test_builtin_model_protocols_matrix import request

    model = native.ScriptedModelProvider(
        tuple(
            native.ScriptedModelStep(events=(native.completed(""),)) for _ in range(5)
        )
    )
    scope = RecoveryScope(config=ModelRecoveryConfig(run_requests=1))
    persisted = []

    async def persist(key, state, error, decision):
        if decision.reason != "dispatch_state":
            persisted.append(state.run_requests)

    scope.persist = persist
    with recovery_scope(scope):
        for purpose in ("judge", "memory"):
            with pytest.raises(SageV2Error):
                await collect_response(model, request(), purpose=purpose)
    assert len(model.requests) == 3  # Two independent initial calls, one shared extra.
    assert persisted == [1]
    cancelled = RecoveryScope()

    async def check():
        raise SageV2Error(
            RuntimeErrorInfo(
                code="cancelled", category=ErrorCategory.CANCELLED, message="cancelled"
            )
        )

    cancelled.check = check
    with recovery_scope(cancelled), pytest.raises(SageV2Error):
        await collect_response(model, request())
    assert len(model.requests) == 3


@pytest.mark.asyncio
async def test_empty_guidance_reservation_survives_worker_restart(monkeypatch):
    import asyncio
    from tests.sagents.v2 import test_agent_loop_matrix as native

    first = native.ScriptedModelProvider(
        (native.ScriptedModelStep(events=(native.completed(""),)),)
    )
    runtime, handle, loop, executor = await native.setup_loop(first)
    waiting = asyncio.Event()

    async def wait(run_id, delay):
        waiting.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(loop, "_wait_for_model_retry", wait)
    task = asyncio.create_task(loop.execute(handle.run_id, native.CONTEXT))
    await asyncio.wait_for(waiting.wait(), 2)
    checkpoint = await runtime.session_store.get_latest_checkpoint(handle.run_id)
    saved = native.AgentLoopCheckpointCodec.decode(checkpoint.state)
    assert saved.model_recovery.counts["empty"] == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    second = native.ScriptedModelProvider(
        (native.ScriptedModelStep(events=(native.completed(""),)),)
    )
    recovered = native.AgentLoopEngine(
        runtime=runtime,
        model=second,
        tool_catalog=native.InMemoryToolCatalog((native.READ_TOOL, native.WRITE_TOOL)),
        tool_executor=executor,
    )
    result = await recovered.recover_interrupted(handle.run_id, native.CONTEXT)
    assert result.state == native.RunState.FAILED
    assert len(second.requests) == 1
    assert any(
        m.metadata.get("runtime_continuation_guidance")
        for m in second.requests[0].messages
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("refused", [False, True])
async def test_responses_terminal_content_without_deltas_is_not_empty(refused):
    from types import SimpleNamespace
    from tests.sagents.v2.test_builtin_model_protocols_matrix import (
        FakeResponses,
        FakeAsyncStream,
        request,
        CAPABILITIES,
        OpenAIResponsesModelProvider,
        OpenAIResponsesConfig,
    )

    content = (
        {"type": "refusal", "refusal": "Cannot answer this request."}
        if refused
        else {"type": "output_text", "text": "Delivered result."}
    )
    provider = OpenAIResponsesModelProvider(
        OpenAIResponsesConfig(model="fixture", capabilities=CAPABILITIES),
        client=SimpleNamespace(
            responses=FakeResponses(
                FakeAsyncStream(
                    (
                        {
                            "type": "response.completed",
                            "response": {
                                "id": "r",
                                "status": "completed",
                                "output": [
                                    {
                                        "id": "msg",
                                        "type": "message",
                                        "content": [content],
                                    }
                                ],
                            },
                        },
                    )
                )
            )
        ),
    )
    events = [event async for event in provider.stream(request())]
    response = events[-1].response
    assert response.text == (
        "Cannot answer this request." if refused else "Delivered result."
    )
    assert response.termination == (T.REFUSED if refused else T.COMPLETE)


@pytest.mark.asyncio
async def test_auxiliary_restart_never_reuses_a_dispatched_guidance_allowance():
    from sagents.v2.model.recovery import collect_response
    from sagents.v2.model.recovery_scope import RecoveryScope, recovery_scope
    from tests.sagents.v2.test_builtin_model_protocols_matrix import request
    from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider

    now = datetime.now(timezone.utc)
    config = ModelRecoveryConfig()
    decision = ModelRecoveryPolicy().decide(
        empty_error(), ModelRecoveryState(), config, now=now
    )
    state = reserve_recovery(
        ModelRecoveryState(),
        decision,
        config,
        now=now,
        logical_call_id="operation:judge",
        error=empty_error(),
    ).model_copy(update={"dispatch_started": True})
    scope = RecoveryScope(
        config=config,
        run_requests=1,
        states={"operation:judge": state},
        episode_counts={"operation": 1},
        episode_deadlines={"operation": state.deadline},
    )
    model = ScriptedModelProvider(())
    with recovery_scope(scope), pytest.raises(SageV2Error) as caught:
        await collect_response(model, request(), purpose="judge")
    assert (
        caught.value.info.metadata["recovery"]["action"]
        == A.STOP_WITH_EXPLANATION.value
    )
    assert not model.requests


@pytest.mark.parametrize(
    "code,status,kind",
    [
        ("billing_error", 400, K.QUOTA),
        ("insufficient_balance", 429, K.QUOTA),
        ("unsupported_endpoint", 500, K.UNSUPPORTED),
        ("invalid_image", 400, K.MEDIA),
        ("refusal", 200, K.REFUSED),
    ],
)
def test_explicit_provider_code_overrides_generic_http_class(code, status, kind):
    error = provider_error(
        ProviderStreamFailure("fixture", code=code, status_code=status)
    ).info
    assert failure_from_error(error).kind == kind
    assert not error.retryable


def test_gemini_daily_quota_is_not_transient_rate_limit():
    error = provider_error(
        ProviderStreamFailure(
            "fixture",
            status_code=429,
            body={
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [
                                {"quotaId": "GenerateRequestsPerDayPerProjectPerModel"}
                            ],
                        }
                    ],
                }
            },
        )
    ).info
    assert failure_from_error(error).kind == K.QUOTA
    assert not error.retryable


@pytest.mark.asyncio
async def test_transient_retry_preserves_the_guided_semantic_request(monkeypatch):
    from sagents.v2.model.recovery import collect_response
    from sagents.v2.model.recovery_scope import RecoveryScope
    from tests.sagents.v2 import test_agent_loop_matrix as native
    from tests.sagents.v2.test_builtin_model_protocols_matrix import request
    async def no_wait(self, seconds):
        pass
    monkeypatch.setattr(RecoveryScope, 'wait', no_wait)
    transient = RuntimeErrorInfo(code='model.provider_transient', category=ErrorCategory.PROVIDER_TRANSIENT,
        message='temporary', retryable=True)
    model = native.ScriptedModelProvider((
        native.ScriptedModelStep(events=(native.completed(''),)),
        native.ScriptedModelStep(events=(), error=transient),
        native.ScriptedModelStep(events=(native.completed('delivered'),)),
    ))
    await collect_response(model, request())
    assert model.requests[1].messages[-1].metadata['runtime_continuation_guidance']
    assert model.requests[2].messages == model.requests[1].messages


@pytest.mark.parametrize('code', ['server_is_overloaded', 'no_capacity', 'invalid_api_key'])
def test_structured_code_wins_over_context_words_in_message(code):
    error = provider_error(ProviderStreamFailure('prompt is too long', code=code, status_code=200)).info
    assert failure_from_error(error).kind == (K.AUTHENTICATION if code == 'invalid_api_key' else K.OVERLOADED)


@pytest.mark.asyncio
async def test_resumed_auxiliary_reservation_preserves_server_wait(monkeypatch):
    from sagents.v2.model.recovery import collect_response
    from sagents.v2.model.recovery_scope import RecoveryScope, recovery_scope
    from tests.sagents.v2 import test_agent_loop_matrix as native
    from tests.sagents.v2.test_builtin_model_protocols_matrix import request
    error = RuntimeErrorInfo(code='model.provider_transient', category=ErrorCategory.RATE_LIMITED,
        message='limited', retryable=True, metadata={'model_failure': ModelFailure(kind=K.RATE_LIMIT, retry_after_seconds=60).model_dump(mode='json')})
    config = ModelRecoveryConfig()
    decision = ModelRecoveryPolicy().decide(error, ModelRecoveryState(), config, now=NOW)
    state = reserve_recovery(ModelRecoveryState(), decision, config, now=NOW, logical_call_id='operation:judge', error=error)
    state = ModelRecoveryState.model_validate_json(state.model_dump_json())
    scope = RecoveryScope(clock=lambda: NOW + timedelta(seconds=18), run_requests=1,
        states={'operation:judge': state}, episode_counts={'operation': 1}, episode_deadlines={'operation': state.deadline})
    waits = []
    async def wait(self, seconds):
        waits.append(seconds)
    monkeypatch.setattr(RecoveryScope, 'wait', wait)
    model = native.ScriptedModelProvider((native.ScriptedModelStep(events=(native.completed('done'),)),))
    with recovery_scope(scope):
        await collect_response(model, request(), purpose='judge')
    assert waits == [42]
    assert len(model.requests) == 1
    assert scope.run_requests == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["", "not json"])
@pytest.mark.parametrize("recover", [False, True])
async def test_judge_failed_response_usage_stops_recovery_at_run_token_budget(invalid, recover):
    from tests.sagents.v2 import test_agent_loop_matrix as native
    main = native.ScriptedModelProvider((native.ScriptedModelStep(events=(native.completed('done', input_tokens=0, output_tokens=0),)),))
    judge = native.ScriptedModelProvider((
        native.ScriptedModelStep(events=(native.completed(invalid, input_tokens=10, output_tokens=1),)),
        native.ScriptedModelStep(events=(native.completed('{"decision":"completed","reason":"done"}'),)),
    ))
    policy = native.LLMJudgeContinuationPolicy(native.LLMContinuationJudge(judge))
    runtime, handle, loop, _ = await native.setup_loop(main, max_total_tokens=100 if recover else 11, continuation_policy=policy)
    result = await loop.execute(handle.run_id, native.CONTEXT)
    assert result.state == (native.RunState.COMPLETED if recover else native.RunState.FAILED)
    assert len(judge.requests) == (2 if recover else 1)
    events = await runtime.session_store.read_events(handle.run_id)
    assert sum(e.data.usage.input_tokens + e.data.usage.output_tokens for e in events if e.type == 'usage.recorded') == (18 if recover else 11)


@pytest.mark.asyncio
async def test_old_checkpoint_episode_counters_seed_the_shared_scope():
    from tests.sagents.v2 import test_agent_loop_matrix as native
    model = native.ScriptedModelProvider(())
    runtime, handle, loop, _ = await native.setup_loop(model)
    run = await runtime.get_run(handle.run_id)
    command = await runtime.session_store.get_start_command(handle.run_id)
    state = native.AgentLoopCheckpointState(turn_id='turn_test', step_number=1,
        model_recovery=ModelRecoveryState(episode_requests=3, run_requests=3))
    scope = await loop._create_recovery_scope(run, state, command, native.CONTEXT)
    assert scope.episode_counts[scope.step_key] == 3
    assert scope.run_requests == 3
