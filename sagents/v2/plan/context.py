"""Completion gate for Plan-mode Runs."""

from __future__ import annotations

from sagents.v2.agent.policy import (
    ContinuationAction,
    ContinuationContext,
    ContinuationDecision,
    ContinuationPolicy,
)
from sagents.v2.context.contracts import ContextSegment, ContextStability
from sagents.v2.contracts.commands import StartRun
from sagents.v2.i18n import normalize_language, tr
from xml.sax.saxutils import escape

from sagents.v2.goal import GoalStateService


class PlanContextProvider:
    def __init__(self, goals: GoalStateService) -> None:
        self.goals = goals

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        if command.invocation_mode != "plan" or run_id is None:
            return ()
        state = await self.goals.get(run_id)
        if state is None:
            return ()
        language = normalize_language(
            str(command.config.metadata.get("response_language") or "en")
        )
        instruction = tr("plan.submitted_instruction", language)
        return (
            ContextSegment(
                segment_id="submitted_plan",
                content=(
                    "<submitted_plan>\n"
                    f"<content>{escape(state.content)}</content>\n"
                    "<status>approved</status>\n"
                    f"{instruction}\n"
                    "</submitted_plan>"
                ),
                stability=ContextStability.SEMI_STABLE,
                priority=-163,
            ),
        )


class PlanCompletionGatePolicy:
    """A Plan Run succeeds only after the user-approved Plan Tool succeeds."""

    def __init__(self, base: ContinuationPolicy, goals: GoalStateService) -> None:
        self.base = base
        self.goals = goals

    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        if not await self.goals.is_plan_mode(context.run_id):
            return await self.base.decide(context)
        state = await self.goals.get(context.run_id)
        if state is not None:
            if not context.response.text.strip():
                return ContinuationDecision(
                    action=ContinuationAction.CONTINUE_STEP,
                    reason_code="plan.explanation_required",
                    reason=tr("plan.explanation_required", context.language),
                )
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="plan.submitted",
                reason=tr("plan.submitted_reason", context.language),
            )

        decision = await self.base.decide(context)
        if decision.action in {
            ContinuationAction.FAIL,
            ContinuationAction.REQUEST_INTERACTION,
        }:
            return decision
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_STEP,
            reason_code="plan.required",
            reason=tr("plan.required", context.language),
        )
