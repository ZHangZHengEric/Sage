
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.agent.policy.output_self_check import OutputChecker

import asyncio
from unittest.mock import AsyncMock

import pytest

from sagents.v2.agent.policy.output_self_check import (
    OutputCheck,
    OutputSelfCheck,
    OutputSelfCheckPolicy,
)
from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationDecision,
)


@pytest.mark.asyncio
async def test_independent_checks_run_concurrently_and_errors_keep_registration_order():
    events = [asyncio.Event(), asyncio.Event()]

    class Check:
        def __init__(self, index):
            self.index = index

        async def check(self, context):
            events[self.index].set()
            await events[1 - self.index].wait()
            return OutputCheck(
                errors=[f"failure-{self.index}"], repair_instruction=f"fix-{self.index}"
            )

    # Would deadlock if checks were awaited one at a time. No model dependency.
    result = await asyncio.wait_for(
        OutputSelfCheck([Check(0), Check(1)]).check(None), 1
    )
    assert cast('OutputCheck', result).errors == ["failure-0", "failure-1"]
    assert cast('OutputCheck', result).repair_instruction == "fix-0\nfix-1"


@pytest.mark.asyncio
async def test_inapplicable_checks_do_not_create_a_report():
    checker = AsyncMock()
    checker.check.return_value = None
    assert await OutputSelfCheck([checker]).check(None) is None


@pytest.mark.asyncio
async def test_infrastructure_failure_cancels_other_checks():
    started, cancelled = asyncio.Event(), asyncio.Event()

    class Waiting:
        async def check(self, context):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    class Broken:
        async def check(self, context):
            await started.wait()
            raise RuntimeError("compiler unavailable")

    with pytest.raises(ExceptionGroup):
        await OutputSelfCheck([Waiting(), Broken()]).check(None)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_hard_runtime_decision_does_not_run_output_checks():
    from types import SimpleNamespace

    delegate, checker = AsyncMock(), AsyncMock()
    delegate.decide.return_value = ContinuationDecision(
        action=ContinuationAction.FAIL,
        reason_code="budget.max_tokens",
        reason="budget",
    )
    result = await OutputSelfCheckPolicy(delegate, cast('OutputChecker', [checker])).decide(
        SimpleNamespace(response=SimpleNamespace(tool_calls=()))
    )
    assert result == delegate.decide.return_value
    checker.check.assert_not_called()


def test_repair_feedback_budget_preserves_detailed_diagnostics():
    from sagents.v2.agent.engine import AgentLoopEngine

    detail = "x" * 300 + " offending dependency: field_b"
    assert "field_b" not in cast('str', AgentLoopEngine._normalized_continuation_reason(detail))
    assert "field_b" in cast('str', AgentLoopEngine._normalized_continuation_reason(
        detail, limit=6000
    ))
    assert (
        len(cast(str, AgentLoopEngine._normalized_continuation_reason("x" * 7000, limit=6000)))
        == 6000
    )
