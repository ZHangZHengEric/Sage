"""Pure model recovery decisions. No network, tools, sleeps or persistence."""

from datetime import datetime, timedelta
import hashlib

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.model_recovery import (
    ModelFailure,
    ModelFailureKind as Kind,
    ModelRecoveryAction as Action,
    ModelRecoveryConfig,
    ModelRecoveryDecision,
    ModelRecoveryState,
    ModelTermination,
)

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

_CODES = {
    "model.internal_error": Kind.INTERNAL,
    "model.empty_semantic_response": Kind.EMPTY,
    "model.empty_response": Kind.EMPTY,
    "model.reasoning_only": Kind.REASONING_ONLY,
    "model.stream_incomplete": Kind.STREAM,
    "model.context_window_exceeded": Kind.CONTEXT,
    "model.response_blocked": Kind.REFUSED,
    "model.response_refused": Kind.REFUSED,
    "model.response_paused": Kind.PAUSED,
    "model.response_invalid": Kind.PROTOCOL,
    "model.response_unsupported": Kind.UNSUPPORTED,
    "model.provider_state_invalid": Kind.STATE,
    "model.queue_full": Kind.CAPACITY,
    "model.queue_timeout": Kind.CAPACITY,
    "model.output_budget_exceeded": Kind.INVALID_REQUEST,
    "model.response_unknown": Kind.PROTOCOL,
    "model.capability_unsupported": Kind.UNSUPPORTED,
    "model.reasoning_effort_unsupported": Kind.UNSUPPORTED,
    "model.extra_body_conflict": Kind.INVALID_REQUEST,
    "model.media_mime_type_missing": Kind.MEDIA,
    "model.system_content_unsupported": Kind.UNSUPPORTED,
    "model.tool_call_missing": Kind.STATE,
    "model.response_rejected": Kind.PROTOCOL,
    "model.tool_arguments_invalid_json": Kind.ARGUMENTS,
    "model.tool_arguments_not_object": Kind.ARGUMENTS,
    "model.tool_arguments_truncated": Kind.ARGUMENTS,
    "model.tool_name_missing": Kind.ARGUMENTS,
    "model.structured_output_invalid": Kind.STRUCTURED_OUTPUT,
}


def failure_from_error(error: RuntimeErrorInfo) -> ModelFailure:
    # Host cancellation, budgets and effect barriers override provider claims.
    if error.category == ErrorCategory.CANCELLED:
        return ModelFailure(kind=Kind.CANCELLED)
    if error.code.startswith("budget.") or error.code == "model.recovery_exhausted":
        return ModelFailure(kind=Kind.BUDGET)
    if (
        error.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT
        or error.metadata.get("side_effect_state") == "unknown"
    ):
        return ModelFailure(kind=Kind.STATE, side_effect_state="unknown")
    raw = error.metadata.get("model_failure")
    if isinstance(raw, dict):
        try:
            return ModelFailure.model_validate(raw)
        except ValueError:
            pass  # Old/custom providers still use the conservative legacy mapping.
    kind = _CODES.get(error.code, Kind.UNKNOWN)
    if error.code.startswith("budget.") or error.code == "model.recovery_exhausted":
        kind = Kind.BUDGET
    elif error.category == ErrorCategory.CANCELLED:
        kind = Kind.CANCELLED
    elif kind == Kind.UNKNOWN:
        if error.category == ErrorCategory.RATE_LIMITED and error.retryable:
            kind = Kind.RATE_LIMIT
        elif error.category == ErrorCategory.PROVIDER_TRANSIENT and error.retryable:
            kind = Kind.TRANSPORT
    return ModelFailure(
        kind=kind,
        native_code=error.provider_code,
        response_started=bool(error.metadata.get("response_started")),
        usage=error.metadata.get("usage"),
        side_effect_state="unknown"
        if error.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT
        else "not_applied",
    )


def annotate_error(error: RuntimeErrorInfo, failure: ModelFailure) -> RuntimeErrorInfo:
    return error.model_copy(
        update={
            "metadata": {
                **error.metadata,
                "model_failure": failure.model_dump(mode="json"),
            }
        }
    )


def checked_response(response, request=None):
    """Validate semantic completion before committing Items or executing tools."""
    if len({call.tool_call_id for call in response.tool_calls}) != len(
        response.tool_calls
    ):
        raise SageV2Error(
            annotate_error(
                RuntimeErrorInfo(
                    code="model.response_invalid",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="The model returned conflicting tool call identifiers.",
                    safe_to_resume=True,
                ),
                ModelFailure(
                    kind=Kind.PROTOCOL,
                    terminal_received=True,
                    provider=response.provider_metadata.get("provider_id"),
                    has_tool_calls=True,
                ),
            )
        )
    termination = response.termination
    if termination == ModelTermination.TRUNCATED and response.tool_calls:
        raise SageV2Error(
            annotate_error(
                RuntimeErrorInfo(
                    code="model.tool_arguments_truncated",
                    category=ErrorCategory.VALIDATION,
                    message="Output limit interrupted tool generation; no calls were executed.",
                    safe_to_resume=True,
                    metadata={"usage": response.usage.model_dump(mode="json")},
                ),
                ModelFailure(
                    kind=Kind.ARGUMENTS,
                    terminal_received=True,
                    has_tool_calls=True,
                    native_finish_reason=response.finish_reason,
                ),
            )
        )
    kind = None
    code = None
    if termination == ModelTermination.REFUSED:
        kind, code = Kind.REFUSED, "model.response_refused"
    elif termination == ModelTermination.PAUSED:
        kind, code = Kind.PAUSED, "model.response_paused"
    elif termination == ModelTermination.UNKNOWN:
        kind, code = Kind.PROTOCOL, "model.response_unknown"
    elif termination == ModelTermination.EMPTY:
        kind = Kind.REASONING_ONLY if response.reasoning.strip() else Kind.EMPTY
        code = (
            "model.reasoning_only"
            if kind == Kind.REASONING_ONLY
            else "model.empty_semantic_response"
        )
    if kind is None:
        if (
            request is not None
            and not response.tool_calls
            and termination != ModelTermination.TRUNCATED
            and (
                request.response_schema is not None
                or request.response_format == "json_object"
            )
            and request.metadata.get("purpose")
            not in {"continuation_judge", "conversation_summary"}
        ):
            import json
            from jsonschema import validate, ValidationError

            try:
                value = json.loads(response.text)
                schema = request.response_schema or request.metadata.get(
                    "output_validation_schema"
                )
                if schema is not None:
                    validate(value, schema)
                elif not isinstance(value, dict):
                    raise ValueError("JSON object required")
            except (ValueError, ValidationError) as exc:
                raise SageV2Error(
                    annotate_error(
                        RuntimeErrorInfo(
                            code="model.structured_output_invalid",
                            category=ErrorCategory.VALIDATION,
                            message="Model output did not match the requested JSON contract.",
                            safe_to_resume=True,
                            metadata={"usage": response.usage.model_dump(mode="json")},
                        ),
                        ModelFailure(
                            kind=Kind.STRUCTURED_OUTPUT, terminal_received=True
                        ),
                    )
                ) from exc
        return response
    failure = ModelFailure(
        kind=kind,
        provider=response.provider_metadata.get("provider_id"),
        native_finish_reason=response.finish_reason,
        terminal_received=True,
        has_text=bool(response.text.strip()),
        has_reasoning=bool(response.reasoning.strip()),
        has_tool_calls=bool(response.tool_calls),
        response_id=response.response_id,
        usage=response.usage.model_dump(mode="json")
        if response.usage.reported
        else None,
    )
    raise SageV2Error(
        annotate_error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message={
                    Kind.EMPTY: "The model returned no usable answer or tool call.",
                    Kind.REASONING_ONLY: "The model returned reasoning but no answer or tool call.",
                    Kind.REFUSED: "The model declined or filtered this response.",
                    Kind.PAUSED: "The model requested protocol continuation that is not supported by this route.",
                    Kind.PROTOCOL: "The model returned an unrecognized termination reason.",
                }[kind],
                safe_to_resume=True,
                metadata={
                    "usage": response.usage.model_dump(mode="json"),
                    "refusal_text": response.text if kind == Kind.REFUSED else None,
                },
            ),
            failure,
        )
    )


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
                    EMPTY_GUIDANCE,
                )
            elif kind in {Kind.ARGUMENTS, Kind.STRUCTURED_OUTPUT}:
                action, counter, limit, guidance = (
                    Action.REGENERATE_WITH_GUIDANCE,
                    "arguments",
                    config.argument_repairs,
                    (
                        "The previous answer did not match the required JSON contract. Return one complete valid JSON object matching the requested schema; preserve the original task and committed results."
                        if kind == Kind.STRUCTURED_OUTPUT
                        else ARGUMENT_GUIDANCE
                    ),
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
            deadline = state.deadline or now + timedelta(seconds=config.episode_seconds)
            if now + timedelta(seconds=delay) >= deadline:
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
            "guidance_kind": decision.kind if decision.guidance else state.guidance_kind,
            "dispatch_started": False,
            "guidance_version": "model-guidance/1"
            if decision.guidance
            else state.guidance_version,
        }
    )


def normalize_provider_failure(error, provider):
    failure = failure_from_error(error)
    failure = failure.model_copy(
        update={
            "provider": provider,
            "native_finish_reason": error.metadata.get("finish_reason")
            or error.metadata.get("native_finish_reason")
            or failure.native_finish_reason,
            "usage": error.metadata.get("usage") or failure.usage,
        }
    )
    return annotate_error(error, failure)
