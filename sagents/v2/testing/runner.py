"""Deterministic scenario runner for AgentPackage and runtime acceptance tests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from sagents.v2.contracts.commands import ReplyInteraction, StartRun
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.items import MessageItemData, TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunSnapshot, RunState
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.testing.contracts import (
    ScenarioDefinition,
    ScenarioResult,
    ScenarioSuiteReport,
)


class ScenarioDriver(Protocol):
    async def execute(self, run_id: str, context: RequestContext) -> RunSnapshot: ...
    async def resume(self, run_id: str, context: RequestContext) -> RunSnapshot: ...


class ScenarioRunner:
    """Run scripted inputs and assert terminal state, events, tools, and artifacts.

    This harness is executable contract documentation. Model-quality evaluation
    is a separate opt-in layer and must not make deterministic CI flaky.
    """

    def __init__(self, runtime: RuntimePort) -> None:
        self.runtime = runtime

    async def run(
        self,
        scenario: ScenarioDefinition,
        driver: ScenarioDriver,
        context: RequestContext,
    ) -> ScenarioResult:
        """Drive one Run, apply scripted interactions, and evaluate assertions."""

        started = time.monotonic()
        events: tuple[RuntimeEvent, ...] = ()
        run_result = None
        failures: list[str] = []
        try:
            async with asyncio.timeout(scenario.timeout_seconds):
                handle = await self.runtime.start_run(
                    StartRun(
                        agent_id=scenario.agent_id,
                        input=scenario.input,
                        config=scenario.config,
                        resolved_spec_hash=scenario.resolved_spec_hash,
                        idempotency_key=f"scenario:{scenario.scenario_id}",
                    ),
                    context,
                )
                run = await driver.execute(handle.run_id, context)
                replies = iter(scenario.interactions)
                while run.state == RunState.SUSPENDED:
                    try:
                        scripted = next(replies)
                    except StopIteration:
                        failures.append(
                            "run suspended without a scripted interaction reply"
                        )
                        break
                    if run.suspension_id is None:
                        failures.append("suspended run has no suspension_id")
                        break
                    suspension = await self.runtime.session_store.get_suspension(
                        run.suspension_id
                    )
                    if suspension.interaction_id is None:
                        failures.append("suspension has no interaction_id")
                        break
                    interaction = await self.runtime.session_store.get_interaction(
                        suspension.interaction_id
                    )
                    receipt = await self.runtime.reply_interaction(
                        ReplyInteraction(
                            run_id=run.run_id,
                            expected_revision=run.revision,
                            suspension_id=suspension.suspension_id,
                            interaction_id=interaction.interaction_id,
                            expected_suspension_revision=suspension.expected_revision,
                            expected_interaction_revision=interaction.expected_revision,
                            decision=scripted.decision,
                            payload=scripted.payload,
                            idempotency_key=new_id("scenario_reply"),
                        ),
                        context,
                    )
                    if receipt.error is not None:
                        failures.append(
                            f"interaction reply rejected: {receipt.error.code}"
                        )
                        break
                    run = await driver.resume(run.run_id, context)
                events = await self.runtime.session_store.read_events(handle.run_id)
                if run.state in {
                    RunState.COMPLETED,
                    RunState.FAILED,
                    RunState.CANCELLED,
                }:
                    run_result = await self.runtime.get_run_result(handle.run_id)
                failures.extend(self._assertions(scenario, run, events, run_result))
        except TimeoutError:
            failures.append(f"scenario exceeded {scenario.timeout_seconds}s timeout")
        except Exception as exc:
            failures.append(f"unhandled {type(exc).__name__}: {exc}")
        return ScenarioResult(
            scenario_id=scenario.scenario_id,
            passed=not failures,
            failures=tuple(failures),
            run_result=run_result,
            events=events,
            duration_seconds=max(0, time.monotonic() - started),
        )

    async def run_suite(
        self,
        scenarios: tuple[ScenarioDefinition, ...],
        driver_factory: Callable[
            [ScenarioDefinition], Awaitable[ScenarioDriver] | ScenarioDriver
        ],
        context: RequestContext,
        *,
        max_concurrency: int = 4,
    ) -> ScenarioSuiteReport:
        semaphore = asyncio.Semaphore(max_concurrency)

        async def one(scenario):
            async with semaphore:
                driver = driver_factory(scenario)
                if hasattr(driver, "__await__"):
                    driver = await driver
                return await self.run(scenario, driver, context)

        results = tuple(await asyncio.gather(*(one(value) for value in scenarios)))
        passed = sum(value.passed for value in results)
        return ScenarioSuiteReport(
            passed=passed == len(results),
            passed_count=passed,
            failed_count=len(results) - passed,
            results=results,
        )

    @staticmethod
    def _assertions(scenario, run, events, run_result):
        expected = scenario.expectation
        failures = []
        types = [event.type for event in events]
        if run.state != expected.outcome:
            failures.append(
                f"expected outcome {expected.outcome.value}, got {run.state.value}"
            )
        for event_type in expected.required_event_types:
            if event_type not in types:
                failures.append(f"required event {event_type!r} was not emitted")
        for event_type in expected.forbidden_event_types:
            if event_type in types:
                failures.append(f"forbidden event {event_type!r} was emitted")
        tool_events = [event for event in events if event.type == "tool.call.proposed"]
        tool_names = {event.data.tool_name for event in tool_events}
        for name in expected.required_tool_names:
            if name not in tool_names:
                failures.append(f"required tool {name!r} was not called")
        if (
            expected.max_tool_calls is not None
            and len(tool_events) > expected.max_tool_calls
        ):
            failures.append(
                f"tool calls {len(tool_events)} exceed limit {expected.max_tool_calls}"
            )
        steps = sum(event.type == "step.started" for event in events)
        if expected.max_steps is not None and steps > expected.max_steps:
            failures.append(f"steps {steps} exceed limit {expected.max_steps}")
        final_text = "\n".join(
            block.text
            for item in (() if run_result is None else run_result.final_items)
            if isinstance(item.data, MessageItemData) and item.data.role == "assistant"
            for block in item.data.content
            if isinstance(block, TextBlock)
        )
        for required in expected.final_text_contains:
            if required not in final_text:
                failures.append(f"final assistant text does not contain {required!r}")
        return failures
