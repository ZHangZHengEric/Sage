from __future__ import annotations

import pytest

from sagents.v2.agent.step_request import DefaultAgentStepRequestBuilder
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model.contracts import ModelMessage
from sagents.v2.tool import DirectToolSelectionPolicy, ToolDefinition
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog


class PassthroughContextAssembler:
    async def prepare_messages(self, command, messages, *, run_id=None):
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
