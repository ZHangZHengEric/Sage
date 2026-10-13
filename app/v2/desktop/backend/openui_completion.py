"""Desktop completion gate backed by the same parser used for publication."""

from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationDecision,
)
from sagents.v2.contracts.conversation import is_user_request
from .openui import openui_blocks


class OpenUiCompletionGate:
    def __init__(self, delegate, parser):
        self.delegate = delegate
        self.parser = parser

    async def decide(self, context):
        decision = await self.delegate.decide(context)
        if (
            decision.action
            not in {
                ContinuationAction.COMPLETE_RUN,
                ContinuationAction.COMPLETE_TURN,
                ContinuationAction.CONTINUE_STEP,
            }
            and decision.reason_code != "judge.plain_text_no_progress"
            or context.response.tool_calls
        ):
            return decision
        blocks = openui_blocks(context.response.text)
        if not blocks:
            # A later prose-only "done" must not bypass a failed UI from this turn.
            for message in reversed(context.ledger):
                if is_user_request(message):
                    break
                if message.role != "assistant":
                    continue
                text = "\n".join(
                    getattr(block, "text", "") for block in message.content
                )
                blocks = openui_blocks(text)
                if blocks:
                    break
        if not blocks:
            return decision
        errors = []
        for index, block in enumerate(blocks):
            try:
                if not block["closed"]:
                    raise ValueError("OpenUI fence was not closed")
                await self.parser.parse(
                    block["code"],
                    complete=True,
                    stream_id=f"completion:{context.run_id}:{context.step_number}:{index}",
                )
            except (ValueError, RuntimeError) as exc:
                errors.append(f"Block {index + 1}: {str(exc)[:1200]}")
        if not errors:
            if decision.reason_code == "judge.plain_text_no_progress" and openui_blocks(
                context.response.text
            ):
                # A validated replacement is progress without a tool call. Still
                # ask the normal judge to assess whether it fulfills the request.
                return await self.delegate.decide(
                    context.model_copy(update={"validated_output_progress": True})
                )
            return decision
        # Count UI-bearing responses from this user turn in the persisted ledger.
        # Runtime continuation guidance is inference-only and cannot be a counter.
        generations = 0
        for message in reversed(context.ledger):
            if is_user_request(message):
                break
            if message.role == "assistant" and any(
                openui_blocks(getattr(block, "text", "")) for block in message.content
            ):
                generations += 1
        exhausted = generations >= 3 or context.step_number >= context.max_steps
        return ContinuationDecision(
            action=ContinuationAction.FAIL
            if exhausted
            else ContinuationAction.CONTINUE_STEP,
            reason_code="openui.validation_failed"
            if exhausted
            else "openui.validation_retry",
            reason="[openui.validation] Generated UI failed the actual parser/renderer contract. "
            + "\n".join(errors)
            + (
                " Repair budget exhausted."
                if exhausted
                else "\nCorrect the reported constraints and output one complete replacement OpenUI block. "
                "Do not repeat earlier versions or use tools merely to render it."
            ),
            usage=decision.usage,
        )
