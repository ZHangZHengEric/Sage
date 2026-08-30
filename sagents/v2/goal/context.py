"""System context and continuation gate for goal-mode Runs."""

from __future__ import annotations

from xml.sax.saxutils import escape

from sagents.v2.agent.policy import (
    ContinuationAction,
    ContinuationContext,
    ContinuationDecision,
    ContinuationPolicy,
)
from sagents.v2.context.contracts import ContextSegment, ContextStability
from sagents.v2.contracts.commands import StartRun
from sagents.v2.i18n import normalize_language, tr

from .state import GoalStateService


class GoalContextProvider:
    def __init__(self, goals: GoalStateService) -> None:
        self.goals = goals

    async def segments(
        self, command: StartRun, *, run_id: str | None = None
    ) -> tuple[ContextSegment, ...]:
        if (
            command.invocation_mode != "goal"
            and command.config.metadata.get("goal_mode") is not True
        ):
            return ()
        language = normalize_language(
            str(command.config.metadata.get("response_language") or "en")
        )
        state = await self.goals.get(run_id) if run_id is not None else None
        if state is None:
            instructions = tr("goal.create_instruction", language)
            body = f"<goal_mode>\n{instructions}\n</goal_mode>"
        else:
            status = "completed" if state.completed else "active"
            instructions = tr("goal.verify_instruction", language)
            body = (
                "<active_goal>\n"
                f"<source>{state.source}</source>\n"
                f"<content>{escape(state.content)}</content>\n"
                f"<status>{status}</status>\n"
                f"{instructions}\n"
                "</active_goal>"
            )
        return (
            ContextSegment(
                segment_id="goal_mode",
                content=body,
                stability=ContextStability.SEMI_STABLE,
                priority=-164,
            ),
        )


class GoalCompletionGatePolicy:
    """Wrap any continuation policy with the same durable goal completion gate."""

    def __init__(self, base: ContinuationPolicy, goals: GoalStateService) -> None:
        self.base = base
        self.goals = goals

    async def decide(self, context: ContinuationContext) -> ContinuationDecision:
        if not await self.goals.is_goal_mode(context.run_id):
            return await self.base.decide(context)
        state = await self.goals.get(context.run_id)
        if state is not None and state.completed:
            if not context.response.text.strip():
                return ContinuationDecision(
                    action=ContinuationAction.CONTINUE_STEP,
                    reason_code="goal.explanation_required",
                    reason=tr("goal.explanation_required", context.language),
                )
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="goal.complete",
                reason=tr("goal.complete_reason", context.language),
            )

        decision = await self.base.decide(context)
        if decision.action in {
            ContinuationAction.FAIL,
            ContinuationAction.REQUEST_INTERACTION,
        }:
            return decision
        reason = tr(
            "goal.create_required" if state is None else "goal.incomplete",
            context.language,
        )
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_STEP,
            reason_code="goal.incomplete",
            reason=reason,
        )
