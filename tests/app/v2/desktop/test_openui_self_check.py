import json
from unittest.mock import AsyncMock

import pytest

from app.v2.desktop.backend.openui import OpenUiParser
from app.v2.desktop.backend.openui_checks import probe_tree, NumericEvaluation
from app.v2.desktop.backend.openui_completion import OpenUiOutputChecker
from sagents.v2.agent.policy.output_self_check import OutputSelfCheckPolicy
from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationContext,
    ContinuationDecision,
)
from sagents.v2.model import ModelResponse


def context(code):
    return ContinuationContext(
        run_id="check",
        step_number=1,
        max_steps=10,
        response=ModelResponse(
            response_id="answer", finish_reason="stop", text=f"```openui\n{code}\n```"
        ),
    )


@pytest.mark.asyncio
async def test_numeric_domain_failure_uses_only_local_checks():
    parser = OpenUiParser()
    delegate = AsyncMock()
    delegate.decide.return_value = ContinuationDecision(
        action=ContinuationAction.COMPLETE_RUN, reason_code="done", reason="done"
    )
    try:
        gate = OutputSelfCheckPolicy(delegate, OpenUiOutputChecker(parser))
        result = await gate.decide(
            context(
                'root = Stack([NumberInput("n", "N", 1, 0, 10, 1), Computed("Ratio", "divide", [100, "n"])])'
            )
        )
        assert "When n=0" in result.reason
        assert result.action == ContinuationAction.CONTINUE_STEP
        delegate.decide.assert_awaited_once()
        assert result.usage == delegate.decide.return_value.usage
    finally:
        await parser.close()


@pytest.mark.asyncio
async def test_probes_calculate_nested_bindings_and_checkbox_progress():
    parser = OpenUiParser()
    try:
        tree = await parser.parse(
            """root = Stack([checks, count, Progress("Progress", rate)])
checks = CheckboxGroup("done", "Done", ["A", "B"], [])
count = Computed("Count", "count", [checks])
rate = Computed("Rate", "ratioPercent", [count, 2])""",
            complete=True,
        )
        errors, evidence = probe_tree(tree)
        assert not errors
        assert all(value == 0 for value in evidence["defaults"].values())
        assert 100 in evidence["probes"][0]["results"].values()
    finally:
        await parser.close()


@pytest.mark.parametrize(
    "operation,args,expected",
    [
        ("sum", [1, 2], 3),
        ("product", [100, 25, 30], 75000),
        ("difference", [75000, 44000], 31000),
        ("divide", [1, 0], None),
        ("ratioPercent", [1, -2], None),
        ("ratioPercent", [1, 4], 25),
        ("percent", [200, 5], 10),
        ("compoundGrowth", [100, 10, 2], 121),
        ("compoundGrowth", [100, -101, 2], None),
        ("loanPayment", [1200, 0, 12], 100),
        ("product", [1e15, 2], None),
    ],
)
def test_native_arithmetic_contract(operation, args, expected):
    result = NumericEvaluation({}).compute(operation, args)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_shared_backend_flutter_numeric_fixtures():
    from pathlib import Path

    fixtures = (
        Path(__file__).resolve().parents[4]
        / "app/v2/desktop/test/fixtures/openui_numeric_contract.json"
    )
    for case in json.loads(fixtures.read_text()):
        result = NumericEvaluation(case["values"]).compute(
            case["operation"], case["inputs"]
        )
        if case["expected"] is None:
            assert result is None, case
        else:
            assert result == pytest.approx(case["expected"], abs=1e-8), case


@pytest.mark.asyncio
async def test_probe_work_is_bounded():
    parser = OpenUiParser()
    try:
        tree = await parser.parse(
            'root = Computed("Total", "sum", [1, 2])', complete=True
        )
        with pytest.raises(ValueError, match="work budget exceeded"):
            probe_tree(tree, max_work=1)
    finally:
        await parser.close()


@pytest.mark.asyncio
async def test_plain_text_skips_parser_and_probes():
    from app.v2.desktop.backend.openui_completion import OpenUiOutputChecker

    parser = AsyncMock()
    ctx = context("unused")
    ctx = ctx.model_copy(
        update={"response": ctx.response.model_copy(update={"text": "Plain answer"})}
    )
    assert await OpenUiOutputChecker(parser).check(ctx) is None
    parser.parse.assert_not_called()


@pytest.mark.asyncio
async def test_latest_body_only_excludes_historical_ui_reasoning_and_tool_results():
    from app.v2.desktop.backend.openui_completion import OpenUiOutputChecker
    from sagents.v2.contracts.items import TextBlock
    from sagents.v2.model import ModelMessage
    parser = AsyncMock()
    code = '```openui\nroot = BROKEN()\n```'
    ctx = context('unused')
    ctx = ctx.model_copy(update={
        "response": ctx.response.model_copy(update={"text": "Done", "reasoning": code}),
        "ledger": (
            ModelMessage(role="assistant", content=(TextBlock(text=code),)),
            ModelMessage(role="tool", tool_call_id="tool_result", content=(TextBlock(text=code),)),
        ),
    })
    assert await OpenUiOutputChecker(parser).check(ctx) is None
    parser.parse.assert_not_called()
