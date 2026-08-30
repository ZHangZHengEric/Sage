"""SAgents V2 module for contracts/errors.py."""

from __future__ import annotations

from enum import Enum
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


class ConflictError(SageV2Error):
    pass


class NotFoundError(SageV2Error):
    pass
