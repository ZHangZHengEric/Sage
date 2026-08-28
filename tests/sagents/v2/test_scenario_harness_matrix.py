from __future__ import annotations

import asyncio

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.model import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ScriptedModelProvider,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.contracts.commands import InputItem, RunConfig
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.testing import (
    ScenarioDefinition,
    ScenarioExpectation,
    ScenarioInteractionReply,
    ScenarioRunner,
)


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user_1",
        principal_type=PrincipalType.USER,
        scopes=frozenset({"workspace.write"}),
    )
)


WRITE = ToolDefinition(
    name="file_write",
    description="write",
    input_schema={
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
        "additionalProperties": False,
    },
    side_effect_level=SideEffectLevel.WRITE,
    requires_approval=True,
    required_scopes=("workspace.write",),
)


def completed(text="", *, calls=()):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id=f"response_{text or 'tool'}",
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
        ),
    )


def scenario(scenario_id="scenario_1", **expected):
    expectation = {
        "required_event_types": (
            "interaction.requested",
            "interaction.resolved",
            "tool.call.succeeded",
        ),
        "required_tool_names": ("file_write",),
        "final_text_contains": ("finished",),
        "max_tool_calls": 1,
        "max_steps": 2,
    }
    expectation.update(expected)
    return ScenarioDefinition(
        scenario_id=scenario_id,
        agent_id="coder",
        input=(InputItem(role="user", content=(TextBlock(text="write a file"),)),),
        config=RunConfig(max_steps=4),
        resolved_spec_hash="sha256:spec",
        interactions=(ScenarioInteractionReply(decision="approve_once"),),
        expectation=ScenarioExpectation(**expectation),
    )


def driver(runtime, dispatches):
    async def write(call, context):
        dispatches.append(call)
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="written"),),
        )

    call = ModelToolCall(
        tool_call_id="call_write",
        name="file_write",
        arguments={"path": "a.txt"},
    )
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed(calls=(call,)),)),
            ScriptedModelStep(events=(completed("finished"),)),
        )
    )
    return AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((WRITE,)),
        tool_executor=InMemoryToolExecutor({WRITE.name: WRITE}, {WRITE.name: write}),
    )


@pytest.mark.asyncio
async def test_scenario_runner_drives_approval_resume_and_projects_run_result():
    runtime = HarnessRuntime()
    dispatches = []
    result = await ScenarioRunner(runtime).run(
        scenario(), driver(runtime, dispatches), CONTEXT
    )
    assert result.passed, result.failures
    assert len(dispatches) == 1
    assert result.run_result is not None
    assert result.run_result.final_cursor.run_sequence == result.events[-1].run_sequence
    assert result.run_result.outcome.value == "completed"


@pytest.mark.asyncio
async def test_scenario_runner_reports_semantic_assertion_failures_without_throwing():
    runtime = HarnessRuntime()
    result = await ScenarioRunner(runtime).run(
        scenario(
            "expected_failure",
            required_event_types=("artifact.finalized",),
            final_text_contains=("missing",),
            max_steps=1,
        ),
        driver(runtime, []),
        CONTEXT,
    )
    assert result.passed is False
    assert any("artifact.finalized" in failure for failure in result.failures)
    assert any("missing" in failure for failure in result.failures)
    assert any("steps" in failure for failure in result.failures)


@pytest.mark.asyncio
async def test_scenario_suite_has_bounded_parallel_execution_and_stable_counts():
    runtime = HarnessRuntime()
    active = 0
    peak = 0

    async def factory(value):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return driver(runtime, [])

    scenarios = tuple(scenario(f"scenario_{index}") for index in range(12))
    report = await ScenarioRunner(runtime).run_suite(
        scenarios, factory, CONTEXT, max_concurrency=3
    )
    assert report.passed is True
    assert report.passed_count == 12
    assert report.failed_count == 0
    assert peak <= 3


@pytest.mark.asyncio
async def test_scenario_without_approval_reply_stays_suspended_and_fails_cleanly():
    runtime = HarnessRuntime()
    value = scenario().model_copy(update={"interactions": ()})
    result = await ScenarioRunner(runtime).run(value, driver(runtime, []), CONTEXT)
    assert result.passed is False
    assert result.run_result is None
    assert result.failures == (
        "run suspended without a scripted interaction reply",
        "expected outcome completed, got suspended",
        "required event 'interaction.resolved' was not emitted",
        "required event 'tool.call.succeeded' was not emitted",
        "final assistant text does not contain 'finished'",
    )
