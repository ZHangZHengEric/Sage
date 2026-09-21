from __future__ import annotations

import pytest

from sagents.v2.agent.step_request import DefaultAgentStepRequestBuilder
from sagents.v2.context import ContextBudget, DefaultContextAssembler
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import ImageBlock, TextBlock
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

        async def observe_projection(self, run_id, projection, **kwargs):
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
    assert (
        prepared.request.metadata["request_budget"]["estimated_input_tokens"]
        <= budget.max_input_tokens
    )
    assert prepared.request.metadata["request_budget"]["tool_schema_tokens"] > 0
    assert (
        prepared.request.metadata["request_budget"]["continuation_guidance_tokens"] > 0
    )
    assert prepared.request.metadata["request_budget"]["protocol_overhead_tokens"] == 32
    assert prepared.request.messages[-1].metadata["runtime_continuation_guidance"]
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
                ModelMessage(role="user", content=(TextBlock(text="current request"),)),
            ),
            pending_continuation_reason=None,
            language="en",
        )

    assert getattr(error.value, "info", None).code == "context.invalid_budget"


@pytest.mark.asyncio
async def test_multimodal_data_uri_fits_by_image_tokens_not_base64_bytes():
    budget = ContextBudget(
        max_input_tokens=128_000,
        reserve_output_tokens=8_196,
    )
    assembler = DefaultContextAssembler(budget=budget)
    builder = DefaultAgentStepRequestBuilder(
        context_assembler=assembler,
        tool_catalog=InMemoryToolCatalog(()),
        tool_selection_policy=DirectToolSelectionPolicy(),
        token_estimator=assembler.estimator,
        context_budget=budget,
    )
    image_uri = "data:image/png;base64," + ("A" * 2_000_000)

    prepared = await builder.prepare(
        command=_command(None),
        run_id="run_multimodal",
        turn_id="turn_multimodal",
        step_id="step_multimodal",
        messages=(
            ModelMessage(
                role="user",
                content=(
                    TextBlock(text="What is in this image?"),
                    ImageBlock(uri=image_uri, mime_type="image/png"),
                ),
            ),
        ),
        pending_continuation_reason=None,
        language="en",
    )

    estimated = prepared.request.metadata["request_budget"]["estimated_input_tokens"]
    assert 4_096 <= estimated < 10_000
    assert prepared.request.messages[0].content[1].uri == image_uri


async def _calibrated_prepare(
    builder, messages, *, run_id="calibration_run", command=None
):
    return (
        await builder.prepare(
            command=command or _command(None),
            run_id=run_id,
            turn_id="turn_calibration",
            step_id="step_calibration",
            messages=messages,
            pending_continuation_reason=None,
            language="en",
        )
    ).request


def _calibration_builder(assembler=None):
    return DefaultAgentStepRequestBuilder(
        context_assembler=assembler or PassthroughContextAssembler(),
        tool_catalog=InMemoryToolCatalog(()),
        tool_selection_policy=DirectToolSelectionPolicy(),
    )


def _reported_response(tokens=1000, *, reported=True, cached=0):
    from sagents.v2.model.contracts import ModelResponse
    from sagents.v2.contracts.items import UsageSummary

    return ModelResponse(
        response_id="response_calibration",
        finish_reason="stop",
        usage=UsageSummary(
            reported=reported,
            input_tokens=tokens,
            cached_input_tokens=cached,
            output_tokens=900,
        ),
    )


@pytest.mark.asyncio
async def test_usage_calibration_reuses_total_input_not_output_or_cache_twice():
    builder = _calibration_builder()
    messages = (ModelMessage(role="user", content=(TextBlock(text="x" * 20000),)),)
    first = await _calibrated_prepare(builder, messages)
    builder.observe_response(first, _reported_response(cached=800))
    added = (ModelMessage(role="assistant", content=(TextBlock(text="answer"),)),)
    second = await _calibrated_prepare(builder, (*messages, *added))
    budget = second.metadata["request_budget"]
    assert budget[
        "estimated_input_tokens"
    ] == 1000 + 128 + builder.token_estimator.estimate(added)
    assert budget["accounting_method"] == "reported_prefix_plus_estimated_delta"
    assert budget["estimated_new_message_count"] == 1
    # The next successful response replaces the anchor; margins never accumulate.
    builder.observe_response(second, _reported_response(1100))
    third = await _calibrated_prepare(builder, second.messages)
    assert third.metadata["request_budget"]["estimated_input_tokens"] == 1228


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["edited", "removed", "image", "tools", "model", "run", "missing_usage"]
)
async def test_usage_calibration_invalidates_changed_request_identity(change):
    builder = _calibration_builder()
    messages = (
        ModelMessage(
            role="user",
            content=(
                TextBlock(text="x" * 1000),
                ImageBlock(uri="data:image/png;base64,AAAA", mime_type="image/png"),
            ),
        ),
    )
    first = await _calibrated_prepare(builder, messages)
    builder.observe_response(
        first, _reported_response(reported=change != "missing_usage")
    )
    command = _command(None)
    run_id = "calibration_run"
    if change == "edited":
        messages = (ModelMessage(role="user", content=(TextBlock(text="edited"),)),)
    elif change == "removed":
        messages = ()
    elif change == "image":
        messages = (
            messages[0].model_copy(
                update={
                    "content": (
                        messages[0].content[0],
                        ImageBlock(
                            uri="data:image/png;base64,BBBB", mime_type="image/png"
                        ),
                    )
                }
            ),
        )
    elif change == "tools":
        builder.tool_catalog = InMemoryToolCatalog((_tool("new_tool"),))
    elif change == "model":
        command = command.model_copy(
            update={
                "config": command.config.model_copy(
                    update={"model_bindings": {"primary": "different_model"}}
                )
            }
        )
    elif change == "run":
        run_id = "other_run"
    second = await _calibrated_prepare(
        builder, messages, command=command, run_id=run_id
    )
    assert second.metadata["request_budget"]["accounting_method"] == "estimated"


@pytest.mark.asyncio
async def test_usage_calibration_is_used_before_context_reduction():
    assembler = DefaultContextAssembler(budget=ContextBudget(max_input_tokens=20000))
    builder = _calibration_builder(assembler)
    messages = (ModelMessage(role="user", content=(TextBlock(text="x" * 20000),)),)
    first = await _calibrated_prepare(builder, messages)
    builder.observe_response(first, _reported_response())
    # Without calibration, this unchanged current turn cannot fit and raises.
    assembler.budget = ContextBudget(max_input_tokens=2000)
    builder.context_budget = assembler.budget
    second = await _calibrated_prepare(builder, messages)
    assert second.messages == first.messages
    assert second.metadata["request_budget"]["estimated_input_tokens"] == 1128
    # Reported underestimates must also influence reduction, not only final validation.
    builder.observe_response(second, _reported_response(3000))
    with pytest.raises(SageV2Error, match="budget"):
        await _calibrated_prepare(builder, messages)


@pytest.mark.asyncio
async def test_calibration_context_is_task_local_and_restored_after_errors():
    import asyncio
    from sagents.v2.context.calibration import (
        InputUsageBaseline,
        input_usage_scope,
        message_fingerprints,
    )
    from sagents.v2.context.token_estimator import estimate_tokens_async
    from sagents.v2.context.plugins.estimator_json import JsonHeuristicTokenEstimator

    estimator = JsonHeuristicTokenEstimator()
    messages = (ModelMessage(role="user", content=(TextBlock(text="same"),)),)
    barrier = asyncio.Event()

    async def estimate_with(tokens):
        baseline = InputUsageBaseline(
            "scope", "request", message_fingerprints(messages), tokens, 32
        )
        with input_usage_scope(baseline):
            await barrier.wait()
            return await estimate_tokens_async(estimator, messages)

    first = asyncio.create_task(estimate_with(1000))
    second = asyncio.create_task(estimate_with(2000))
    barrier.set()
    assert await asyncio.gather(first, second) == [1096, 2096]
    assert await estimate_tokens_async(estimator, messages) == estimator.estimate(
        messages
    )
    with pytest.raises(ValueError):
        with input_usage_scope(
            InputUsageBaseline(
                "scope", "request", message_fingerprints(messages), 1000, 32
            )
        ):
            raise ValueError("projection failed")
    assert await estimate_tokens_async(estimator, messages) == estimator.estimate(
        messages
    )
