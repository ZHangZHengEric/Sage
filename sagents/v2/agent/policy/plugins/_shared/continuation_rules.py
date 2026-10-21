"""Shared deterministic rules for continuation plugins."""
from __future__ import annotations

from sagents.v2.agent.policy.continuation import (
    ContinuationAction, ContinuationContext, ContinuationDecision, InteractionDraft,
)
from sagents.v2.i18n import recovery_payload, tr


_OUTPUT_LIMIT_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})


class BudgetRule:
    async def evaluate(self, context: ContinuationContext):
        if context.step_number >= context.max_steps and (
            context.response.tool_calls
            or context.response.finish_reason in _OUTPUT_LIMIT_REASONS
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


class ResponseLimitRule:
    """A provider output limit is not evidence that the user task is complete."""

    async def evaluate(self, context: ContinuationContext):
        if context.response.finish_reason not in _OUTPUT_LIMIT_REASONS:
            return None
        if (
            context.requested_interaction is not None
            or context.pending_tool_calls
            or context.response.tool_calls
        ):
            return None
        return ContinuationDecision(
            action=ContinuationAction.CONTINUE_STEP,
            reason_code="response.output_limit",
            reason=(
                "The previous response reached the model output limit. Continue "
                "from where it stopped without repeating earlier text. Finish "
                "the remaining answer or work; do not treat the partial response "
                "as a completed task."
            ),
        )


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


class InspectionProgressRule:
    async def evaluate(self, context: ContinuationContext):
        if not context.response.tool_calls or context.no_progress_steps < 6:
            return None
        reason = (
            "Recent Tool calls repeated inspections without obtaining new evidence or advancing the task. "
            "Use the results already collected. Identify the next unfinished deliverable and implement it, "
            "or finish the answer if enough evidence exists. Read again only for a specific unresolved question; "
            "do not repeat completed operations."
        )
        if context.no_progress_steps < 12:
            return ContinuationDecision(action=ContinuationAction.CONTINUE_STEP,
                reason_code="loop.inspection_correction", reason=reason)
        return ContinuationDecision(
            action=ContinuationAction.REQUEST_INTERACTION,
            reason_code="loop.no_progress", reason=reason,
            interaction=InteractionDraft(interaction_type="loop_recovery", allowed_decisions=("submit", "cancel"),
                payload=recovery_payload("recovery.loop_tools", context.language,
                    reason_code="loop.no_progress", message_params={"count": context.no_progress_steps})),
        )


class LoopCorrectionRule:
    async def evaluate(self, context: ContinuationContext):
        if context.response.tool_calls and 3 <= context.repeated_fingerprint_count < 6:
            return ContinuationDecision(action=ContinuationAction.CONTINUE_STEP,
                reason_code="loop.pattern_correction",
                reason="A repeated Tool cycle was detected. Reuse the existing results and choose a different action that advances the unfinished task. Do not repeat completed operations.")
        return None


class LoopRecoveryRule:
    def __init__(self, threshold: int = 3) -> None:
        if threshold < 2:
            raise ValueError("loop recovery threshold must be at least 2")
        self.threshold = threshold

    async def evaluate(self, context: ContinuationContext):
        if context.repeated_fingerprint_count >= self.threshold:
            tool_names = [call.name for call in context.response.tool_calls]
            payload = recovery_payload(
                "recovery.loop_tools" if tool_names else "recovery.loop_text",
                context.language,
                reason_code="loop.repeated_pattern",
                message_params={
                    "count": context.repeated_fingerprint_count,
                },
            )
            payload.update(
                repeat_count=context.repeated_fingerprint_count,
                repeated_tool_names=tool_names,
            )
            return ContinuationDecision(
                action=ContinuationAction.REQUEST_INTERACTION,
                reason_code="loop.repeated_pattern",
                reason=payload["prompt"],
                interaction=InteractionDraft(
                    interaction_type="loop_recovery",
                    allowed_decisions=("submit", "cancel"),
                    payload=payload,
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
