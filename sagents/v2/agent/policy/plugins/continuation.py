"""Deterministic and explicit-status continuation plugins."""
from __future__ import annotations

from sagents.v2.agent.policy.continuation import (
    ContinuationContext,
    ContinuationDecision,
    ContinuationRule,
)
from sagents.v2.agent.policy.plugins._shared.continuation_rules import (
    BudgetRule, ExplicitStatusRequiredRule, ExplicitStatusRule, FlowBoundaryRule, InspectionProgressRule, LoopCorrectionRule, LoopRecoveryRule, ResponseLimitRule, ToolOrTextRule, ToolOrTextRuleForPendingCalls,
)


class CompositeContinuationPolicy:
    """Deterministic continuation plugin composed from ordered rules."""

    plugin_id = "sage.agent.continuation.deterministic"
    name = "Deterministic continuation policy"
    description = (
        "Applies ordered safety, budget, and completion rules without a model call."
    )

    def __init__(self, rules: tuple[ContinuationRule, ...] | None = None) -> None:
        self.rules = rules or (
            BudgetRule(),
            ResponseLimitRule(),
            ExplicitStatusRule(),
            InspectionProgressRule(),
            LoopCorrectionRule(),
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


class ExplicitStatusContinuationPolicy:
    """Require turn_status for completion while preserving safety boundaries."""

    plugin_id = "sage.agent.continuation.explicit-status"
    name = "Explicit turn_status completion policy"
    description = "Completes only when the model emits an explicit turn_status."

    def __init__(self, *, repeat_threshold: int = 3) -> None:
        self.rules = (
            BudgetRule(),
            ResponseLimitRule(),
            ExplicitStatusRule(),
            LoopRecoveryRule(repeat_threshold),
            FlowBoundaryRule(),
            ToolOrTextRuleForPendingCalls(),
            ExplicitStatusRequiredRule(),
        )

    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        for rule in self.rules:
            decision = await rule.evaluate(context)
            if decision is not None:
                return decision
        raise RuntimeError("continuation policy has no terminal fallback rule")
