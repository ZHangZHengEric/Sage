"""State-dependent policy coverage, without network requests or real backoff."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.model_recovery import (
    ModelFailure,
    ModelFailureKind as K,
    ModelRecoveryAction as A,
    ModelRecoveryConfig,
    ModelRecoveryState,
)
from sagents.v2.model.failures import annotate_error
from sagents.v2.model.recovery_policy import ModelRecoveryPolicy, guidance_for_failure
from sagents.v2.model.recovery_scope import (
    RecoveryScope,
    recovery_scope,
    recovery_operation,
    reserve_additional_request,
)

NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)
TRANSIENT = {K.TRANSPORT, K.STREAM, K.OVERLOADED, K.RATE_LIMIT, K.CAPACITY}
GUIDED = {K.EMPTY, K.REASONING_ONLY, K.ARGUMENTS, K.STRUCTURED_OUTPUT}


def failure(kind, **facts):
    return annotate_error(
        RuntimeErrorInfo(
            code="fixture.failure",
            category=ErrorCategory.VALIDATION,
            message="Untrusted timeout text must not change classification",
        ),
        ModelFailure(kind=kind, **facts),
    )


@pytest.mark.parametrize("kind", list(K))
@pytest.mark.parametrize(
    "purpose",
    ["agent", "continuation_judge", "tool_selection", "memory", "capability_probe"],
)
def test_every_category_has_an_explicit_bounded_action(kind, purpose):
    decision = ModelRecoveryPolicy().decide(
        failure(kind),
        ModelRecoveryState(),
        ModelRecoveryConfig(),
        now=NOW,
        purpose=purpose,
        can_compress=True,
    )
    expected = A.STOP_WITH_EXPLANATION
    if kind in TRANSIENT:
        expected = A.RETRY_SAME_REQUEST
    elif purpose != "capability_probe":
        if kind in GUIDED:
            expected = A.REGENERATE_WITH_GUIDANCE
        elif kind == K.CONTEXT:
            expected = A.REPAIR_REQUEST
    assert decision.action == expected
    if expected != A.STOP_WITH_EXPLANATION:
        assert decision.counter and decision.limit > 0
        exhausted = ModelRecoveryState(counts={decision.counter: decision.limit})
        assert (
            ModelRecoveryPolicy()
            .decide(
                failure(kind),
                exhausted,
                ModelRecoveryConfig(),
                now=NOW,
                purpose=purpose,
                can_compress=True,
            )
            .action
            == A.STOP_WITH_EXPLANATION
        )
    if expected == A.REGENERATE_WITH_GUIDANCE:
        assert decision.guidance == guidance_for_failure(kind)


@pytest.mark.parametrize("kind", list(K))
@pytest.mark.parametrize(
    "barrier", ["side_effect", "host", "deadline", "run", "episode", "cancel"]
)
def test_barriers_win_for_every_error_category(kind, barrier):
    error = failure(
        kind, side_effect_state="unknown" if barrier == "side_effect" else "not_applied"
    )
    state = ModelRecoveryState(
        deadline=NOW if barrier == "deadline" else None,
        run_requests=24 if barrier == "run" else 0,
        episode_requests=6 if barrier == "episode" else 0,
    )
    if barrier == "cancel":
        error = error.model_copy(update={"category": ErrorCategory.CANCELLED})
    assert (
        ModelRecoveryPolicy()
        .decide(
            error,
            state,
            ModelRecoveryConfig(),
            now=NOW,
            blocked=barrier == "host",
            can_compress=True,
        )
        .action
        == A.STOP_WITH_EXPLANATION
    )


@pytest.mark.parametrize("delay", [120, 121, 1e20, 1e300])
@pytest.mark.parametrize("existing_deadline", [False, True])
def test_huge_retry_after_stops_without_datetime_overflow(delay, existing_deadline):
    decision = ModelRecoveryPolicy().decide(
        failure(K.RATE_LIMIT, retry_after_seconds=delay),
        ModelRecoveryState(
            deadline=NOW + timedelta(seconds=120) if existing_deadline else None
        ),
        ModelRecoveryConfig(),
        now=NOW,
    )
    assert decision.action == A.STOP_WITH_EXPLANATION
    assert decision.reason == "retry_after_exceeds_deadline"


async def test_successful_concurrent_sibling_cannot_close_failed_operation():
    scope = RecoveryScope()
    entered = asyncio.Event()
    failed = asyncio.Event()

    async def bad():
        try:
            async with recovery_operation():
                await entered.wait()
                await reserve_additional_request("arguments", purpose="invalid_output")
                raise ValueError("semantic validation failed")
        finally:
            failed.set()

    async def good():
        async with recovery_operation():
            entered.set()
            await failed.wait()
            return "valid sibling"

    with recovery_scope(scope):
        results = await asyncio.gather(bad(), good(), return_exceptions=True)
    assert isinstance(results[0], ValueError)
    assert results[1] == "valid sibling"
    assert scope.run_requests == 1
    assert scope.episode_counts == {"operation": 1}
    assert scope.episode_deadlines
    assert scope.states["operation:invalid_output"].counts == {"arguments": 1}


@pytest.mark.parametrize("kind", list(GUIDED))
async def test_restart_uses_same_guidance_as_fresh_recovery(kind, monkeypatch):
    from sagents.v2.model.recovery import collect_response
    from sagents.v2.model.recovery_policy import reserve_recovery
    from tests.sagents.v2.test_auxiliary_recovery_boundaries import model, no_wait
    from tests.sagents.v2.test_builtin_model_protocols_matrix import request

    monkeypatch.setattr(RecoveryScope, "wait", no_wait)
    scope = RecoveryScope(clock=lambda: NOW)
    error = failure(kind)
    decision = ModelRecoveryPolicy().decide(
        error, ModelRecoveryState(), scope.config, now=NOW
    )
    reserved = reserve_recovery(
        ModelRecoveryState(),
        decision,
        scope.config,
        now=NOW,
        logical_call_id="original",
        error=error,
    )
    await scope.reserve("operation:auxiliary", reserved, error, decision)
    provider = model(("{}", "stop"))
    with recovery_scope(scope):
        await collect_response(provider, request(), purpose="auxiliary")
    guidance = provider.requests[0].messages[-1]
    assert guidance.content[0].text == decision.guidance
    assert guidance.metadata["inference_view_only"] is True
    assert scope.run_requests == 1
    assert not scope.episode_counts


async def test_concurrent_success_closes_episode_once_and_preserves_run_total():
    scope = RecoveryScope()
    persisted = []
    both_entered = asyncio.Event()

    async def persist(*args):
        persisted.append(args)

    scope.persist = persist

    async def operation(first):
        async with recovery_operation():
            if first:
                await reserve_additional_request("arguments", purpose="repair")
                await both_entered.wait()
            else:
                both_entered.set()

    with recovery_scope(scope):
        await asyncio.gather(operation(True), operation(False))
    assert scope.run_requests == 1
    assert not scope.episode_counts
    assert not scope.states
    assert (
        len([args for args in persisted if args[2].metadata.get("episode_closed")]) == 1
    )
