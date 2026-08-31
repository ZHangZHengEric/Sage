"""SAgents V2 module for tool/contracts.py."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel, ToolName
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.items import ContentBlock


class SideEffectLevel(str, Enum):
    NONE = "none"
    READ = "read"
    WRITE = "write"
    REVERSIBLE = "reversible"
    IRREVERSIBLE = "irreversible"


class IdempotencyStrategy(str, Enum):
    NATIVE_KEY = "native_key"
    FINGERPRINT = "fingerprint"
    RECONCILE_ONLY = "reconcile_only"
    NONE = "none"


class CancelSemantics(str, Enum):
    NOT_STARTED_ONLY = "not_started_only"
    COOPERATIVE = "cooperative"
    FORCEABLE = "forceable"
    NOT_SUPPORTED = "not_supported"


class ResumeStrategy(str, Enum):
    REPLAY_RESULT = "replay_result"
    RECONCILE = "reconcile"
    RETRY = "retry"
    RESTART_STEP = "restart_step"
    MANUAL_RESOLUTION = "manual_resolution"


class ReconcileState(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PENDING = "pending"
    UNKNOWN = "unknown"


class ToolCancellationState(str, Enum):
    CANCELLED = "cancelled"
    TOO_LATE = "too_late"
    UNKNOWN = "unknown"
    NOT_SUPPORTED = "not_supported"


class ToolDefinition(StrictModel):
    name: ToolName
    description: str
    input_schema: dict[str, Any]
    # Model-visible compatibility fields.  ``None`` means that the provider
    # must omit the field; this matters when adapting existing Sage tools whose
    # OpenAI schema explicitly contains ``strict: false`` and ``returns``.
    strict: bool | None = None
    output_schema: dict[str, Any] | None = None
    side_effect_level: SideEffectLevel = SideEffectLevel.NONE
    idempotency_strategy: IdempotencyStrategy = IdempotencyStrategy.FINGERPRINT
    cancel_semantics: CancelSemantics = CancelSemantics.NOT_STARTED_ONLY
    resume_strategy: ResumeStrategy = ResumeStrategy.REPLAY_RESULT
    supports_reconciliation: bool = False
    requires_approval: bool = False
    required_scopes: tuple[Identifier, ...] = ()


class ToolCall(StrictModel):
    tool_call_id: Identifier
    tool_name: ToolName
    arguments: dict[str, Any]
    operation_id: Identifier
    idempotency_key: Identifier
    owner_run_id: Identifier
    owner_agent_id: Identifier | None = None
    owner_session_id: Identifier | None = None


class ToolExecutionResult(StrictModel):
    tool_call_id: Identifier
    operation_id: Identifier
    content: tuple[ContentBlock, ...] = ()
    error: RuntimeErrorInfo | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReconcileResult(StrictModel):
    operation_id: Identifier
    state: ReconcileState
    result: ToolExecutionResult | None = None
    error: RuntimeErrorInfo | None = None


class ToolCancellationResult(StrictModel):
    operation_id: Identifier
    state: ToolCancellationState
    message: str | None = None
