"""Regression coverage for logical identity, live deadlines and restored waits."""

import asyncio
import json
from contextlib import asynccontextmanager

import pytest

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.model_recovery import (
    ModelRecoveryConfig,
    ModelRecoveryState,
    ModelFailureKind as K,
)
from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
from sagents.v2.context.summary import SummarizationRequest
from sagents.v2.model.recovery import collect_response
from sagents.v2.model.recovery_policy import ModelRecoveryPolicy, reserve_recovery
from sagents.v2.model.recovery_scope import (
    RecoveryScope,
    recovery_scope,
    reserve_additional_request,
    schedule_failure_recovery,
)
from sagents.v2.optimization.default_user_simulator import (
    DefaultUserSimulator,
    generate_user_text,
)
from sagents.v2.optimization.python_user_simulator import UserSimulationExecutionError
from tests.sagents.v2.test_auxiliary_recovery_boundaries import response, model
from tests.sagents.v2.test_builtin_model_protocols_matrix import request
from tests.sagents.v2.test_recovery_state_matrix import failure
from tests.sagents.v2.test_user_simulator import request as simulation_request, STOP
from tests.sagents.v2.test_api_context_recovery import scope as context_scope, message


@pytest.mark.parametrize("same_id", [False, True])
async def test_same_purpose_concurrent_calls_never_adopt_each_others_recovery(same_id):
    started, release = asyncio.Event(), asyncio.Event()

    class Provider:
        calls = 0

        async def stream(self, req):
            self.calls += 1
            if self.calls == 1:
                yield response("")
            else:
                started.set()
                await release.wait()
                yield response("A completed")

    a = Provider()
    b = model(("B completed", "stop"))
    scope = RecoveryScope()
    with recovery_scope(scope):
        task = asyncio.create_task(
            collect_response(
                a, request().model_copy(update={"request_id": "A"}), purpose="same"
            )
        )
        await started.wait()
        try:
            result = await collect_response(
                b,
                request().model_copy(update={"request_id": "A" if same_id else "B"}),
                purpose="same",
            )
            assert result.text == "B completed"
            assert (
                not b.requests[0]
                .messages[-1]
                .metadata.get("runtime_continuation_guidance")
            )
        finally:
            release.set()
            assert (await task).text == "A completed"
    assert a.calls == 2
    assert len(b.requests) == 1
    assert scope.run_requests == 1


async def test_request_fingerprint_restores_pending_wait_after_request_id_changes():
    saved = []
    scope = RecoveryScope()

    async def persist(key, state, error, decision):
        saved.append((key, state.model_dump(mode="json")))

    async def crash(seconds):
        raise asyncio.CancelledError()

    class Limited:
        async def stream(self, req):
            raise SageV2Error(failure(K.RATE_LIMIT, retry_after_seconds=30))
            yield

    scope.persist, scope.wait = persist, crash
    original = request().model_copy(update={"request_id": "old"})
    with recovery_scope(scope), pytest.raises(asyncio.CancelledError):
        await collect_response(Limited(), original)
    restored = RecoveryScope(
        run_requests=scope.run_requests,
        states={key: ModelRecoveryState.model_validate(value) for key, value in saved},
        episode_counts=dict(scope.episode_counts),
        episode_deadlines=dict(scope.episode_deadlines),
    )
    waits = []

    async def wait(seconds):
        waits.append(seconds)

    restored.wait = wait
    provider = model(("done", "stop"))
    with recovery_scope(restored):
        await collect_response(
            provider, original.model_copy(update={"request_id": "rebuilt"})
        )
    assert len(provider.requests) == 1
    assert waits[0] >= 29
    assert restored.run_requests == 1


@pytest.mark.parametrize("main", [False, True])
async def test_provider_negotiation_installs_deadline_during_active_call(main):
    class Negotiating:
        closed = False

        async def capabilities(self, binding):
            return await model().capabilities(binding)

        async def stream(self, req):
            try:
                await reserve_additional_request("compatibility", purpose="field")
                await asyncio.sleep(1)
                yield response("too late")
            finally:
                self.closed = True

    provider = Negotiating()
    config = ModelRecoveryConfig(episode_seconds=0.02)
    if main:
        from tests.sagents.v2 import test_agent_loop_matrix as native

        runtime, handle, engine, _ = await native.setup_loop(provider)
        create_scope = engine._create_recovery_scope

        async def configured_scope(*args):
            scope = await create_scope(*args)
            scope.config = config
            return scope

        engine._create_recovery_scope = configured_scope
        run = await engine.execute(handle.run_id, native.CONTEXT)
        assert run.state.value == "failed"
        events = await runtime.session_store.read_events(run.run_id)
        assert any(
            getattr(event.data, "error", None)
            and event.data.error.code == "model.recovery_exhausted"
            for event in events
        )
    else:
        with (
            recovery_scope(RecoveryScope(config=config)),
            pytest.raises(SageV2Error) as caught,
        ):
            await collect_response(provider, request())
        assert caught.value.info.code == "model.recovery_exhausted"
    assert provider.closed


@pytest.mark.parametrize("dispatched", [False, True])
async def test_summary_resume_observes_wait_and_charges_uncertain_dispatch(dispatched):
    calls, waits = [], []

    class Summary(ModelConversationSummarizer):
        async def _summarize(self, req, progress):
            calls.append(req)
            assert waits
            return "summary"

    scope = RecoveryScope()
    with recovery_scope(scope):
        await schedule_failure_recovery(
            failure(K.RATE_LIMIT, retry_after_seconds=30), purpose="summary_transport"
        )
    scope.states["operation:summary_transport"] = scope.states[
        "operation:summary_transport"
    ].model_copy(update={"dispatch_started": dispatched})

    async def wait(seconds):
        waits.append(seconds)

    scope.wait = wait
    with recovery_scope(scope):
        await Summary(object()).summarize(
            SummarizationRequest(
                scope=context_scope(),
                messages=(message("long " * 100),),
                target_tokens=100,
            )
        )
    assert len(calls) == 1
    if not dispatched:
        assert waits[0] >= 29
    # The saved reservation already pays for the next summary request.
    assert scope.run_requests == 1 + int(dispatched)


async def test_stale_dispatch_cannot_roll_back_reserved_counters():
    scope = RecoveryScope()
    error = failure(K.TRANSPORT)

    async def reserve():
        state = scope.states.get("operation:call", ModelRecoveryState())
        decision = ModelRecoveryPolicy().decide(
            error, state, scope.config, now=scope.clock()
        )
        state = reserve_recovery(
            state,
            decision,
            scope.config,
            now=scope.clock(),
            logical_call_id="call",
            error=error,
        )
        return await scope.reserve("operation:call", state, error, decision)

    first = await reserve()
    second = await reserve()
    with pytest.raises(SageV2Error, match="Stale recovery dispatch"):
        await scope.record_dispatch("operation:call", first)
    assert scope.states["operation:call"] == second


@pytest.mark.parametrize(
    "finish", ["length", "max_tokens", "max_output_tokens", "MAX_TOKENS"]
)
async def test_simulator_truncation_regenerates_complete_json_for_all_protocols(finish):
    provider = model((json.dumps(STOP), finish), (json.dumps(STOP), "stop"))
    provider.model_binding = "test"

    @asynccontextmanager
    async def factory(req):
        yield provider

    scope = RecoveryScope()
    with recovery_scope(scope):
        result = await DefaultUserSimulator(factory).reply(simulation_request())
    assert result.stop_reason == "completed"
    assert len(provider.requests) == 2
    assert scope.run_requests == 1
    assert provider.requests[1].messages[-1].metadata["inference_view_only"]


@pytest.mark.parametrize(
    "finish", ["length", "max_tokens", "max_output_tokens", "MAX_TOKENS"]
)
async def test_plain_simulator_helper_never_accepts_truncated_text(finish):
    provider = model(("partial", finish))
    provider.model_binding = "test"
    with pytest.raises(UserSimulationExecutionError):
        await generate_user_text(provider, request().messages)


async def test_ambiguous_restored_calls_stop_instead_of_borrowing_a_reservation():
    from sagents.v2.model.recovery_scope import recovery_call

    scope = RecoveryScope()
    error = failure(K.EMPTY)
    with recovery_scope(scope):
        with recovery_call(request(), "auxiliary") as first:
            with recovery_call(request(), "auxiliary") as second:
                decision = ModelRecoveryPolicy().decide(
                    error, ModelRecoveryState(), scope.config, now=scope.clock()
                )
                for key in (first, second):
                    state = reserve_recovery(
                        ModelRecoveryState(),
                        decision,
                        scope.config,
                        now=scope.clock(),
                        logical_call_id=key,
                        error=error,
                    )
                    await scope.reserve(key, state, error, decision)
        provider = model(("must not dispatch", "stop"))
        with pytest.raises(SageV2Error, match="Multiple pending model calls"):
            await collect_response(provider, request())
        assert not provider.requests


async def test_summary_cancellation_during_restored_wait_does_not_dispatch():
    calls = []

    class Summary(ModelConversationSummarizer):
        async def _summarize(self, req, progress):
            calls.append(req)
            return "summary"

    scope = RecoveryScope()
    with recovery_scope(scope):
        await schedule_failure_recovery(
            failure(K.RATE_LIMIT, retry_after_seconds=30), purpose="summary_transport"
        )

    async def cancel(seconds):
        raise asyncio.CancelledError()

    scope.wait = cancel
    with recovery_scope(scope), pytest.raises(asyncio.CancelledError):
        await Summary(object()).summarize(
            SummarizationRequest(
                scope=context_scope(), messages=(message("long"),), target_tokens=100
            )
        )
    assert not calls
    assert scope.run_requests == 1
    assert scope.states["operation:summary_transport"].pending_action is not None


async def test_nested_compatibility_reservation_keeps_identity_after_restart():
    from sagents.v2.model.recovery_scope import recovery_call

    scope = RecoveryScope()
    original = request()
    with recovery_scope(scope):
        with recovery_call(original, "auxiliary") as key:
            await reserve_additional_request("compatibility", purpose="token_field")
    rebuilt = RecoveryScope(
        run_requests=scope.run_requests,
        states={
            key: ModelRecoveryState.model_validate(state.model_dump(mode="json"))
            for key, state in scope.states.items()
        },
        episode_counts=dict(scope.episode_counts),
        episode_deadlines=dict(scope.episode_deadlines),
    )
    with recovery_scope(rebuilt):
        with recovery_call(
            original.model_copy(update={"request_id": "new"}), "auxiliary"
        ) as resumed:
            assert resumed == key
            with pytest.raises(SageV2Error, match="budget exhausted"):
                await reserve_additional_request("compatibility", purpose="token_field")
    assert rebuilt.run_requests == 1


async def test_completed_compatibility_children_are_not_resumed_by_later_calls():
    from sagents.v2.model.recovery_scope import recovery_operation, recovery_call

    class Negotiating:
        async def stream(self, req):
            await reserve_additional_request("compatibility", purpose="field")
            yield response("done")

    scope = RecoveryScope()
    original = request()
    with recovery_scope(scope):
        async with recovery_operation():
            await collect_response(Negotiating(), original)
            assert all(state.pending_action is None for state in scope.states.values())
            previous_keys = tuple(scope.states)
            with recovery_call(original, "auxiliary") as key:
                assert not any(child.startswith(key + ":") for child in previous_keys)


async def test_summary_transport_retry_preserves_existing_empty_response_guidance():
    class Provider:
        def __init__(self):
            self.requests = []

        async def capabilities(self, binding):
            return await model().capabilities(binding)

        async def stream(self, req):
            self.requests.append(req)
            if len(self.requests) == 1:
                yield response("")
            elif len(self.requests) == 2:
                raise SageV2Error(failure(K.TRANSPORT))
            else:
                yield response(
                    json.dumps(
                        dict(
                            summary="short",
                            decisions=[],
                            open_tasks=[],
                            files_touched=[],
                            commands_run=[],
                            important_errors=[],
                            user_requirements=[],
                        )
                    )
                )

    scope = RecoveryScope()

    async def wait(seconds):
        pass

    scope.wait = wait
    provider = Provider()
    with recovery_scope(scope):
        await ModelConversationSummarizer(provider).summarize(
            SummarizationRequest(
                scope=context_scope(),
                messages=(message("source " * 100),),
                target_tokens=100,
            )
        )
    assert len(provider.requests) == 3
    assert provider.requests[2].messages == provider.requests[1].messages
    assert scope.run_requests == 2
