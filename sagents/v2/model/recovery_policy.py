"""Pure model recovery decisions. No network, tools, sleeps or persistence."""

from datetime import datetime, timedelta
import hashlib

from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.model_recovery import (
    ModelFailureKind as Kind,
    ModelRecoveryAction as Action,
    ModelRecoveryConfig,
    ModelRecoveryDecision,
    ModelRecoveryState,
)

# Compatibility exports for integrations using the original module paths.
from sagents.v2.model.failures import (
    annotate_error as annotate_error,
    annotate_stream_failure as annotate_stream_failure,
    failure_from_error as failure_from_error,
    normalize_provider_failure as normalize_provider_failure,
)
from sagents.v2.model.response_validation import checked_response as checked_response

EMPTY_GUIDANCE = (
    "The previous model call ended without a usable answer or tool call. "
    "Continue the original task using the committed conversation and tool results. "
    "If the task is complete, deliver its results and state any unverified requirements; "
    "otherwise perform the necessary next step. Reuse successful results and do not "
    "repeat completed operations. If blocked, explain the specific obstacle. "
    "An empty response is not evidence of task completion."
)
ARGUMENT_GUIDANCE = (
    "The previous response contained an invalid or incomplete tool call. No tool from "
    "that rejected response was executed. Generate fresh complete calls using valid "
    "JSON objects and available tool schemas. Do not continue partial JSON. Use smaller "
    "batches and reuse earlier successful results without repeating operations."
)

STRUCTURED_GUIDANCE = (
    "The previous answer did not match the required JSON contract or was truncated. "
    "Regenerate one shorter, complete valid JSON object matching the requested schema. "
    "Do not append to partial JSON; preserve the original task and committed results."
)


def guidance_for_failure(kind):
    """The same controlled template is used for new and resumed recoveries."""
    if kind in {Kind.EMPTY, Kind.REASONING_ONLY}:
        return EMPTY_GUIDANCE
    if kind == Kind.STRUCTURED_OUTPUT:
        return STRUCTURED_GUIDANCE
    if kind == Kind.ARGUMENTS:
        return ARGUMENT_GUIDANCE
    return None


class ModelRecoveryPolicy:
    def decide(
        self,
        error: RuntimeErrorInfo,
        state: ModelRecoveryState,
        config: ModelRecoveryConfig,
        *,
        now: datetime,
        blocked=False,
        can_compress=False,
        purpose="agent",
        jitter=0.0,
    ):
        failure = failure_from_error(error)
        kind = failure.kind

        def stop(reason):
            return ModelRecoveryDecision(
                action=Action.STOP_WITH_EXPLANATION, reason=reason, kind=kind
            )

        if (
            error.metadata.get("recovery", {}).get("action")
            == Action.STOP_WITH_EXPLANATION.value
        ):
            return stop("nested_recovery_exhausted")
        if blocked or failure.side_effect_state == "unknown":
            return stop("execution_barrier")
        if (
            state.episode_requests >= config.episode_requests
            or state.run_requests >= config.run_requests
        ):
            return stop("recovery_request_budget")
        if state.deadline is not None and now >= state.deadline:
            return stop("recovery_deadline")
        action, counter, limit, guidance = Action.STOP_WITH_EXPLANATION, None, 0, None
        if kind in {
            Kind.TRANSPORT,
            Kind.STREAM,
            Kind.OVERLOADED,
            Kind.RATE_LIMIT,
            Kind.CAPACITY,
        }:
            action, counter, limit = (
                Action.RETRY_SAME_REQUEST,
                "transient",
                config.transient_retries,
            )
        elif purpose != "capability_probe":
            if kind in {Kind.EMPTY, Kind.REASONING_ONLY}:
                action, counter, limit, guidance = (
                    Action.REGENERATE_WITH_GUIDANCE,
                    "empty",
                    config.guidance_retries,
                    guidance_for_failure(kind),
                )
            elif kind in {Kind.ARGUMENTS, Kind.STRUCTURED_OUTPUT}:
                action, counter, limit, guidance = (
                    Action.REGENERATE_WITH_GUIDANCE,
                    "arguments",
                    config.argument_repairs,
                    guidance_for_failure(kind),
                )
            elif kind == Kind.CONTEXT and can_compress:
                action, counter, limit = (
                    Action.REPAIR_REQUEST,
                    "context",
                    config.context_repairs,
                )
        if counter is None:
            return stop("not_automatically_recoverable")
        count = state.counts.get(counter, 0)
        if count >= limit:
            return stop("recovery_attempts_exhausted")
        delay = 0.0
        if action == Action.RETRY_SAME_REQUEST:
            delay = max(
                min(30.0, 2.0 ** min(count, 5) + max(0.0, jitter)),
                failure.retry_after_seconds or 0,
            )
            remaining = (
                (state.deadline - now).total_seconds()
                if state.deadline
                else config.episode_seconds
            )
            if delay >= remaining:
                return stop("retry_after_exceeds_deadline")
        return ModelRecoveryDecision(
            action=action,
            reason="recoverable_model_failure",
            kind=kind,
            counter=counter,
            limit=limit,
            guidance=guidance,
            delay_seconds=delay,
        )


def reserve_recovery(state, decision, config, *, now, logical_call_id, error):
    """Caller persists this reservation BEFORE issuing any additional request."""
    counts = dict(state.counts)
    counts[decision.counter] = counts.get(decision.counter, 0) + 1
    return state.model_copy(
        update={
            "logical_call_id": state.logical_call_id or logical_call_id,
            "counts": counts,
            "episode_requests": state.episode_requests + 1,
            "run_requests": state.run_requests + 1,
            "first_failure_at": state.first_failure_at or now,
            "deadline": state.deadline
            or now + timedelta(seconds=config.episode_seconds),
            "error_fingerprint": hashlib.sha256(
                f"{error.code}:{decision.kind.value}".encode()
            ).hexdigest(),
            "pending_action": decision.action,
            "pending_kind": decision.kind,
            "retry_not_before": now + timedelta(seconds=decision.delay_seconds),
            "guidance_kind": decision.kind
            if decision.guidance
            else state.guidance_kind,
            "dispatch_started": False,
            "guidance_version": "model-guidance/1"
            if decision.guidance
            else state.guidance_version,
        }
    )
