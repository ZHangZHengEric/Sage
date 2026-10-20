"""Continuation decisions, signals and policy interfaces."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Protocol

from pydantic import Field

from sagents.v2.model.contracts import ModelMessage, ModelResponse
from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.items import UsageSummary


class ContinuationAction(str, Enum):
    CONTINUE_STEP = "continue_step"
    COMPLETE_TURN = "complete_turn"
    COMPLETE_RUN = "complete_run"
    REQUEST_INTERACTION = "request_interaction"
    HANDOFF = "handoff"
    FAIL = "fail"


class InteractionDraft(StrictModel):
    interaction_type: Identifier
    allowed_decisions: tuple[str, ...]
    payload: dict = Field(default_factory=dict)


class ContinuationContext(StrictModel):
    run_id: Identifier
    step_number: int = Field(ge=1)
    max_steps: int = Field(gt=0)
    response: ModelResponse
    ledger: tuple[ModelMessage, ...] = ()
    language: str = "en"
    agent_system_requirements: str = ""
    available_tools: tuple[str, ...] = ()
    pending_tool_calls: int = Field(default=0, ge=0)
    repeated_fingerprint_count: int = Field(default=0, ge=0)
    no_progress_steps: int = Field(default=0, ge=0)
    # Host validators may certify a structured answer as actual output progress.
    # This only bypasses the plain-text loop heuristic, never runtime budgets.
    validated_output_progress: bool = False
    explicit_status: str | None = None
    explicit_status_note: str | None = None
    requested_interaction: InteractionDraft | None = None
    flow_boundary: str | None = None
    elapsed_seconds: float = Field(default=0, ge=0)
    deadline_seconds: float | None = Field(default=None, gt=0)
    total_tokens: int = Field(default=0, ge=0)
    max_total_tokens: int | None = Field(default=None, gt=0)


class ContinuationDecision(StrictModel):
    """Side-effect-free decision later recorded as `continuation.decided`."""

    action: ContinuationAction
    reason_code: Identifier
    reason: str
    next_agent: Identifier | None = None
    interaction: InteractionDraft | None = None
    error: RuntimeErrorInfo | None = None
    usage: UsageSummary = Field(default_factory=UsageSummary)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def stable_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ContinuationSignals(StrictModel):
    """Run-scoped control signals produced outside the policy itself."""

    explicit_status: str | None = None
    explicit_status_note: str | None = None
    interaction: InteractionDraft | None = None
    flow_boundary: str | None = None


ContinuationSignalProvider = Callable[
    [str], ContinuationSignals | Awaitable[ContinuationSignals]
]


class ContinuationRule(Protocol):
    async def evaluate(
        self, context: ContinuationContext
    ) -> ContinuationDecision | None: ...


class ContinuationPolicy(Protocol):
    async def decide(self, context: ContinuationContext) -> ContinuationDecision: ...
