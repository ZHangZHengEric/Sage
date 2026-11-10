"""Pure recovery decisions: ordinary execution failures never require a person."""

from collections.abc import Iterable

from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationDecision,
)
from sagents.v2.contracts.errors import ErrorCategory
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.errors import error_diagnostic_message
from sagents.v2.tool.contracts import ToolExecutionResult
from sagents.v2.contracts.events import RuntimeEvent, ToolEventData

RECOVERY_GUIDANCE = (
    "Handle this failure autonomously using the recorded error and available tools. "
    "Correct invalid inputs, inspect status or outputs, or choose a safe alternative. "
    "Reuse successful sibling results; do not repeat completed operations. "
    "Do not ask the user to diagnose a tool failure. Approval and genuinely missing "
    "credentials, resources or task information still require the appropriate user action."
)


def autonomous_continuation(decision: ContinuationDecision) -> ContinuationDecision:
    """Convert only framework recovery prompts, never approvals or task questions."""
    if (
        decision.action != ContinuationAction.REQUEST_INTERACTION
        or decision.interaction is None
        or decision.interaction.interaction_type
        not in {"agent_recovery", "loop_recovery"}
    ):
        return decision
    if decision.reason_code in {"status.failed", "status.invalid"}:
        return decision.model_copy(
            update={
                "action": ContinuationAction.CONTINUE_STEP,
                "reason_code": "agent.autonomous_repair",
                "interaction": None,
                "reason": RECOVERY_GUIDANCE
                + " Return a supported status after completing the necessary recovery.",
            }
        )
    # Loops already received bounded correction opportunities. Budget exhaustion
    # is not permission to reset limits, and is not a question for the user.
    reason = (
        "Configured execution limits were reached before task completion."
        if decision.reason_code in {"budget.max_steps", "status.missing_at_limit"}
        else "Automatic recovery stopped because repeated attempts did not make sufficient progress."
    )
    return decision.model_copy(
        update={
            "action": ContinuationAction.FAIL,
            "interaction": None,
            "reason": reason
            + " Completed results are preserved; this run did not complete.",
        }
    )


def unresolved_effects(
    events: Iterable[RuntimeEvent],
) -> list[tuple[ToolEventData | None, ToolEventData]]:
    """Reconstruct effect barriers from authoritative events, including replay."""
    proposals: dict[str, ToolEventData] = {}
    unresolved: dict[str, ToolEventData] = {}
    for event in events:
        data = event.data
        if not isinstance(data, ToolEventData) or not data.operation_id:
            continue
        if event.type == "tool.call.proposed":
            proposals.setdefault(data.operation_id, data)
        elif event.type == "tool.call.unknown":
            unresolved[data.operation_id] = data
        elif event.type == "tool.call.reconciled":
            if data.error is None or (
                data.error.category != ErrorCategory.UNCERTAIN_SIDE_EFFECT
                and data.error.metadata.get("side_effect_state") != "unknown"
            ):
                unresolved.pop(data.operation_id, None)
    return [
        (proposals.get(operation_id), data) for operation_id, data in unresolved.items()
    ]


def with_recovery_feedback(result: ToolExecutionResult) -> ToolExecutionResult:
    """Keep structured/partial output and append missing model-visible diagnostics."""
    if result.error is None:
        return result
    diagnostic = error_diagnostic_message(result.error)
    content = result.content
    if not any(
        isinstance(block, TextBlock) and diagnostic in block.text for block in content
    ):
        content = (*content, TextBlock(text=diagnostic))
    if not any(
        isinstance(block, TextBlock) and block.text == RECOVERY_GUIDANCE
        for block in content
    ):
        content = (*content, TextBlock(text=RECOVERY_GUIDANCE))
    return result.model_copy(update={"content": content})
