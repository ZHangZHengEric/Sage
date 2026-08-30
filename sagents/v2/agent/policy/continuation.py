"""Deterministic policy deciding what follows a fully settled Agent Step."""

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
from sagents.v2.i18n import recovery_payload, tr


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


class BudgetRule:
    async def evaluate(self, context: ContinuationContext):
        if context.step_number >= context.max_steps and (
            context.response.tool_calls
            or not context.response.text.strip()
            or (context.explicit_status or "").lower()
            in {"continue_work", "continue", "in_progress"}
        ):
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="budget.max_steps",
                reason=tr("recovery.max_steps", context.language),
                interaction=InteractionDraft(
                    interaction_type="loop_recovery",
                    allowed_decisions=("submit", "cancel"),
                    payload={
                        **recovery_payload(
                            "recovery.max_steps",
                            context.language,
                            reason_code="budget.max_steps",
                        ),
                        "reset_step_budget": True,
                    },
                ),
            )
        if (
            context.max_total_tokens is not None
            and context.total_tokens >= context.max_total_tokens
        ):
            return ContinuationDecision(
                action=ContinuationAction.FAIL,
                reason_code="budget.max_tokens",
                reason=tr("error.budget.max_tokens", context.language),
            )
        if (
            context.deadline_seconds is not None
            and context.elapsed_seconds >= context.deadline_seconds
        ):
            return ContinuationDecision(
                action=ContinuationAction.FAIL,
                reason_code="budget.deadline",
                reason=tr("error.budget.deadline", context.language),
            )
        return None


class ExplicitStatusRule:
    async def evaluate(self, context: ContinuationContext):
        status = (context.explicit_status or "").strip().lower()
        if not status:
            return None
        if status in {
            "task_done",
            "complete",
            "completed",
            "done",
        }:
            if not context.response.text.strip():
                return ContinuationDecision(
                    action=ContinuationAction.CONTINUE_STEP,
                    reason_code="status.explanation_required",
                    reason=(
                        "terminal status requires user-facing text in the same "
                        "model response"
                    ),
                )
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="status.complete",
                reason="model returned an explicit completed status",
            )
        if status in {"continue_work", "continue", "in_progress"}:
            return ContinuationDecision(
                action=ContinuationAction.CONTINUE_STEP,
                reason_code="status.continue",
                reason="model returned an explicit continue status",
            )
        if status == "need_user_input":
            if not context.response.text.strip():
                return ContinuationDecision(
                    action=ContinuationAction.CONTINUE_STEP,
                    reason_code="status.explanation_required",
                    reason=(
                        "need_user_input requires a user-facing question in the "
                        "same model response"
                    ),
                )
            prompt = context.explicit_status_note or context.response.text.strip()
            interaction = context.requested_interaction or InteractionDraft(
                interaction_type="agent_input_required",
                allowed_decisions=("submit", "cancel"),
                payload={
                    **recovery_payload(
                        "recovery.input_prompt",
                        context.language,
                        reason_code="status.need_user_input",
                    ),
                    "status": status,
                    "prompt": prompt,
                },
            )
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="status.need_user_input",
                reason=prompt,
                interaction=interaction,
            )
        if status == "blocked":
            if not context.response.text.strip():
                return ContinuationDecision(
                    action=ContinuationAction.CONTINUE_STEP,
                    reason_code="status.explanation_required",
                    reason=(
                        "blocked status requires a user-facing explanation in the "
                        "same model response"
                    ),
                )
            prompt = context.explicit_status_note or context.response.text.strip()
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="status.blocked",
                reason=prompt,
                interaction=InteractionDraft(
                    interaction_type="agent_blocked",
                    allowed_decisions=("submit", "cancel"),
                    payload={
                        **recovery_payload(
                            "recovery.input_prompt",
                            context.language,
                            reason_code="status.blocked",
                        ),
                        "status": status,
                        "prompt": prompt,
                    },
                ),
            )
        if status in {"failed", "error"}:
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="status.failed",
                reason=tr("recovery.status_failed", context.language),
                interaction=InteractionDraft(
                    interaction_type="agent_recovery",
                    allowed_decisions=("submit", "cancel"),
                    payload=recovery_payload(
                        "recovery.status_failed",
                        context.language,
                        reason_code="status.failed",
                    ),
                ),
            )
        return ContinuationDecision(
            action=ContinuationAction.REQUEST_INTERACTION,
            reason_code="status.invalid",
            reason=tr("recovery.invalid_status", context.language, status=status),
            interaction=InteractionDraft(
                interaction_type="agent_recovery",
                allowed_decisions=("submit", "cancel"),
                payload=recovery_payload(
                    "recovery.invalid_status",
                    context.language,
                    reason_code="status.invalid",
                    status=status,
                ),
            ),
        )


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
                reason=tr("recovery.loop", context.language),
                interaction=InteractionDraft(
                    interaction_type="loop_recovery",
                    allowed_decisions=("submit", "cancel"),
                    payload={
                        **recovery_payload(
                            "recovery.loop",
                            context.language,
                            reason_code="loop.repeated_pattern",
                        ),
                        "repeat_count": context.repeated_fingerprint_count,
                    },
                ),
            )
        return None


class FlowBoundaryRule:
    async def evaluate(self, context: ContinuationContext):
        # A Flow boundary must never skip a proposed Tool call. It applies only
        # after the current model response has no remaining work to dispatch.
        if context.pending_tool_calls or context.response.tool_calls:
            return None
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
        if context.flow_boundary:
            return ContinuationDecision(
                action=ContinuationAction.FAIL,
                reason_code="flow.invalid_boundary",
                reason=f"unsupported Flow boundary: {context.flow_boundary}",
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


class ExplicitStatusRequiredRule:
    """Continue until the model emits a typed status, then ask for guidance."""

    async def evaluate(self, context: ContinuationContext):
        if context.step_number >= context.max_steps:
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="status.missing_at_limit",
                reason=tr("recovery.missing_status", context.language),
                interaction=InteractionDraft(
                    interaction_type="agent_recovery",
                    allowed_decisions=("submit", "cancel"),
                    payload={
                        **recovery_payload(
                            "recovery.missing_status",
                            context.language,
                            reason_code="status.missing_at_limit",
                        ),
                        "reset_step_budget": True,
                    },
                ),
            )
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_STEP,
            reason_code="status.required",
            reason="this policy requires an explicit turn_status value",
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


class ToolOrTextRuleForPendingCalls:
    """Handle Tool proposals without treating ordinary text as completion."""

    async def evaluate(self, context: ContinuationContext):
        if context.pending_tool_calls or context.response.tool_calls:
            return ContinuationDecision(
                action=ContinuationAction.CONTINUE_STEP,
                reason_code="tool.pending",
                reason="tool calls must complete before the run can finish",
            )
        return None


class ExplicitStatusContinuationPolicy(CompositeContinuationPolicy):
    """Require turn_status for completion while preserving safety boundaries."""

    def __init__(self, *, repeat_threshold: int = 3) -> None:
        super().__init__(
            rules=(
                BudgetRule(),
                ExplicitStatusRule(),
                LoopRecoveryRule(repeat_threshold),
                FlowBoundaryRule(),
                ToolOrTextRuleForPendingCalls(),
                ExplicitStatusRequiredRule(),
            )
        )
