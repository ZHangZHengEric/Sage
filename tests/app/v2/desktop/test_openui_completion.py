from unittest.mock import AsyncMock

import pytest

from app.v2.desktop.backend.openui import OpenUiParser
from app.v2.desktop.backend.openui_completion import OpenUiCompletionGate
from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationContext,
    ContinuationDecision,
)
from sagents.v2.model import ModelResponse, ModelMessage
from sagents.v2.contracts.items import TextBlock
from sagents.v2.agent.policy.judge import LLMJudgeContinuationPolicy


@pytest.mark.asyncio
async def test_actual_validation_overrides_completed_judge_and_bounds_repairs():
    parser = OpenUiParser()
    completed = ContinuationDecision(
        action=ContinuationAction.COMPLETE_RUN, reason_code="judge.done", reason="done"
    )
    delegate = AsyncMock()
    delegate.decide.return_value = completed
    gate = OpenUiCompletionGate(delegate, parser)
    bad = '```openui\nroot = Deck("Deck", [Slide("Cover", [Text("Hello"), Metric("A", "B")], "cover", "blue")])\n```'
    context = ContinuationContext(
        run_id="test",
        step_number=1,
        max_steps=10,
        response=ModelResponse(response_id="response", finish_reason="stop", text=bad),
    )
    try:
        result = await gate.decide(context)
        assert result.action == ContinuationAction.CONTINUE_STEP
        assert "too many blocks" in result.reason
        retries = tuple(
            ModelMessage(role="assistant", content=(TextBlock(text=bad),))
            for _ in range(3)
        )
        assert (
            await gate.decide(context.model_copy(update={"ledger": retries}))
        ).action == ContinuationAction.FAIL
        assert (
            await gate.decide(context.model_copy(update={"step_number": 10}))
        ).action == ContinuationAction.FAIL
        good = bad.replace(', Metric("A", "B")', "")
        assert (
            await gate.decide(
                context.model_copy(
                    update={
                        "response": ModelResponse(
                            response_id="response", finish_reason="stop", text=good
                        )
                    }
                )
            )
            == completed
        )
        assert (
            await gate.decide(
                context.model_copy(
                    update={
                        "response": ModelResponse(
                            response_id="response",
                            finish_reason="stop",
                            text="Plain answer",
                        )
                    }
                )
            )
            == completed
        )
        plain = context.model_copy(
            update={
                "response": ModelResponse(
                    response_id="plain", finish_reason="stop", text="Done"
                ),
                "ledger": (
                    ModelMessage(role="assistant", content=(TextBlock(text=bad),)),
                ),
            }
        )
        assert (await gate.decide(plain)).action == ContinuationAction.CONTINUE_STEP
        new_turn = plain.model_copy(
            update={
                "ledger": (
                    *plain.ledger,
                    ModelMessage(
                        role="user", content=(TextBlock(text="New question"),)
                    ),
                )
            }
        )
        assert await gate.decide(new_turn) == completed
        delegate.decide.return_value = completed.model_copy(
            update={"action": ContinuationAction.REQUEST_INTERACTION}
        )
        assert (
            await gate.decide(context)
        ).action == ContinuationAction.REQUEST_INTERACTION
    finally:
        await parser.close()


@pytest.mark.asyncio
async def test_native_output_repairs_are_progress_without_tools():
    parser = OpenUiParser()
    judge = AsyncMock()
    judge.decide.return_value = ContinuationDecision(
        action=ContinuationAction.COMPLETE_RUN,
        reason_code="judge.completed",
        reason="done",
    )
    policy = LLMJudgeContinuationPolicy(judge)
    gate = OpenUiCompletionGate(policy, parser)
    good = '```openui\nroot = Stack([Computed("Total", "sum", [1, 2])])\n```'
    bad = '```openui\nroot = Stack([Metric("Total", Computed("Sum", "sum", [1, 2]))])\n```'
    context = ContinuationContext(
        run_id="test",
        step_number=3,
        max_steps=10,
        response=ModelResponse(response_id="r", finish_reason="stop", text=good),
        ledger=tuple(
            ModelMessage(role="assistant", content=(TextBlock(text=text),))
            for text in [bad, bad, good]
        ),
    )
    try:
        assert (
            await policy.decide(context)
        ).reason_code == "judge.plain_text_no_progress"
        result = await gate.decide(context)
        assert result.action == ContinuationAction.COMPLETE_RUN
        assert judge.decide.call_args.args[0].validated_output_progress is True
        # The same three invalid generations terminate with a concrete parser error.
        invalid = context.model_copy(
            update={
                "response": context.response.model_copy(update={"text": bad}),
                "ledger": tuple(
                    ModelMessage(role="assistant", content=(TextBlock(text=bad),))
                    for _ in range(3)
                ),
            }
        )
        result = await gate.decide(invalid)
        assert result.reason_code == "openui.validation_failed"
        assert result.action == ContinuationAction.FAIL
        assert "Metric" in result.reason
        # Validation progress cannot override hard budgets.
        result = await gate.decide(
            context.model_copy(update={"max_total_tokens": 100, "total_tokens": 100})
        )
        assert result.reason_code == "budget.max_tokens"
    finally:
        await parser.close()


@pytest.mark.asyncio
async def test_judge_continue_gets_actual_validation_error():
    parser = OpenUiParser()
    delegate = AsyncMock()
    delegate.decide.return_value = ContinuationDecision(
        action=ContinuationAction.CONTINUE_STEP,
        reason_code="judge.continue",
        reason="please improve",
    )
    context = ContinuationContext(
        run_id="test",
        step_number=1,
        max_steps=10,
        response=ModelResponse(
            response_id="r",
            finish_reason="stop",
            text='```openui\nroot = Metric("A", Computed("B", "sum", [1]))\n```',
        ),
    )
    try:
        result = await OpenUiCompletionGate(delegate, parser).decide(context)
        assert result.reason_code == "openui.validation_retry"
        assert "expects string" in result.reason
    finally:
        await parser.close()
