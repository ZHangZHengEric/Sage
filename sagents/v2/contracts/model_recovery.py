"""Serializable, provider-independent model recovery contracts."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from sagents.v2.contracts.common import StrictModel


class ModelTermination(str, Enum):
    COMPLETE = "complete"
    TOOL_CALLS = "tool_calls"
    TRUNCATED = "truncated"
    PAUSED = "paused"
    REFUSED = "refused"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class ModelFailureKind(str, Enum):
    TRANSPORT = "transport"
    OVERLOADED = "overloaded"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    ROUTE = "route"
    INVALID_REQUEST = "invalid_request"
    CONTEXT = "context"
    PAYLOAD = "payload"
    MEDIA = "media"
    OUTPUT_LIMIT = "output_limit"
    ARGUMENTS = "arguments"
    STRUCTURED_OUTPUT = "structured_output"
    EMPTY = "empty"
    REASONING_ONLY = "reasoning_only"
    STREAM = "stream"
    PROTOCOL = "protocol"
    UNSUPPORTED = "unsupported"
    STATE = "state"
    REFUSED = "refused"
    PAUSED = "paused"
    CAPACITY = "capacity"
    CANCELLED = "cancelled"
    BUDGET = "budget"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


class ModelFailure(StrictModel):
    version: Literal["model-failure/1"] = "model-failure/1"
    kind: ModelFailureKind
    phase: str = "response"
    provider: str | None = None
    http_status: int | None = None
    native_code: str | None = None
    native_finish_reason: str | None = None
    terminal_received: bool = False
    response_started: bool = False
    has_text: bool = False
    has_reasoning: bool = False
    has_tool_calls: bool = False
    retry_after_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    request_id: str | None = None
    response_id: str | None = None
    usage: dict[str, Any] | None = None
    side_effect_state: Literal["not_applied", "committed", "unknown"] = "not_applied"


class ModelRecoveryAction(str, Enum):
    RETRY_SAME_REQUEST = "retry_same_request"
    REPAIR_REQUEST = "repair_request"
    REGENERATE_WITH_GUIDANCE = "regenerate_with_guidance"
    CONTINUE_PROTOCOL = "continue_protocol"
    STOP_WITH_EXPLANATION = "stop_with_explanation"


class ModelRecoveryConfig(StrictModel):
    transient_retries: int = Field(default=2, ge=0)
    guidance_retries: int = Field(default=1, ge=0)
    argument_repairs: int = Field(default=2, ge=0)
    compatibility_repairs: int = Field(default=1, ge=0)
    context_repairs: int = Field(default=6, ge=0)
    protocol_continuations: int = Field(default=3, ge=0)
    episode_requests: int = Field(default=6, ge=0)
    episode_seconds: float = Field(default=120, ge=0, allow_inf_nan=False)
    run_requests: int = Field(default=24, ge=0)


class ModelRecoveryState(StrictModel):
    logical_call_id: str | None = None
    counts: dict[str, int] = Field(default_factory=dict)
    episode_requests: int = Field(default=0, ge=0)
    run_requests: int = Field(default=0, ge=0)
    first_failure_at: datetime | None = None
    deadline: datetime | None = None
    error_fingerprint: str | None = None
    first_failure: ModelFailure | None = None
    first_request_bytes: int | None = None
    pending_action: ModelRecoveryAction | None = None
    pending_kind: ModelFailureKind | None = None
    dispatch_started: bool = False
    guidance_version: str | None = None
    guidance_kind: ModelFailureKind | None = None
    retry_not_before: datetime | None = None

    def next_call(self) -> "ModelRecoveryState":
        return ModelRecoveryState(run_requests=self.run_requests)

    def first_failure_metadata(self) -> dict[str, Any]:
        if self.first_failure is None:
            return {}
        return {
            "first_model_failure": self.first_failure.model_dump(mode="json"),
            "first_request_bytes": self.first_request_bytes,
        }


class ModelRecoveryDecision(StrictModel):
    action: ModelRecoveryAction
    reason: str
    kind: ModelFailureKind
    delay_seconds: float = Field(default=0, ge=0)
    guidance: str | None = None
    counter: str | None = None
    limit: int = 0
