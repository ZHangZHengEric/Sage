"""Provider-wire helpers shared by the built-in model adapters.

This module deliberately contains no SDK-specific imports.  Keeping the small
normalization helpers here makes each adapter independently testable and lets a
host inject either an official SDK client or a protocol-compatible test client.
"""

from __future__ import annotations

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


def wire_value(value: Any, name: str, default: Any = None) -> Any:
    """Read one field from an SDK object or a decoded JSON mapping."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def compact_json(value: Any) -> str:
    """Serialize provider arguments deterministically without ASCII escaping."""

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def parse_tool_arguments(
    raw: str | None,
    *,
    tool_call_id: str | None,
    name: str | None,
) -> ModelToolCall:
    """Decode one provider tool call into the strict v2 contract."""

    try:
        arguments = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="model.tool_arguments_invalid_json",
                category=ErrorCategory.PROVIDER_PERMANENT,
                message=f"model returned invalid tool arguments: {exc}",
                safe_to_resume=True,
            )
        ) from exc
    if not isinstance(arguments, dict):
        raise SageV2Error(
            RuntimeErrorInfo(
                code="model.tool_arguments_not_object",
                category=ErrorCategory.PROVIDER_PERMANENT,
                message="model tool arguments must decode to an object",
                safe_to_resume=True,
            )
        )
    if not name:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="model.tool_name_missing",
                category=ErrorCategory.PROVIDER_PERMANENT,
                message="model returned a tool call without a name",
                safe_to_resume=True,
            )
        )
    return ModelToolCall(
        tool_call_id=tool_call_id or new_id("tool_call"),
        name=name,
        arguments=arguments,
    )


def provider_error(exc: Exception) -> SageV2Error:
    """Classify common HTTP/SDK failures without exposing credential material."""

    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    retryable = status in {408, 409, 425, 429} or (
        isinstance(status, int) and status >= 500
    )
    return SageV2Error(
        RuntimeErrorInfo(
            code="model.provider_transient"
            if retryable
            else "model.provider_permanent",
            category=(
                ErrorCategory.PROVIDER_TRANSIENT
                if retryable
                else ErrorCategory.PROVIDER_PERMANENT
            ),
            message=str(exc),
            retryable=retryable,
            safe_to_resume=True,
            provider_code=str(status) if status is not None else None,
        )
    )
