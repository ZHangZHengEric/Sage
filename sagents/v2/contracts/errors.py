"""SAgents V2 module for contracts/errors.py."""

from __future__ import annotations

from enum import Enum
from contextlib import contextmanager
from collections.abc import Iterator
from typing import Any

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel


class ErrorCategory(str, Enum):
    VALIDATION = "validation"
    CONFLICT = "conflict"
    POLICY_DENIED = "policy_denied"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    RATE_LIMITED = "rate_limited"
    PROVIDER_TRANSIENT = "provider_transient"
    PROVIDER_PERMANENT = "provider_permanent"
    RESOURCE_LOST = "resource_lost"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    CORRUPT_STATE = "corrupt_state"
    UNCERTAIN_SIDE_EFFECT = "uncertain_side_effect"
    CANCELLED = "cancelled"
    INTERNAL = "internal"


class RuntimeErrorInfo(StrictModel):
    code: Identifier
    category: ErrorCategory
    message: str
    retryable: bool = False
    safe_to_resume: bool = False
    details_ref: Identifier | None = None
    provider_code: str | None = None
    message_key: Identifier | None = None
    message_params: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SageV2Error(Exception):
    def __init__(self, info: RuntimeErrorInfo):
        super().__init__(info.message)
        self.info = info


def error_diagnostic_message(error: RuntimeErrorInfo) -> str:
    """Model-facing failure details, independent of the localized UI summary."""
    diagnostic = error.metadata.get("diagnostic_message")
    message = (
        diagnostic if isinstance(diagnostic, str) and diagnostic else error.message
    )
    return f"{error.code}: {message}" if message else error.code


def exception_diagnostic_message(error: Exception) -> str:
    """Keep the exception kind even when its text is just a path or is empty."""
    return f"{type(error).__name__}: {error}" if str(error) else type(error).__name__


@contextmanager
def errors_before_side_effect(code: str) -> Iterator[None]:
    """Mark only an explicitly side-effect-free preflight as not applied.

    Never wrap execution/materialization with this: a failure after mutation
    still needs reconciliation, even if it looks like a validation error.
    """
    try:
        yield
    except Exception as exc:
        info = (
            exc.info
            if isinstance(exc, SageV2Error)
            else RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=exception_diagnostic_message(exc),
            )
        )
        raise SageV2Error(
            info.model_copy(
                update={
                    "safe_to_resume": True,
                    "metadata": {**info.metadata, "side_effect_state": "not_applied"},
                }
            )
        ) from exc


class ConflictError(SageV2Error):
    pass


class NotFoundError(SageV2Error):
    pass
