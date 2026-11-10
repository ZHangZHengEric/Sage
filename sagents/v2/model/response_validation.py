"""Validate completed model output before committing text or executing tools."""

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.model_recovery import (
    ModelFailure,
    ModelFailureKind as Kind,
    ModelTermination,
)
from sagents.v2.model.failures import annotate_error


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
    if (
        termination == ModelTermination.TRUNCATED
        and not response.tool_calls
        and request is not None
        and (
            request.response_schema is not None
            or request.response_format == "json_object"
            or request.metadata.get("output_validation_schema") is not None
        )
        and request.metadata.get("purpose") != "conversation_summary"
    ):
        raise SageV2Error(
            annotate_error(
                RuntimeErrorInfo(
                    code="model.structured_output_invalid",
                    category=ErrorCategory.VALIDATION,
                    message="Structured output was truncated; regenerate a shorter complete object.",
                    safe_to_resume=True,
                    metadata={"usage": response.usage.model_dump(mode="json")},
                ),
                ModelFailure(
                    kind=Kind.STRUCTURED_OUTPUT,
                    terminal_received=True,
                    native_finish_reason=response.finish_reason,
                ),
            )
        )
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
    elif termination == ModelTermination.EMPTY or (
        termination in {ModelTermination.COMPLETE, ModelTermination.TOOL_CALLS}
        and not response.text.strip()
        and not response.tool_calls
    ):
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
                or request.metadata.get("output_validation_schema") is not None
            )
            and request.metadata.get("purpose")
            not in {"continuation_judge", "conversation_summary"}
        ):
            import json
            from jsonschema import validate, ValidationError

            try:
                text = response.text.strip()
                if request.metadata.get("json_fence_compatible") and text.startswith(
                    "```"
                ):
                    lines = text.splitlines()
                    if len(lines) > 2 and lines[-1].strip() == "```":
                        text = "\n".join(lines[1:-1])
                value = json.loads(text)
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
