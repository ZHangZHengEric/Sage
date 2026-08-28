from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.agent.state import AgentLoopCheckpointState
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.tool.contracts import (
    ReconcileResult,
    ReconcileState,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)
from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationDecision,
    InteractionDraft,
)
from sagents.v2.contracts.commands import (
    CommandDecision,
    InputItem,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    RunConfig,
    StartRun,
)
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.events import ItemEventData
from sagents.v2.contracts.items import ItemStatus, TextBlock, UsageSummary
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.kernel import HarnessRuntime


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="user_1",
        principal_type=PrincipalType.USER,
        tenant_id="tenant_1",
        scopes=("filesystem:write",),
    )
)


READ_TOOL = ToolDefinition(
    name="read_value",
    description="read a value",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
        "additionalProperties": False,
    },
    side_effect_level=SideEffectLevel.READ,
)
WRITE_TOOL = ToolDefinition(
    name="write_value",
    description="write a value",
    input_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["key", "value"],
        "additionalProperties": False,
    },
    side_effect_level=SideEffectLevel.WRITE,
    required_scopes=("filesystem:write",),
)


def completed(text="done", *, calls=(), input_tokens=5, output_tokens=2):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="response_1",
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            usage=UsageSummary(input_tokens=input_tokens, output_tokens=output_tokens),
        ),
    )


def tool_call(name="read_value", arguments=None):
    return ModelToolCall(
        tool_call_id="call_1",
        name=name,
        arguments=arguments
        or ({"key": "answer"} if name == "read_value" else {"key": "a", "value": "1"}),
    )


async def tool_handler(call, context):
    value = call.arguments.get("value", "42")
    return ToolExecutionResult(
        tool_call_id=call.tool_call_id,
        operation_id=call.operation_id,
        content=(TextBlock(text=value),),
    )


class UncertainToolExecutor:
    def __init__(self, states):
        self.states = list(states)
        self.calls = []
        self.reconciliations = []

    async def execute(self, call, context):
        self.calls.append(call)
        raise SageV2Error(
            RuntimeErrorInfo(
                code="tool.response_lost",
                category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                message="the request may have committed before the response was lost",
                safe_to_resume=True,
            )
        )

    async def reconcile(self, operation_id, context):
        self.reconciliations.append(operation_id)
        state = self.states.pop(0) if self.states else ReconcileState.UNKNOWN
        call = self.calls[0]
        if state == ReconcileState.SUCCEEDED:
            return ReconcileResult(
                operation_id=operation_id,
                state=state,
                result=ToolExecutionResult(
                    tool_call_id=call.tool_call_id,
                    operation_id=operation_id,
                    content=(TextBlock(text="42"),),
                ),
            )
        if state == ReconcileState.FAILED:
            return ReconcileResult(
                operation_id=operation_id,
                state=state,
                error=RuntimeErrorInfo(
                    code="tool.remote_failed",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="remote system confirmed failure",
                    safe_to_resume=True,
                ),
            )
        return ReconcileResult(operation_id=operation_id, state=state)


async def setup_loop(
    model,
    *,
    tools=(READ_TOOL, WRITE_TOOL),
    handlers=None,
    max_steps=10,
    max_output_tokens=None,
    max_total_tokens=None,
    deadline_seconds=None,
    clock=None,
    actor_context=CONTEXT,
):
    runtime = HarnessRuntime()
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent_test",
            input=(InputItem(role="user", content=(TextBlock(text="do task"),)),),
            config=RunConfig(
                model_bindings={"primary": "test-model"},
                max_steps=max_steps,
                max_output_tokens=max_output_tokens,
                max_total_tokens=max_total_tokens,
                deadline_seconds=deadline_seconds,
            ),
            resolved_spec_hash="sha256:agent",
            idempotency_key="start_1",
        ),
        actor_context,
    )
    catalog = InMemoryToolCatalog(tuple(tools))
    executor = InMemoryToolExecutor(
        {tool.name: tool for tool in tools},
        handlers
        or {
            "read_value": tool_handler,
            "write_value": tool_handler,
        },
    )
    loop_kwargs = dict(
        runtime=runtime,
        model=model,
        tool_catalog=catalog,
        tool_executor=executor,
    )
    if clock is not None:
        loop_kwargs["clock"] = clock
    loop = AgentLoopEngine(**loop_kwargs)
    return runtime, handle, loop, executor


@pytest.mark.asyncio
async def test_text_reasoning_stream_completes_with_canonical_event_lifecycles():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.REASONING_DELTA, delta="think"
                    ),
                    ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="hel"),
                    ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="lo"),
                    completed("hello"),
                )
            ),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model)
    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    types = [event.type for event in events]

    assert result.state == RunState.COMPLETED
    assert types[:5] == [
        "run.accepted",
        "run.queued",
        "message.completed",
        "run.started",
        "turn.started",
    ]
    assert "reasoning.started" in types
    assert "reasoning.delta" in types
    assert types.count("message.delta") == 2
    assert "message.completed" in types
    assert "continuation.decided" in types
    assert types[-3:] == ["step.completed", "turn.completed", "run.completed"]
    assert [event.run_sequence for event in events] == list(range(1, len(events) + 1))


@pytest.mark.asyncio
async def test_run_config_output_and_deadline_budgets_are_enforced_by_loop():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("otherwise final"),)),)
    )
    runtime, handle, loop, _ = await setup_loop(
        model,
        max_output_tokens=321,
        deadline_seconds=1,
        clock=lambda: datetime.now(timezone.utc) + timedelta(hours=1),
    )

    run = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)

    assert model.requests[0].max_output_tokens == 321
    assert run.state == RunState.FAILED
    assert events[-1].data.error.code == "budget.deadline"


@pytest.mark.asyncio
async def test_model_call_to_unavailable_tool_becomes_typed_run_failure():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    completed(
                        "",
                        calls=(
                            ModelToolCall(
                                tool_call_id="call_missing",
                                name="not_enabled",
                                arguments={},
                            ),
                        ),
                    ),
                )
            ),
        )
    )
    runtime, handle, loop, executor = await setup_loop(model, tools=(READ_TOOL,))

    run = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)

    assert run.state == RunState.FAILED
    assert executor.calls == []
    assert events[-1].type == "run.failed"
    assert events[-1].data.error.code == "tool.not_found"


@pytest.mark.asyncio
async def test_allowed_read_tool_executes_then_result_is_in_next_model_request():
    call = tool_call()

    def assert_second_request(request):
        assert request.messages[-2].role == "assistant"
        assert request.messages[-2].tool_calls[0].tool_call_id == "call_1"
        assert request.messages[-1].role == "tool"
        assert request.messages[-1].tool_call_id == "call_1"
        assert request.messages[-1].content[0].text == "42"

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(call,)),)),
            ScriptedModelStep(
                events=(completed("the answer is 42"),),
                assertion=assert_second_request,
            ),
        )
    )
    runtime, handle, loop, executor = await setup_loop(model)
    result = await loop.execute(handle.run_id, CONTEXT)
    types = [
        event.type for event in await runtime.session_store.read_events(handle.run_id)
    ]

    assert result.state == RunState.COMPLETED
    assert len(executor.calls) == 1
    expected = [
        "tool.call.proposed",
        "policy.decision.recorded",
        "tool.call.dispatching",
        "tool.call.started",
        "tool.call.succeeded",
    ]
    positions = [types.index(value) for value in expected]
    assert positions == sorted(positions)
    assert len(model.requests) == 2


@pytest.mark.asyncio
async def test_write_tool_suspends_before_dispatch_and_approval_resumes_once():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(completed("", calls=(tool_call("write_value"),)),)
            ),
            ScriptedModelStep(events=(completed("written"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(model)
    suspended = await loop.execute(handle.run_id, CONTEXT)
    events_before = await runtime.session_store.read_events(handle.run_id)

    assert suspended.state == RunState.SUSPENDED
    assert suspended.suspension_id is not None
    assert suspended.checkpoint_id is not None
    assert executor.calls == []
    types_before = [event.type for event in events_before]
    assert "tool.call.awaiting_approval" in types_before
    assert "tool.call.dispatching" not in types_before
    assert types_before[-3:] == [
        "interaction.requested",
        "checkpoint.committed",
        "run.suspended",
    ]

    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    reply = await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve_once",
            idempotency_key="approve_1",
        ),
        CONTEXT,
    )
    assert reply.decision == CommandDecision.ACCEPTED
    completed_run = await loop.resume(handle.run_id, CONTEXT)

    assert completed_run.state == RunState.COMPLETED
    assert len(executor.calls) == 1
    types = [
        event.type for event in await runtime.session_store.read_events(handle.run_id)
    ]
    assert types.index("interaction.resolved") < types.index("run.resumed")
    assert types.index("run.resumed") < types.index("tool.call.dispatching")
    assert types.count("tool.call.succeeded") == 1


@pytest.mark.asyncio
async def test_declined_write_never_dispatches_and_model_receives_decline_result():
    def assert_decline(request):
        tool_result = request.messages[-1]
        assert tool_result.role == "tool"
        assert "declined" in tool_result.content[0].text

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(completed("", calls=(tool_call("write_value"),)),)
            ),
            ScriptedModelStep(
                events=(completed("not written"),), assertion=assert_decline
            ),
        )
    )
    runtime, handle, loop, executor = await setup_loop(model)
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=0,
            expected_interaction_revision=0,
            decision="deny",
            idempotency_key="deny_1",
        ),
        CONTEXT,
    )
    result = await loop.resume(handle.run_id, CONTEXT)
    types = [
        event.type for event in await runtime.session_store.read_events(handle.run_id)
    ]
    assert result.state == RunState.COMPLETED
    assert executor.calls == []
    assert "tool.call.cancelled" in types
    assert "tool.call.dispatching" not in types


@pytest.mark.asyncio
async def test_missing_actor_scope_denies_without_interaction_or_dispatch():
    restricted_context = RequestContext(
        actor=ActorRef(
            principal_id="user_2",
            principal_type=PrincipalType.USER,
            tenant_id="tenant_1",
        )
    )
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(completed("", calls=(tool_call("write_value"),)),)
            ),
            ScriptedModelStep(events=(completed("denied"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(
        model, actor_context=restricted_context
    )
    result = await loop.execute(handle.run_id, restricted_context)
    types = [
        event.type for event in await runtime.session_store.read_events(handle.run_id)
    ]
    assert result.state == RunState.COMPLETED
    assert executor.calls == []
    assert "interaction.requested" not in types
    assert "tool.call.cancelled" in types


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("step", "error_code"),
    [
        (
            ScriptedModelStep(
                events=(),
                error=RuntimeErrorInfo(
                    code="model.rate_limited",
                    category=ErrorCategory.RATE_LIMITED,
                    message="rate limited",
                    retryable=True,
                ),
            ),
            "model.rate_limited",
        ),
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="partial"),
                )
            ),
            "model.stream_incomplete",
        ),
    ],
)
async def test_model_failure_matrix_ends_run_with_typed_terminal_events(
    step, error_code
):
    runtime, handle, loop, _ = await setup_loop(ScriptedModelProvider((step,)))
    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    assert result.state == RunState.FAILED
    assert [event.type for event in events[-3:]] == [
        "step.failed",
        "turn.failed",
        "run.failed",
    ]
    assert events[-1].data.error.code == error_code


@pytest.mark.asyncio
async def test_step_budget_fails_instead_of_infinite_tool_loop():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),)
    )
    runtime, handle, loop, executor = await setup_loop(model, max_steps=1)
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.FAILED
    assert len(executor.calls) == 1
    assert (await runtime.session_store.read_events(handle.run_id))[
        -1
    ].data.error.code == "budget.max_steps"


class BlockingModel:
    def __init__(self):
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
        self.requests = []

    async def capabilities(self, model_binding):
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=False,
            supports_parallel_tool_calls=False,
            supports_reasoning=False,
            supports_multimodal_input=False,
            supports_structured_output=False,
        )

    async def _stream(self, request):
        self.requests.append(request)
        yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="partial")
        self.blocked.set()
        await self.release.wait()
        yield completed("partial final")

    def stream(self, request):
        return self._stream(request)


@pytest.mark.asyncio
async def test_pause_during_model_stream_commits_partial_as_suspended_not_final():
    model = BlockingModel()
    runtime, handle, loop, _ = await setup_loop(model, tools=(), handlers={})
    executing = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await model.blocked.wait()
    current = await runtime.get_run(handle.run_id)
    pause = await runtime.pause_run(
        PauseRun(
            run_id=handle.run_id,
            expected_revision=current.revision,
            idempotency_key="pause_1",
        ),
        CONTEXT,
    )
    assert pause.decision == CommandDecision.ACCEPTED
    model.release.set()
    suspended = await executing
    assert suspended.state == RunState.SUSPENDED
    events = await runtime.session_store.read_events(handle.run_id)
    completed_items = [
        event.data.item
        for event in events
        if event.type == "item.completed"
        and isinstance(event.data, ItemEventData)
        and event.data.item is not None
    ]
    assert len(completed_items) == 1
    assert completed_items[0].status == ItemStatus.SUSPENDED
    assert not any(
        event.type == "message.completed"
        and event.data.item is not None
        and event.data.item.data.kind == "message"
        and event.data.item.data.role == "assistant"
        for event in events
    )
    checkpoint = await runtime.session_store.get_latest_checkpoint(handle.run_id)
    state = AgentLoopCheckpointState.model_validate(checkpoint.state)
    assert state.retry_model_step is True


@pytest.mark.asyncio
async def test_manual_pause_at_safe_point_can_resume_same_run():
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("done"),)),))
    runtime, handle, loop, _ = await setup_loop(model)
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="start-execution",
    )
    await runtime.pause_run(
        PauseRun(
            run_id=handle.run_id,
            expected_revision=running.revision,
            idempotency_key="pause",
        ),
        CONTEXT,
    )
    # execute() refuses suspend_requested ownership; executor safe-point handling
    # is exercised by the streaming test above. Here create the durable pause via
    # a tiny checkpoint by using the engine's safe point helper.
    state = AgentLoopCheckpointState(
        turn_id="turn_1",
        step_number=1,
        messages=await loop.context_assembler.initial_ledger(
            await runtime.session_store.get_start_command(handle.run_id),
            run_id=handle.run_id,
        ),
    )
    suspended = await loop._suspend_at_safe_point(
        await runtime.get_run(handle.run_id), state, CONTEXT
    )
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    receipt = await runtime.resume_run(
        ResumeRun(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            idempotency_key="resume",
        ),
        CONTEXT,
    )
    assert receipt.decision == CommandDecision.ACCEPTED
    result = await loop.resume(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED


@pytest.mark.asyncio
async def test_user_input_resume_rebuilds_ledger_from_events_not_checkpoint_messages():
    class AskThenComplete:
        def __init__(self):
            self.calls = 0

        async def decide(self, context):
            self.calls += 1
            if self.calls == 1:
                return ContinuationDecision(
                    action=ContinuationAction.REQUEST_INTERACTION,
                    reason_code="test.direction",
                    reason="ask for direction",
                    interaction=InteractionDraft(
                        interaction_type="direction",
                        allowed_decisions=("change_direction", "cancel"),
                    ),
                )
            return ContinuationDecision(
                action=ContinuationAction.COMPLETE_RUN,
                reason_code="test.done",
                reason="done",
            )

    runtime = HarnessRuntime()
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("first answer"),)),
            ScriptedModelStep(events=(completed("revised answer"),)),
        )
    )
    loop = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
        continuation_policy=AskThenComplete(),
    )
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent_test",
            input=(InputItem(role="user", content=(TextBlock(text="do task"),)),),
            resolved_spec_hash="sha256:agent",
            idempotency_key="user-input-start",
        ),
        CONTEXT,
    )
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    checkpoint = await runtime.session_store.get_checkpoint(suspension.checkpoint_id)
    assert checkpoint.checkpoint_codec_version == "agent-loop/2"
    assert "messages" not in checkpoint.state

    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="change_direction",
            payload={"text": "take the safer route"},
            idempotency_key="direction",
        ),
        CONTEXT,
    )
    completed_run = await loop.resume(handle.run_id, CONTEXT)

    assert completed_run.state == RunState.COMPLETED
    request = model.requests[1]
    assert [message.role for message in request.messages] == [
        "user",
        "assistant",
        "user",
    ]
    assert request.messages[-1].content == (TextBlock(text="take the safer route"),)
    events = await runtime.session_store.read_events(handle.run_id)
    assert any(
        event.type == "message.completed"
        and event.interaction_id == interaction.interaction_id
        for event in events
    )


@pytest.mark.asyncio
async def test_resume_rejects_checkpoint_ledger_digest_that_disagrees_with_events():
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("done"),)),))
    runtime, handle, loop, _ = await setup_loop(model)
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="digest-start",
    )
    await runtime.pause_run(
        PauseRun(
            run_id=handle.run_id,
            expected_revision=running.revision,
            idempotency_key="digest-pause",
        ),
        CONTEXT,
    )
    command = await runtime.session_store.get_start_command(handle.run_id)
    state = AgentLoopCheckpointState(
        turn_id="turn_1",
        step_number=1,
        messages=await loop.context_assembler.initial_ledger(
            command, run_id=handle.run_id
        ),
    )
    suspended = await loop._suspend_at_safe_point(
        await runtime.get_run(handle.run_id), state, CONTEXT
    )
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    await runtime.resume_run(
        ResumeRun(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            idempotency_key="digest-resume",
        ),
        CONTEXT,
    )
    payload = await runtime.session_store.export_state()
    payload["checkpoints"][0]["state"]["ledger_digest"] = "sha256:tampered"
    restored_runtime = HarnessRuntime()
    await restored_runtime.session_store.load_state(payload)
    restored_loop = AgentLoopEngine(
        runtime=restored_runtime,
        model=ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("should not run"),)),)
        ),
        tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
    )

    with pytest.raises(SageV2Error) as mismatch:
        await restored_loop.resume(handle.run_id, CONTEXT)
    assert mismatch.value.info.code == "loop.checkpoint_ledger_mismatch"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "confirmed_state", [ReconcileState.SUCCEEDED, ReconcileState.FAILED]
)
async def test_uncertain_tool_is_reconciled_without_duplicate_dispatch(confirmed_state):
    definition = READ_TOOL.model_copy(update={"supports_reconciliation": True})
    executor = UncertainToolExecutor((confirmed_state,))
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),
            ScriptedModelStep(events=(completed("handled"),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model, tools=(definition,))
    loop.tool_executor = executor

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    types = [event.type for event in events]

    assert result.state == RunState.COMPLETED
    assert len(executor.calls) == 1
    assert len(executor.reconciliations) == 1
    assert types.index("tool.call.unknown") < types.index("tool.call.reconciling")
    assert types.index("tool.call.reconciling") < types.index("tool.call.reconciled")
    assert "tool.call.failed" not in types


@pytest.mark.asyncio
async def test_pending_reconciliation_suspends_and_resume_reconciles_without_retry():
    definition = READ_TOOL.model_copy(update={"supports_reconciliation": True})
    executor = UncertainToolExecutor((ReconcileState.PENDING, ReconcileState.SUCCEEDED))
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),
            ScriptedModelStep(events=(completed("42"),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model, tools=(definition,))
    loop.tool_executor = executor

    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    checkpoint = await runtime.session_store.get_checkpoint(suspension.checkpoint_id)
    state = AgentLoopCheckpointState.model_validate(checkpoint.state)

    assert suspended.state == RunState.SUSPENDED
    assert state.pending_tool_phase == "reconciliation"
    assert interaction.allowed_decisions == (
        "reconcile",
        "confirm_succeeded",
        "mark_failed",
        "cancel",
    )
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="reconcile",
            idempotency_key="reconcile_1",
        ),
        CONTEXT,
    )
    result = await loop.resume(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert len(executor.calls) == 1
    assert len(executor.reconciliations) == 2


@pytest.mark.asyncio
async def test_non_reconcilable_unknown_requires_explicit_manual_resolution():
    executor = UncertainToolExecutor(())

    def assert_confirmed(request):
        assert request.messages[-1].role == "tool"
        assert request.messages[-1].content[0].text == "confirmed receipt 42"

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),
            ScriptedModelStep(events=(completed("42"),), assertion=assert_confirmed),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model, tools=(READ_TOOL,))
    loop.tool_executor = executor
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)

    assert "reconcile" not in interaction.allowed_decisions
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="confirm_succeeded",
            payload={"result_text": "confirmed receipt 42"},
            idempotency_key="confirm_1",
        ),
        CONTEXT,
    )
    result = await loop.resume(handle.run_id, CONTEXT)
    types = [
        event.type for event in await runtime.session_store.read_events(handle.run_id)
    ]

    assert result.state == RunState.COMPLETED
    assert len(executor.calls) == 1
    assert executor.reconciliations == []
    assert types.count("tool.call.reconciled") == 1
