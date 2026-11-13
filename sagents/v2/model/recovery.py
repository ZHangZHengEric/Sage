"""API-driven bounded recovery for read-only auxiliary model requests.

No input token estimates are made. The original request is immutable; only a
retry projection is replaced. Model calls never execute returned Tool calls.
"""

from __future__ import annotations

from sagents.v2.model.recovery_scope import scoped_recovery

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model.contracts import ModelEventKind


@dataclass
class ModelCallBudget:
    remaining: int = 64

    def consume(self):
        if self.remaining <= 0:
            raise recovery_error(
                "model.context_recovery_exhausted",
                "Context recovery reached its model-call limit",
            )
        self.remaining -= 1


_active_budget: ContextVar[ModelCallBudget | None] = ContextVar("model_context_recovery_budget", default=None)


@contextmanager
def model_call_budget():
    budget = _active_budget.get() or ModelCallBudget()
    token = _active_budget.set(budget)
    try:
        yield budget
    finally:
        _active_budget.reset(token)


def consume_model_call():
    budget = _active_budget.get()
    if budget is not None:
        budget.consume()


def recovery_error(code, message, *, metadata=None):
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=ErrorCategory.VALIDATION,
            message=message,
            safe_to_resume=True,
            metadata=metadata or {},
        )
    )


def is_context_overflow(error):
    return (
        isinstance(error, SageV2Error)
        and error.info.code == "model.context_window_exceeded"
    )


async def adaptive_summary(text, summarize, *, depth=0, merge=None):
    """Try the complete source first; only API rejection permits splitting.

    Both halves are processed before merging. No prefix/tail is discarded and
    no canonical coverage may advance until the complete operation succeeds.
    """
    try:
        result = await summarize(text)
        if not result or not result.strip():
            raise recovery_error(
                "context.summary_empty", "Summary returned no usable content"
            )
        return result
    except SageV2Error as exc:
        if not is_context_overflow(exc):
            raise
        if depth >= 12 or len(text) < 2:
            raise recovery_error(
                "model.context_irreducible",
                "The API rejected the smallest recoverable summary source",
            ) from exc
        middle = len(text) // 2
        first = await adaptive_summary(
            text[:middle], summarize, depth=depth + 1, merge=merge
        )
        second = await adaptive_summary(
            text[middle:], summarize, depth=depth + 1, merge=merge
        )
        merged = merge(first, second) if merge is not None else first + "\n" + second
        # This is a direct content-length comparison, never a token estimate.
        if len(merged) >= len(text):
            raise recovery_error(
                "context.summary_no_progress",
                "Summary splitting did not reduce its source",
            ) from exc
        if merge is not None:
            # Structured children already succeeded through the API. Preserve
            # their facts instead of asking another LLM pass to discard some.
            return merged
        return await adaptive_summary(merged, summarize, depth=depth + 1)


def reported_context_limit_error(response, capabilities):
    """A configured model ceiling is a trigger even if the API accepts input."""
    maximum = capabilities.max_input_tokens
    if maximum and response.usage.reported and response.usage.input_tokens >= maximum:
        return SageV2Error(
            RuntimeErrorInfo(
                code="model.context_window_exceeded",
                category=ErrorCategory.VALIDATION,
                message="Reported input usage reached the configured model limit",
                safe_to_resume=True,
                metadata={
                    "trigger": "reported_input_limit",
                    "input_tokens": response.usage.input_tokens,
                    "max_input_tokens": maximum,
                },
            )
        )
    return None


async def _next_controlled_event(iterator, scope):
    if scope.check is None:
        return await anext(iterator)
    pending = asyncio.create_task(anext(iterator))
    try:
        while not pending.done():
            await asyncio.wait({pending}, timeout=.25)
            await scope.check()
        return pending.result()
    finally:
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)


@scoped_recovery
async def collect_response(model, request, *, transient_retries=None, purpose=None, idle_timeout_seconds=None, on_event=None, manage_transport=True, request_timeout_seconds=None, timeout_error=None):
    from sagents.v2.contracts.common import new_id
    from sagents.v2.contracts.items import TextBlock
    from sagents.v2.model.contracts import ModelMessage
    from sagents.v2.contracts.model_recovery import ModelRecoveryAction
    from sagents.v2.model.recovery_policy import ModelRecoveryPolicy, checked_response, reserve_recovery
    from sagents.v2.model.recovery_scope import recovery_scope, recovery_call, resume_pending_recovery
    import random

    with recovery_scope() as scope, recovery_call(request, purpose) as key:
        config = scope.config
        if transient_retries is not None:
            config = config.model_copy(update={"transient_retries": min(transient_retries, config.transient_retries)})
        purpose = purpose or request.metadata.get("purpose", "auxiliary")
        state = await resume_pending_recovery(scope, key, purpose)
        if purpose == "capability_probe":
            request = request.model_copy(update={"metadata": {**request.metadata, "capability_probe": True}})
        original = request
        if state.pending_action is not None:
            from sagents.v2.model.recovery_policy import guidance_for_failure
            guidance_kind = state.guidance_kind or (state.pending_kind if state.pending_action == ModelRecoveryAction.REGENERATE_WITH_GUIDANCE else None)
            if guidance_kind is not None:
                guidance = guidance_for_failure(guidance_kind)
                request = original.model_copy(update={"messages": (*original.messages,
                    ModelMessage(role="user", content=(TextBlock(text=guidance),),
                        metadata={"inference_view_only": True, "runtime_continuation_guidance": True}))})
        while True:
            if scope.check is not None:
                await scope.check()
            state = state.model_copy(update={
                "deadline": state.deadline or scope.episode_deadlines.get(scope.step_key),
                "episode_requests": max(state.episode_requests, scope.episode_counts.get(scope.step_key, 0)),
                "run_requests": scope.run_requests,
            })
            if state.deadline is not None:
                scope.episode_deadlines.setdefault(scope.step_key, state.deadline)
            consume_model_call()
            if state.deadline is not None and scope.clock() >= state.deadline:
                raise recovery_error("model.recovery_exhausted", "Model recovery deadline reached",
                    metadata=state.first_failure_metadata())
            state = await scope.record_dispatch(key, state)
            from sagents.v2.model.stream_errors import normalized_model_stream
            stream = normalized_model_stream(model, request)
            response = None
            try:
                async with scope.enforce_deadline():
                    try:
                        async with asyncio.timeout(request_timeout_seconds):
                            iterator = aiter(stream)
                            while True:
                                try:
                                    async with asyncio.timeout(idle_timeout_seconds):
                                        event = await _next_controlled_event(iterator, scope)
                                except StopAsyncIteration:
                                    break
                                except TimeoutError as exc:
                                    raise SageV2Error(RuntimeErrorInfo(code="context.summarizer.model_timeout",
                                        category=ErrorCategory.PROVIDER_TRANSIENT,
                                        message="Model response progress stalled", retryable=True, safe_to_resume=True,
                                        metadata={"timeout_kind": "idle"})) from exc
                                if on_event is not None:
                                    on_event(event)
                                if event.kind == ModelEventKind.COMPLETED:
                                    response = event.response
                                    if response is not None:
                                        break
                    except TimeoutError as exc:
                        raise SageV2Error(timeout_error or RuntimeErrorInfo(
                            code="model.request_timeout", category=ErrorCategory.PROVIDER_TRANSIENT,
                            message="Model request timed out", retryable=True, safe_to_resume=True,
                        )) from exc
                if response is None:
                    raise SageV2Error(RuntimeErrorInfo(code="model.stream_incomplete",
                        category=ErrorCategory.PROVIDER_TRANSIENT,
                        message="Auxiliary model stream ended before completion", retryable=True, safe_to_resume=True))
                if purpose != "capability_probe" and not (
                    purpose == "continuation_judge" and response.reasoning.strip() and not response.text.strip()
                    and response.termination.value == "empty"
                ):
                    # A Judge validates its private structured reasoning fallback;
                    # it is never a user-facing answer or an automatic completion.
                    checked_response(response, request)
                await scope.complete_call(key, state)
                return response
            except TimeoutError as exc:
                raise recovery_error("model.recovery_exhausted", "Model recovery deadline reached",
                    metadata=state.first_failure_metadata()) from exc
            except SageV2Error as exc:
                if scope.record_failed_usage is not None:
                    from sagents.v2.contracts.items import UsageSummary
                    from sagents.v2.model.recovery_policy import failure_from_error
                    usage = UsageSummary.model_validate(exc.info.metadata.get("usage") or failure_from_error(exc.info).usage or {})
                    await scope.record_failed_usage(usage)
                if not manage_transport and exc.info.retryable and exc.info.category in {
                    ErrorCategory.PROVIDER_TRANSIENT, ErrorCategory.RATE_LIMITED
                }:
                    raise
                state = state.model_copy(update={"run_requests": scope.run_requests})
                decision = ModelRecoveryPolicy().decide(exc.info, state, config,
                    now=scope.clock(), purpose=purpose, jitter=random.uniform(0, .25))
                if decision.action == ModelRecoveryAction.STOP_WITH_EXPLANATION:
                    raise SageV2Error(exc.info.model_copy(update={"metadata": {**exc.info.metadata,
                        **state.first_failure_metadata(),
                        "recovery": {"version": "model-recovery/1", **decision.model_dump(mode="json"),
                                     "attempt": state.episode_requests}}})) from exc
                state = reserve_recovery(state, decision, config, now=scope.clock(),
                    logical_call_id=original.request_id, error=exc.info)
                state = await scope.reserve(key, state, exc.info, decision)
            finally:
                closer = getattr(stream, "aclose", None)
                if closer is not None:
                    await closer()
            if decision.delay_seconds:
                await scope.wait(decision.delay_seconds)
            if decision.action == ModelRecoveryAction.RETRY_SAME_REQUEST:
                request = request.model_copy(update={"request_id": new_id("model_recovery"),
                    "metadata": {**request.metadata, "logical_request_id": state.logical_call_id,
                                 "recovery_attempt": state.episode_requests}})
                continue
            suffix = ()
            if decision.guidance:
                suffix = (ModelMessage(role="user", content=(TextBlock(text=decision.guidance),),
                    metadata={"inference_view_only": True, "runtime_continuation_guidance": True}),)
            request = original.model_copy(update={"request_id": new_id("model_recovery"),
                "messages": (*original.messages, *suffix),
                "metadata": {**original.metadata, "logical_request_id": state.logical_call_id,
                             "recovery_attempt": state.episode_requests}})


async def execute_recoverable_operation(operation, *, scope, key, purpose, transient_retries=None, on_retry=None):
    """Shared transport recovery for an operation owning its output validation."""
    from sagents.v2.contracts.model_recovery import ModelFailureKind
    from sagents.v2.model.failures import failure_from_error
    from sagents.v2.model.recovery_scope import resume_pending_recovery, schedule_failure_recovery
    state = await resume_pending_recovery(scope, key, purpose)
    while True:
        if scope.check is not None:
            await scope.check()
        state = await scope.record_dispatch(key, state)
        try:
            async with scope.enforce_deadline():
                result = await operation()
        except SageV2Error as exc:
            if failure_from_error(exc.info).kind not in {
                ModelFailureKind.TRANSPORT, ModelFailureKind.STREAM, ModelFailureKind.RATE_LIMIT,
                ModelFailureKind.OVERLOADED, ModelFailureKind.CAPACITY,
            }:
                raise
            decision = await schedule_failure_recovery(exc.info, purpose=purpose, key=key, transient_retries=transient_retries)
            if on_retry is not None:
                on_retry(exc.info, decision)
            state = await resume_pending_recovery(scope, key, purpose)
        else:
            await scope.complete_call(key, state)
            return result
