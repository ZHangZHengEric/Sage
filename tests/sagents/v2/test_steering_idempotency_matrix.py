from __future__ import annotations

import asyncio

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.model import (
    ModelCapabilities,
    ModelEventKind,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.contracts.commands import (
    CommandDecision,
    InputItem,
    PauseRun,
    RunConfig,
    StartRun,
    SteerInboxStatus,
    SteerRun,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.testing.runtime import ephemeral_runtime


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


def start(*, key="start_1", text="initial"):
    return StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text=text),)),),
        config=RunConfig(max_steps=4),
        resolved_spec_hash="sha256:spec",
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_start_idempotency_replays_identical_request_but_rejects_key_reuse():
    runtime = ephemeral_runtime()
    first = await runtime.start_run(start(), CONTEXT)
    replay = await runtime.start_run(start(), CONTEXT)
    assert replay.run_id == first.run_id
    with pytest.raises(Exception) as conflict:
        await runtime.start_run(start(text="different"), CONTEXT)
    assert conflict.value.info.code == "idempotency.conflict"


@pytest.mark.asyncio
async def test_command_idempotency_replays_identical_request_but_rejects_key_reuse():
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(start(), CONTEXT)
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="execute",
    )
    command = PauseRun(
        run_id=handle.run_id,
        expected_revision=running.revision,
        idempotency_key="pause",
        reason="first",
    )
    accepted = await runtime.pause_run(command, CONTEXT)
    replay = await runtime.pause_run(command, CONTEXT)
    assert accepted.decision == CommandDecision.ACCEPTED
    assert replay.decision == CommandDecision.DUPLICATE
    changed = await runtime.pause_run(
        command.model_copy(update={"reason": "different"}), CONTEXT
    )
    assert changed.decision == CommandDecision.REJECTED
    assert changed.error.code == "idempotency.conflict"


@pytest.mark.asyncio
async def test_steer_inbox_orders_inputs_and_marks_them_applied_atomically():
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(start(), CONTEXT)
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="execute",
    )
    first = await runtime.steer_run(
        SteerRun(
            run_id=handle.run_id,
            expected_revision=running.revision,
            expected_turn_id="turn_1",
            input=(InputItem(role="user", content=(TextBlock(text="one"),)),),
            idempotency_key="steer_1",
        ),
        CONTEXT,
    )
    second = await runtime.steer_run(
        SteerRun(
            run_id=handle.run_id,
            expected_revision=first.current_revision,
            expected_turn_id="turn_1",
            input=(InputItem(role="user", content=(TextBlock(text="two"),)),),
            idempotency_key="steer_2",
        ),
        CONTEXT,
    )
    claimed = await runtime.session_store.claim_steers(
        run_id=handle.run_id,
        expected_revision=second.current_revision,
        turn_id="turn_1",
        context=CONTEXT,
    )
    assert [entry.input[0].content[0].text for entry in claimed.entries] == [
        "one",
        "two",
    ]
    assert [entry.inbox_sequence for entry in claimed.entries] == [1, 2]
    assert all(entry.status == SteerInboxStatus.APPLIED for entry in claimed.entries)
    assert [event.type for event in claimed.events] == [
        "steer.applied",
        "message.completed",
        "steer.applied",
        "message.completed",
    ]
    assert (
        await runtime.session_store.claim_steers(
            run_id=handle.run_id,
            expected_revision=claimed.run.revision,
            turn_id="turn_1",
            context=CONTEXT,
        )
    ).entries == ()


TOOL = ToolDefinition(
    name="lookup",
    description="lookup",
    input_schema={"type": "object", "additionalProperties": False},
    side_effect_level=SideEffectLevel.NONE,
)


async def lookup(call, context):
    return ToolExecutionResult(
        tool_call_id=call.tool_call_id,
        operation_id=call.operation_id,
        content=(TextBlock(text="ok"),),
    )


class BlockingTwoStepModel:
    def __init__(self):
        self.first_started = asyncio.Event()
        self.release_first = asyncio.Event()
        self.requests: list[ModelRequest] = []

    async def capabilities(self, model_binding):
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=False,
            supports_reasoning=False,
            supports_multimodal_input=False,
            supports_structured_output=False,
        )

    def stream(self, request):
        return self._stream(request)

    async def _stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            self.first_started.set()
            await self.release_first.wait()
            response = ModelResponse(
                response_id="response_1",
                tool_calls=(
                    ModelToolCall(tool_call_id="call_1", name="lookup", arguments={}),
                ),
                finish_reason="tool_calls",
            )
        else:
            response = ModelResponse(
                response_id="response_2", text="done", finish_reason="stop"
            )
        yield ModelStreamEvent(kind=ModelEventKind.COMPLETED, response=response)


@pytest.mark.asyncio
async def test_agent_loop_applies_steer_at_next_safe_model_boundary():
    runtime = ephemeral_runtime()
    handle = await runtime.start_run(start(), CONTEXT)
    model = BlockingTwoStepModel()
    loop = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((TOOL,)),
        tool_executor=InMemoryToolExecutor({"lookup": TOOL}, {"lookup": lookup}),
    )
    executing = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await model.first_started.wait()
    run = await runtime.get_run(handle.run_id)
    events = await runtime.session_store.read_events(handle.run_id)
    turn_id = next(event.turn_id for event in events if event.type == "turn.started")
    receipt = await runtime.steer_run(
        SteerRun(
            run_id=handle.run_id,
            expected_revision=run.revision,
            expected_turn_id=turn_id,
            input=(InputItem(role="user", content=(TextBlock(text="new direction"),)),),
            idempotency_key="steer_live",
        ),
        CONTEXT,
    )
    assert receipt.decision == CommandDecision.ACCEPTED
    model.release_first.set()
    completed = await executing
    assert completed.state == RunState.COMPLETED
    assert any(
        message.role == "user"
        and message.content
        and message.content[0].text == "new direction"
        for message in model.requests[1].messages
    )
    assert [
        entry.status for entry in await runtime.session_store.list_steers(handle.run_id)
    ] == [SteerInboxStatus.APPLIED]
