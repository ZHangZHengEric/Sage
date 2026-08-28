"""Deterministic policy deciding what follows a fully settled Agent Step."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Protocol

from pydantic import Field

from sagents.v2.model.contracts import ModelResponse
from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.errors import RuntimeErrorInfo


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
    pending_tool_calls: int = Field(default=0, ge=0)
    repeated_fingerprint_count: int = Field(default=0, ge=0)
    explicit_status: str | None = None
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

    def stable_hash(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


class ContinuationRule(Protocol):
    async def evaluate(
        self, context: ContinuationContext
    ) -> ContinuationDecision | None: ...


class ContinuationPolicy(Protocol):
    async def decide(self, context: ContinuationContext) -> ContinuationDecision: ...


class BudgetRule:
    async def evaluate(self, context: ContinuationContext):
        if context.step_number >= context.max_steps and (
            context.response.tool_calls
            or not context.response.text.strip()
            or (context.explicit_status or "").lower() in {"continue", "in_progress"}
        ):
            return ContinuationDecision(
                action=ContinuationAction.FAIL,
                reason_code="budget.max_steps",
                reason="maximum agent steps reached",
            )
        if (
            context.max_total_tokens is not None
            and context.total_tokens >= context.max_total_tokens
        ):
            return ContinuationDecision(
                action=ContinuationAction.FAIL,
                reason_code="budget.max_tokens",
                reason="maximum token budget reached",
            )
        if (
            context.deadline_seconds is not None
            and context.elapsed_seconds >= context.deadline_seconds
        ):
            return ContinuationDecision(
                action=ContinuationAction.FAIL,
                reason_code="budget.deadline",
                reason="run deadline reached",
            )
        return None


class ExplicitStatusRule:
    async def evaluate(self, context: ContinuationContext):
        status = (context.explicit_status or "").lower()
        if status in {"complete", "completed", "done"}:
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="status.complete",
                reason="model returned an explicit completed status",
            )
        if status in {"continue", "in_progress"}:
            return ContinuationDecision(
                action=ContinuationAction.CONTINUE_STEP,
                reason_code="status.continue",
                reason="model returned an explicit continue status",
            )
        if status in {"failed", "error"}:
            return ContinuationDecision(
                action=ContinuationAction.FAIL,
                reason_code="status.failed",
                reason="model returned an explicit failed status",
            )
        return None


class LoopRecoveryRule:
    def __init__(self, threshold: int = 3) -> None:
        if threshold < 2:
            raise ValueError("loop recovery threshold must be at least 2")
        self.threshold = threshold

    async def evaluate(self, context: ContinuationContext):
        if context.repeated_fingerprint_count >= self.threshold:
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="loop.repeated_pattern",
                reason="agent repeated the same action pattern",
                interaction=InteractionDraft(
                    interaction_type="loop_recovery",
                    allowed_decisions=("continue", "change_direction", "cancel"),
                    payload={"repeat_count": context.repeated_fingerprint_count},
                ),
            )
        return None


class FlowBoundaryRule:
    async def evaluate(self, context: ContinuationContext):
        if context.flow_boundary == "complete_node":
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_TURN,
                reason_code="flow.node_complete",
                reason="flow node owns the next transition",
            )
        if context.flow_boundary == "continue_node":
            return ContinuationDecision(
                action=ContinuationAction.CONTINUE_STEP,
                reason_code="flow.node_continue",
                reason="flow node requires another agent step",
            )
        return None


class ToolOrTextRule:
    async def evaluate(self, context: ContinuationContext):
        if context.pending_tool_calls or context.response.tool_calls:
            return ContinuationDecision(
                action=ContinuationAction.CONTINUE_STEP,
                reason_code="tool.pending",
                reason="tool calls must complete before the run can finish",
            )
        if context.response.text.strip():
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="text.final",
                reason="model returned final text without tool calls",
            )
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_STEP,
            reason_code="response.empty",
            reason="empty model response requires another step",
        )


class CompositeContinuationPolicy:
    """Evaluate ordered rules; earlier safety/budget rules have precedence.

    Rules return data only. They may not execute tools, mutate the Session, or
    commit events, which keeps replay and scenario tests deterministic.
    """

    def __init__(self, rules: tuple[ContinuationRule, ...] | None = None) -> None:
        self.rules = rules or (
            BudgetRule(),
            ExplicitStatusRule(),
            LoopRecoveryRule(),
            FlowBoundaryRule(),
            ToolOrTextRule(),
        )

    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        for rule in self.rules:
            decision = await rule.evaluate(context)
            if decision is not None:
                return decision
        raise RuntimeError("continuation policy has no terminal fallback rule")
