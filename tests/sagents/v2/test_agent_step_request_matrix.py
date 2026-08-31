from __future__ import annotations

import pytest

from sagents.v2.agent.step_request import DefaultAgentStepRequestBuilder
from sagents.v2.context import ContextBudget, DefaultContextAssembler
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.tool import DirectToolSelectionPolicy, ToolDefinition
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog


class PassthroughContextAssembler:
    async def prepare_messages(
        self, command, messages, *, run_id=None, reservation=None
    ):
        return messages


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description=f"Use {name}",
        input_schema={"type": "object", "properties": {}},
    )


def _command(invocation_mode: str | None) -> StartRun:
    return StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
        config={
            "model_bindings": {"primary": "model.primary"},
            "max_output_tokens": 321,
        },
        resolved_spec_hash="sha256:spec",
        idempotency_key="start_1",
        invocation_mode=invocation_mode,
    )


@pytest.mark.asyncio
async def test_step_request_builder_owns_mode_projection_and_request_metadata():
    builder = DefaultAgentStepRequestBuilder(
        context_assembler=PassthroughContextAssembler(),
        tool_catalog=InMemoryToolCatalog(
            (_tool("read_value"), _tool("goal_submit"), _tool("goal_complete"))
        ),
        tool_selection_policy=DirectToolSelectionPolicy(),
    )
    messages = (ModelMessage(role="user", content=(TextBlock(text="work"),)),)

    prepared = await builder.prepare(
        command=_command("plan"),
        run_id="run_1",
        turn_id="turn_1",
        step_id="step_1",
        messages=messages,
        pending_continuation_reason="finish the next item",
        language="en",
    )

    assert {tool.name for tool in prepared.tools} == {"read_value", "goal_submit"}
    assert {tool.name for tool in prepared.request.tools} == {
        "read_value",
        "goal_submit",
    }
    assert prepared.request.model_binding == "model.primary"
    assert prepared.request.max_output_tokens == 321
    assert prepared.request.metadata["turn_id"] == "turn_1"
    assert prepared.request.metadata["tool_selection"]["catalog_count"] == 2
    assert prepared.request.messages[-1].metadata["runtime_continuation_guidance"]


@pytest.mark.asyncio
async def test_step_request_builder_hides_goal_tools_outside_goal_modes():
    builder = DefaultAgentStepRequestBuilder(
        context_assembler=PassthroughContextAssembler(),
        tool_catalog=InMemoryToolCatalog(
            (_tool("read_value"), _tool("goal_submit"), _tool("goal_complete"))
        ),
        tool_selection_policy=DirectToolSelectionPolicy(),
    )

    prepared = await builder.prepare(
        command=_command(None),
        run_id="run_1",
        turn_id="turn_1",
        step_id="step_1",
        messages=(),
        pending_continuation_reason=None,
        language="en",
    )

    assert tuple(tool.name for tool in prepared.tools) == ("read_value",)


@pytest.mark.asyncio
async def test_final_request_budget_reserves_tool_schema_and_runtime_suffix():
    class ProjectionObserver:
        projection = None

        async def observe_projection(self, run_id, projection):
            self.projection = projection

    observer = ProjectionObserver()
    budget = ContextBudget(max_input_tokens=420)
    assembler = DefaultContextAssembler(
        budget=budget,
        projection_observer=observer,
    )
    builder = DefaultAgentStepRequestBuilder(
        context_assembler=assembler,
        tool_catalog=InMemoryToolCatalog(
            (
                ToolDefinition(
                    name="lookup",
                    description="schema " * 60,
                    input_schema={
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                    },
                ),
            )
        ),
        tool_selection_policy=DirectToolSelectionPolicy(),
        token_estimator=assembler.estimator,
        context_budget=budget,
    )
    messages = (
        ModelMessage(role="user", content=(TextBlock(text="old " * 800),)),
        ModelMessage(role="assistant", content=(TextBlock(text="old answer"),)),
        ModelMessage(role="user", content=(TextBlock(text="current request"),)),
    )

    prepared = await builder.prepare(
        command=_command(None),
        run_id="run_budget",
        turn_id="turn_budget",
        step_id="step_budget",
        messages=messages,
        pending_continuation_reason="continue safely",
        language="en",
    )

    assert all(
        "old " not in block.text
        for message in prepared.request.messages
        for block in message.content
        if isinstance(block, TextBlock)
    )
    assert any(
        "current request" in block.text
        for message in prepared.request.messages
        for block in message.content
        if isinstance(block, TextBlock)
    )
    assert prepared.request.metadata["request_budget"][
        "estimated_input_tokens"
    ] <= budget.max_input_tokens
    assert prepared.request.metadata["request_budget"]["tool_schema_tokens"] > 0
    assert prepared.request.metadata["request_budget"][
        "continuation_guidance_tokens"
    ] > 0
    assert prepared.request.metadata["request_budget"][
        "protocol_overhead_tokens"
    ] == 32
    assert prepared.request.messages[-1].metadata[
        "runtime_continuation_guidance"
    ]
    assert observer.projection is not None
    assert all(
        not message.metadata.get("runtime_continuation_guidance")
        and not message.metadata.get("runtime_tool_index")
        and not message.metadata.get("request_budget_tools")
        for message in observer.projection.messages
    )
    assert all(
        not message.metadata.get("runtime_continuation_guidance")
        and not message.metadata.get("runtime_tool_index")
        and not message.metadata.get("request_budget_tools")
        for message in observer.projection.historical_messages
    )


@pytest.mark.asyncio
async def test_final_request_budget_fails_before_provider_when_tools_cannot_fit():
    budget = ContextBudget(max_input_tokens=120)
    assembler = DefaultContextAssembler(budget=budget)
    builder = DefaultAgentStepRequestBuilder(
        context_assembler=assembler,
        tool_catalog=InMemoryToolCatalog(
            (
                ToolDefinition(
                    name="oversized",
                    description="schema " * 500,
                    input_schema={"type": "object"},
                ),
            )
        ),
        tool_selection_policy=DirectToolSelectionPolicy(),
        token_estimator=assembler.estimator,
        context_budget=budget,
    )

    with pytest.raises(SageV2Error) as error:
        await builder.prepare(
            command=_command(None),
            run_id="run_oversized",
            turn_id="turn_oversized",
            step_id="step_oversized",
            messages=(
                ModelMessage(
                    role="user", content=(TextBlock(text="current request"),)
                ),
            ),
            pending_continuation_reason=None,
            language="en",
        )

    assert getattr(error.value, "info", None).code == "context.invalid_budget"
