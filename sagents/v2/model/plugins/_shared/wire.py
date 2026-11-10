"""Provider-wire helpers shared by the built-in model adapters.

This module deliberately contains no SDK-specific imports.  Keeping the small
normalization helpers here makes each adapter independently testable and lets a
host inject either an official SDK client or a protocol-compatible test client.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.model.contracts import ModelToolCall


def minimum_reasoning_control(
    strategy: Mapping[str, Any], *, default_disable: str
) -> tuple[str, str | None]:
    """Prefer a probed disable dialect, otherwise the lowest verified effort.

    Unprobed routes try the protocol's explicit disable control. A profile whose
    default is non-reasoning needs no explicit effort parameter.
    """
    disable = strategy.get("reasoning_disable_strategy")
    if disable and disable != "omit":
        return str(disable), None
    if strategy.get("reasoning_behavior") in {"none", "controllable"}:
        return "omit", None
    supported = strategy.get("supported_reasoning_efforts", ())
    for effort in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
        if effort in supported:
            return str(
                strategy.get("reasoning_effort_strategy", "reasoning_effort")
            ), effort
    if disable == "omit" and "supported_reasoning_efforts" in strategy:
        # A verified route may always reason while accepting no control at all.
        # Do not turn a minimum request into a parameter already known invalid.
        return "omit", None
    return default_disable, None


def validate_extra_body(
    extra_body: Mapping[str, Any],
    *,
    reserved_fields: frozenset[str],
    provider: str,
) -> None:
    """Prevent provider extensions from replacing host-owned request fields."""

    conflicts = sorted(set(extra_body).intersection(reserved_fields))
    if not conflicts:
        return
    raise SageV2Error(
        RuntimeErrorInfo(
            code="model.extra_body_conflict",
            category=ErrorCategory.VALIDATION,
            message=(
                f"{provider} extra_body cannot override host-owned fields: "
                + ", ".join(conflicts)
            ),
            safe_to_resume=True,
            metadata={
                "provider": provider,
                "fields": conflicts,
                "side_effect_state": "not_applied",
            },
        )
    )


def stream_incomplete_error(*, provider: str, response_started: bool) -> SageV2Error:
    """Report a transport EOF that arrived before the provider terminal event."""

    return SageV2Error(
        RuntimeErrorInfo(
            code="model.stream_incomplete",
            category=ErrorCategory.PROVIDER_TRANSIENT,
            message=(
                f"{provider} stream ended before a terminal response event was received"
            ),
            retryable=True,
            safe_to_resume=True,
            metadata={
                "provider": provider,
                "response_started": response_started,
            },
        )
    )


def wire_value(value: Any, name: str, default: Any = None) -> Any:
    """Read one field from an SDK object or a decoded JSON mapping."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def wire_json_value(value: Any) -> Any:
    """Convert SDK wire objects to JSON-safe provider continuation state."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): wire_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [wire_json_value(item) for item in value]
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return wire_json_value(dumper(mode="json", exclude_none=True))
    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, Mapping):
        return {
            str(key): wire_json_value(item)
            for key, item in attributes.items()
            if not str(key).startswith("_") and item is not None
        }
    raise TypeError(f"provider wire value is not JSON serializable: {type(value)!r}")


def compact_json(value: Any) -> str:
    """Serialize provider arguments deterministically without ASCII escaping."""

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def parse_tool_arguments(
    raw: str | None,
    *,
    tool_call_id: str | None,
    name: str | None,
    diagnostic_context: Mapping[str, Any] | None = None,
) -> ModelToolCall:
    """Decode one provider tool call into the strict v2 contract."""

    diagnostic = {
        **dict(diagnostic_context or {}),
        "tool_call_id": tool_call_id,
        "tool_name": name,
        "arguments_sha256": hashlib.sha256((raw or "").encode()).hexdigest(),
        "arguments_length": len(raw or ""),
        "side_effect_state": "not_applied",
        "tool_execution_started": False,
    }

    def invalid(code, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=message,
                retryable=True,
                safe_to_resume=True,
                metadata=diagnostic,
            )
        )

    if diagnostic.get("finish_reason") in {"length", "max_tokens", "max_output_tokens"}:
        raise invalid(
            "model.tool_arguments_truncated",
            "model output limit interrupted tool arguments before execution",
        )
    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise invalid(
            "model.tool_arguments_invalid_json",
            f"model returned invalid tool arguments: {exc}",
        ) from exc
    if not isinstance(arguments, dict):
        raise invalid(
            "model.tool_arguments_not_object",
            "model tool arguments must decode to an object",
        )
    if not name:
        raise invalid(
            "model.tool_name_missing", "model returned a tool call without a name"
        )
    return ModelToolCall(
        tool_call_id=tool_call_id or new_id("tool_call"),
        name=name,
        arguments=arguments,
    )


_CONTEXT_WINDOW_MARKERS = (
    "context_length_exceeded",
    "context window exceeded",
    "maximum context length",
    "prompt is too long",
    "input is too long",
    "too many tokens",
)


class ProviderStreamFailure(RuntimeError):
    """Structured provider rejection delivered inside a successful HTTP stream."""

    def __init__(self, message, *, code=None, body=None, status_code=None):
        super().__init__(message)
        self.code = code
        self.body = body
        self.status_code = status_code


def provider_error(exc: Exception, *, response_started: bool = False, provider: str | None = None) -> SageV2Error:
    """Normalize HTTP and successful-HTTP error envelopes before choosing recovery."""
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    import math
    from sagents.v2.contracts.model_recovery import ModelFailure, ModelFailureKind as K
    from sagents.v2.model.recovery_policy import annotate_error

    if isinstance(exc, SageV2Error):
        return exc
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    body = getattr(exc, "body", None)
    if not isinstance(body, Mapping) and response is not None:
        try:
            body = response.json()
        except (ValueError, RuntimeError, AttributeError):
            body = None
    payload = body.get("error", body) if isinstance(body, Mapping) else {}
    if not isinstance(payload, Mapping):
        payload = {}
    native = getattr(exc, "code", None) or payload.get("code") or payload.get("type") or payload.get("status")
    native = str(native) if native is not None else None
    types = {str(v).lower() for v in (native, payload.get("type"), payload.get("status")) if v}
    details = " ".join(str(v) for v in (exc, native, payload.get("message")) if v).lower()
    names = {cls.__name__ for cls in type(exc).__mro__}
    configuration_details = details
    cause = exc.__cause__
    for _ in range(8):
        if cause is None:
            break
        names.update(cls.__name__ for cls in type(cause).__mro__)
        configuration_details += " " + str(cause).lower()
        cause = cause.__cause__
    quota = {"insufficient_quota", "billing_hard_limit_reached", "billing_not_active",
             "organization_usage_limit_exceeded", "usage_limit_reached", "credit_balance_too_low", "billing_error", "insufficient_balance", "out_of_credits"}
    quota_details = payload.get("details", [])
    hard_quota = any(
        isinstance(detail, Mapping) and str(detail.get("@type", "")).endswith("QuotaFailure")
        and any(isinstance(violation, Mapping) and any(marker in str(violation.get("quotaId", "")).lower()
            for marker in ("perday", "per_day", "daily")) for violation in detail.get("violations", []))
        for detail in quota_details if isinstance(quota_details, list)
    ) if isinstance(quota_details, list) else False
    kind = K.UNKNOWN
    if status == 401 or types & {"authentication_error", "invalid_api_key", "unauthenticated"}:
        kind = K.AUTHENTICATION
    elif status == 403 or types & {"permission_error", "permission_denied", "access_denied"}:
        kind = K.PERMISSION
    elif types & quota or hard_quota or (status in {400, 429} and any(v in details for v in
        ("insufficient credits", "credit balance is too low", "billing hard limit", "daily quota exceeded"))):
        kind = K.QUOTA
    elif status == 404 or types & {"model_not_found", "not_found_error"}:
        kind = K.ROUTE
    elif status in {None, 200, 400, 413, 422} and (
        types & {"context_length_exceeded", "context_window_exceeded", "prompt_too_long"}
        or ((not types or types <= {"invalid_request_error", "invalid_request", "invalid_argument", "bad_request"})
            and (any(v in details for v in _CONTEXT_WINDOW_MARKERS)
                 or ("input token count" in details and "exceeds" in details)))):
        kind = K.CONTEXT
    elif types & {"content_filter", "content_policy_violation", "safety", "content_blocked", "refusal"}:
        kind = K.REFUSED
    elif types & {"invalid_image", "image_parse_error", "image_url_invalid", "media_invalid", "unsupported_mime_type"}:
        kind = K.MEDIA
    elif status == 413:
        kind = K.PAYLOAD
    elif status == 429 or types & {"rate_limit_exceeded", "rate_limit_error", "resource_exhausted"}:
        kind = K.RATE_LIMIT
    elif status in {400, 422} or types & {"invalid_request_error", "invalid_argument"}:
        kind = K.INVALID_REQUEST
    elif status in {501, 505} or types & {"not_implemented", "unsupported_operation", "unsupported_endpoint"}:
        kind = K.UNSUPPORTED
    elif status in {500, 502, 503, 504, 529} or types & {
        "server_error", "internal_server_error", "overloaded_error", "server_is_overloaded", "no_capacity", "api_error", "response_failed"}:
        kind = K.OVERLOADED
    elif status in {408, 409, 425}:
        kind = K.TRANSPORT
    elif native == "invalid_provider_response" and status in {None, 200} and (
        response_started or (isinstance(exc, ProviderStreamFailure)
        and str(exc).strip().rstrip(".").casefold() == "response stream could not be completed")):
        kind = K.STREAM
    elif names & {"InvalidURL", "UnsupportedProtocol", "ProxyError", "SSLCertVerificationError"} or any(
        v in configuration_details for v in ("certificate verify failed", "invalid url", "unsupported protocol")):
        kind = K.INVALID_REQUEST
    elif isinstance(exc, (TimeoutError, ConnectionError)) or names & {
        "APIConnectionError", "APITimeoutError", "TransportError", "ReadTimeout", "ConnectTimeout"}:
        kind = K.TRANSPORT
    retry_after = None
    headers = getattr(response, "headers", {}) or {}
    raw = headers.get("retry-after")
    if raw:
        try:
            retry_after = float(raw)
        except (ValueError, TypeError):
            try:
                retry_after = (parsedate_to_datetime(raw) - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                pass
        if retry_after is not None and (not math.isfinite(retry_after) or retry_after < 0):
            retry_after = None
    retryable = kind in {K.TRANSPORT, K.STREAM, K.OVERLOADED, K.RATE_LIMIT}
    category = (ErrorCategory.PROVIDER_TRANSIENT if retryable else ErrorCategory.PROVIDER_PERMANENT)
    if kind == K.CONTEXT:
        category = ErrorCategory.VALIDATION
    code = "model.context_window_exceeded" if kind == K.CONTEXT else (
        "model.provider_transient" if retryable else "model.provider_permanent")
    failure = ModelFailure(kind=kind, phase="transport", provider=provider, http_status=status,
        native_code=native, response_started=response_started, retry_after_seconds=retry_after,
        request_id=headers.get("x-request-id") or headers.get("request-id"))
    return SageV2Error(annotate_error(RuntimeErrorInfo(code=code, category=category,
        message=f"Model request failed ({kind.value}).",
        retryable=retryable or kind == K.CONTEXT, safe_to_resume=True,
        provider_code=str(status) if status is not None else native,
        metadata={"response_started": response_started}), failure))
