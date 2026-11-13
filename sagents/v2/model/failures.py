"""Provider-independent failure facts. No recovery decisions or execution."""

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.model_recovery import ModelFailure, ModelFailureKind as Kind

_CODES = {
    "model.internal_error": Kind.INTERNAL,
    "model.empty_semantic_response": Kind.EMPTY,
    "model.empty_response": Kind.EMPTY,
    "model.reasoning_only": Kind.REASONING_ONLY,
    "model.stream_incomplete": Kind.STREAM,
    "model.context_window_exceeded": Kind.CONTEXT,
    "model.request_too_large": Kind.PAYLOAD,
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
    "model.image_workspace_unavailable": Kind.MEDIA,
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
    if kind == Kind.UNKNOWN:
        if error.category == ErrorCategory.RATE_LIMITED and error.retryable:
            kind = Kind.RATE_LIMIT
        elif error.category == ErrorCategory.PROVIDER_TRANSIENT and error.retryable:
            kind = Kind.TRANSPORT
    return ModelFailure(
        kind=kind,
        native_code=error.provider_code,
        response_started=bool(error.metadata.get("response_started")),
        usage=error.metadata.get("usage"),
        side_effect_state="not_applied",
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


def annotate_stream_failure(
    error, *, provider, usage, response_id, terminal_received, text, reasoning, tools
):
    """Keep already observed usage and progress when a stream fails or ends early."""
    error = normalize_provider_failure(error, provider)
    failure = failure_from_error(error).model_copy(
        update={
            "usage": usage.model_dump(mode="json") if usage.reported else None,
            "response_id": response_id,
            "terminal_received": terminal_received,
            "has_text": bool(text),
            "has_reasoning": bool(reasoning),
            "has_tool_calls": bool(tools),
        }
    )
    return annotate_error(
        error.model_copy(
            update={
                "metadata": {
                    **error.metadata,
                    "usage": usage.model_dump(mode="json"),
                }
            }
        ),
        failure,
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
