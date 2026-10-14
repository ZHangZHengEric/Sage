"""Deterministic output verification and bounded repair, independent of format.

Self-check validators never invoke a model. The existing continuation policy still
owns task completion; concrete validation errors go to the original generation
loop, not to a separate review model.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol

from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationDecision,
)


@dataclass
class OutputCheck:
    errors: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    generations: int = 1
    current_output: bool = True
    repair_instruction: str = "Return one complete corrected replacement."


class OutputChecker(Protocol):
    async def check(self, context) -> OutputCheck | None: ...


class OutputSelfCheck:
    """Run independent, model-free validators concurrently in registration order."""

    def __init__(self, checkers):
        self.checkers = tuple(checkers)

    async def check(self, context):
        # TaskGroup cancels siblings on infrastructure failure or caller cancellation.
        # Normal validation failures are returned as reports, never exceptions.
        async with asyncio.TaskGroup() as group:
            tasks = [
                group.create_task(checker.check(context)) for checker in self.checkers
            ]
        reports = [task.result() for task in tasks if task.result() is not None]
        if not reports:
            return None
        return OutputCheck(
            errors=[error for report in reports for error in report.errors],
            evidence={
                str(index): report.evidence for index, report in enumerate(reports)
            },
            generations=max(report.generations for report in reports),
            current_output=any(report.current_output for report in reports),
            repair_instruction="\n".join(
                dict.fromkeys(
                    report.repair_instruction for report in reports if report.errors
                )
            ),
        )


class OutputSelfCheckPolicy:
    """Common completion gate using only rule/parser/compiler validators."""

    def __init__(
        self,
        delegate,
        checker: OutputChecker,
        *,
        reason_prefix="output.self_check",
        marker="output.self_check",
    ):
        self.delegate = delegate
        self.checker = OutputSelfCheck(
            checker if isinstance(checker, (tuple, list)) else (checker,)
        )
        self.reason_prefix = reason_prefix
        self.marker = marker

    async def decide(self, context):
        decision = await self.delegate.decide(context)
        if context.response.tool_calls or (
            decision.action
            not in {
                ContinuationAction.COMPLETE_RUN,
                ContinuationAction.COMPLETE_TURN,
                ContinuationAction.CONTINUE_STEP,
            }
            and decision.reason_code != "judge.plain_text_no_progress"
        ):
            return decision
        check = await self.checker.check(context)
        if check is None:
            return decision
        if check.errors:
            exhausted = (
                check.generations >= 3 or context.step_number >= context.max_steps
            )
            return ContinuationDecision(
                action=ContinuationAction.FAIL
                if exhausted
                else ContinuationAction.CONTINUE_STEP,
                reason_code=f"{self.reason_prefix}_failed"
                if exhausted
                else f"{self.reason_prefix}_retry",
                reason=f"[{self.marker}] Output self-check failed. "
                + "\n".join(check.errors)[:4500]
                + (
                    " Repair budget exhausted."
                    if exhausted
                    else "\n" + check.repair_instruction
                ),
                usage=decision.usage,
                metadata={
                    "output_self_check": {"passed": False, "issues": check.errors}
                },
            )
        if (
            decision.reason_code == "judge.plain_text_no_progress"
            and check.current_output
        ):
            # This branch is a heuristic rejection before the existing completion
            # judge is run. A validated revision is concrete progress.
            return await self.delegate.decide(
                context.model_copy(update={"validated_output_progress": True})
            )
        return decision
