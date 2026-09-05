from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.agent.observed import ObservedRunDriver
from sagents.v2.agent.stream_batcher import StreamEventBatcher
from sagents.v2.agent.state import AgentLoopCheckpointCodec, AgentLoopCheckpointState
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
    CancelSemantics,
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
from sagents.v2.tool.plugins.selection_lexical import LexicalToolSelectionPolicy
from sagents.v2.tool.plugins.selection_recent import RecentToolSelectionPolicy
from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationDecision,
    ContinuationSignals,
    InteractionDraft,
)
from sagents.v2.agent.policy.approval_memory import SessionApprovalMemory
from sagents.v2.agent.policy.tool_policy import (
    ApprovalStrategy,
    DefaultToolPolicy,
)
from sagents.v2.agent.policy.judge import (
    LLMContinuationJudge,
    LLMJudgeContinuationPolicy,
)
from sagents.v2.contracts.commands import (
    CommandDecision,
    CancelRun,
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
from sagents.v2.contracts.events import ItemEventData, ToolEventData
from sagents.v2.contracts.items import (
    ItemStatus,
    JsonBlock,
    TextBlock,
    ToolResultItemData,
    UsageSummary,
)
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.run_state import RunState
from sagents.v2.context import ContextBudget, DefaultContextAssembler
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.runtime.session.contracts import EventDraft


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
    flow_boundary=None,
    continuation_signal_provider=None,
    continuation_policy=None,
    tool_selection_policy=None,
    response_language=None,
    invocation_mode=None,
    automatic_memory_recall=False,
    memory_recall_query_generator=None,
    context_assembler=None,
    trace_sink=None,
    log_sink=None,
    tool_policy=None,
    approval_memory=None,
):
    runtime = ephemeral_runtime()
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
                flow_boundary=flow_boundary,
                metadata=(
                    {"response_language": response_language}
                    if response_language
                    else {}
                ),
            ),
            resolved_spec_hash="sha256:agent",
            idempotency_key="start_1",
            invocation_mode=invocation_mode,
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
    if continuation_signal_provider is not None:
        loop_kwargs["continuation_signal_provider"] = continuation_signal_provider
    if continuation_policy is not None:
        loop_kwargs["continuation_policy"] = continuation_policy
    if tool_selection_policy is not None:
        loop_kwargs["tool_selection_policy"] = tool_selection_policy
    if automatic_memory_recall:
        loop_kwargs["automatic_memory_recall"] = True
    if memory_recall_query_generator is not None:
        loop_kwargs["memory_recall_query_generator"] = memory_recall_query_generator
    if context_assembler is not None:
        loop_kwargs["context_assembler"] = context_assembler
    if tool_policy is not None:
        loop_kwargs["tool_policy"] = tool_policy
    if approval_memory is not None:
        # 传 callable 时用 runtime 现场构造（例如 SessionApprovalMemory(store)）。
        loop_kwargs["approval_memory"] = (
            approval_memory(runtime) if callable(approval_memory) else approval_memory
        )
    if trace_sink is not None or log_sink is not None:
        loop = ObservedRunDriver(
            **loop_kwargs,
            trace_sink=trace_sink,
            log_sink=log_sink,
        )
    else:
        loop = AgentLoopEngine(**loop_kwargs)
    return runtime, handle, loop, executor


@pytest.mark.asyncio
async def test_loop_rejects_run_from_a_different_resolved_spec():
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("done"),)),))
    runtime, handle, _, executor = await setup_loop(model)
    loop = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((READ_TOOL, WRITE_TOOL)),
        tool_executor=executor,
        expected_resolved_spec_hash="sha256:different",
    )

    with pytest.raises(SageV2Error) as incompatible:
        await loop.execute(handle.run_id, CONTEXT)

    assert incompatible.value.info.code == "loop.resolved_spec_incompatible"
    assert incompatible.value.info.safe_to_resume is False
    assert (await runtime.get_run(handle.run_id)).state == RunState.QUEUED


@pytest.mark.asyncio
async def test_worker_restart_recovers_started_tool_as_manual_resolution_barrier():
    dispatched = asyncio.Event()
    never_finish = asyncio.Event()

    async def interrupted_handler(call, context):
        del call, context
        dispatched.set()
        await never_finish.wait()

    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed(calls=(tool_call(),)),)),)
    )
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=(READ_TOOL,),
        handlers={"read_value": interrupted_handler},
    )
    execution = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(dispatched.wait(), timeout=1)
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    assert (await runtime.get_run(handle.run_id)).state == RunState.RUNNING

    unexpected_dispatches = 0

    async def must_not_replay(call, context):
        del call, context
        nonlocal unexpected_dispatches
        unexpected_dispatches += 1
        return ToolExecutionResult(
            tool_call_id="unexpected",
            operation_id="unexpected",
        )

    recovered_loop = AgentLoopEngine(
        runtime=runtime,
        model=ScriptedModelProvider(()),
        tool_catalog=InMemoryToolCatalog((READ_TOOL,)),
        tool_executor=InMemoryToolExecutor(
            {"read_value": READ_TOOL}, {"read_value": must_not_replay}
        ),
        expected_resolved_spec_hash="sha256:agent",
    )
    recovered = await recovered_loop.recover_interrupted(handle.run_id, CONTEXT)

    assert recovered is not None
    assert recovered.state == RunState.SUSPENDED
    assert unexpected_dispatches == 0
    suspension = await runtime.session_store.get_suspension(recovered.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["reason"] == "tool_outcome_unknown"
    assert interaction.payload["arguments"] == {"key": "answer"}
    assert interaction.payload["side_effect_level"] == "read"
    assert "reconcile" not in interaction.allowed_decisions


@pytest.mark.asyncio
async def test_worker_restart_suspends_when_started_tool_lost_its_proposal():
    runtime, handle, _, _ = await setup_loop(ScriptedModelProvider(()))
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=handle.run_revision,
        context=CONTEXT,
        idempotency_key="missing-proposal:start",
    )
    committed = await runtime.session_store.commit_run(
        run_id=running.run_id,
        expected_revision=running.revision,
        expected_states={RunState.RUNNING},
        new_state=RunState.RUNNING,
        drafts=(
            EventDraft(
                type="tool.call.started",
                turn_id="turn_1",
                step_id="step_1",
                data=ToolEventData(
                    tool_call_id="call_1",
                    tool_name="read_value",
                    state="started",
                    operation_id="operation_1",
                    idempotency_key="tool_1",
                ),
            ),
        ),
        context=CONTEXT,
        idempotency_key="missing-proposal:event",
    )
    assert committed.run.state == RunState.RUNNING
    recovered_loop = AgentLoopEngine(
        runtime=runtime,
        model=ScriptedModelProvider(()),
        tool_catalog=InMemoryToolCatalog((READ_TOOL,)),
        tool_executor=InMemoryToolExecutor({"read_value": READ_TOOL}, {}),
        expected_resolved_spec_hash="sha256:agent",
    )

    recovered = await recovered_loop.recover_interrupted(handle.run_id, CONTEXT)

    assert recovered is not None
    assert recovered.state == RunState.SUSPENDED
    suspension = await runtime.session_store.get_suspension(recovered.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["error_code"] == "tool.recovery_ledger_incomplete"
    assert interaction.allowed_decisions == (
        "confirm_succeeded",
        "mark_failed",
        "cancel",
    )


@pytest.mark.asyncio
async def test_worker_restart_reconciles_supported_tool_without_replaying_it():
    reconcilable = READ_TOOL.model_copy(update={"supports_reconciliation": True})
    dispatched = asyncio.Event()
    never_finish = asyncio.Event()

    async def interrupted_handler(call, context):
        del call, context
        dispatched.set()
        await never_finish.wait()

    runtime, handle, loop, _ = await setup_loop(
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed(calls=(tool_call(),)),)),)
        ),
        tools=(reconcilable,),
        handlers={"read_value": interrupted_handler},
    )
    execution = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(dispatched.wait(), timeout=1)
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution

    class RecoveryExecutor:
        def __init__(self):
            self.reconciled = []
            self.executed = 0

        async def execute(self, call, context):
            del call, context
            self.executed += 1
            raise AssertionError("recovery must not replay the tool")

        async def reconcile(self, operation_id, context):
            del context
            self.reconciled.append(operation_id)
            return ReconcileResult(
                operation_id=operation_id,
                state=ReconcileState.SUCCEEDED,
                result=ToolExecutionResult(
                    tool_call_id="call_1",
                    operation_id=operation_id,
                    content=(TextBlock(text="recovered result"),),
                ),
            )

    recovery_executor = RecoveryExecutor()
    recovered_loop = AgentLoopEngine(
        runtime=runtime,
        model=ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("done after recovery"),)),)
        ),
        tool_catalog=InMemoryToolCatalog((reconcilable,)),
        tool_executor=recovery_executor,
        expected_resolved_spec_hash="sha256:agent",
    )

    recovered = await recovered_loop.recover_interrupted(handle.run_id, CONTEXT)

    assert recovered is not None
    assert recovered.state == RunState.COMPLETED
    assert len(recovery_executor.reconciled) == 1
    assert recovery_executor.executed == 0


@pytest.mark.asyncio
async def test_tool_selection_preparation_runs_in_parallel_with_memory_recall():
    selection_started = asyncio.Event()
    recall_started = asyncio.Event()

    class CoordinatedSelection(RecentToolSelectionPolicy):
        async def prepare(self, context):
            selection_started.set()
            await asyncio.wait_for(recall_started.wait(), timeout=1)
            await super().prepare(context)

    class CoordinatedRecallQuery:
        async def generate(self, user_input, *, run_id):
            del user_input, run_id
            await asyncio.sleep(0)
            assert selection_started.is_set()
            recall_started.set()
            return "current task"

    memory_tool = ToolDefinition(
        name="search_memory",
        description="search memory",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
    )
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("done"),)),))
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=(READ_TOOL, memory_tool),
        handlers={"read_value": tool_handler, "search_memory": tool_handler},
        tool_selection_policy=CoordinatedSelection({"max_visible_tools": 2}),
        automatic_memory_recall=True,
        memory_recall_query_generator=CoordinatedRecallQuery(),
    )

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert selection_started.is_set() and recall_started.is_set()


@pytest.mark.asyncio
async def test_large_catalog_is_bounded_and_expansion_changes_the_next_request():
    expand = ToolDefinition(
        name="tool_expand_tools",
        description="activate exact tool names",
        input_schema={
            "type": "object",
            "properties": {
                "tool_names": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
            "required": ["tool_names"],
        },
    )
    alpha = ToolDefinition(name="alpha", description="alpha", input_schema={})
    beta = ToolDefinition(name="beta", description="beta", input_schema={})
    target = ToolDefinition(
        name="zzz_target", description="hidden target", input_schema={}
    )
    policy = LexicalToolSelectionPolicy(
        {
            "direct_tool_count_threshold": 0,
            "max_visible_tools": 2,
            "candidate_top_k": 2,
            "expansion_batch_limit": 1,
            "max_expanded_tools_per_run": 1,
            "always_visible_tools": ["tool_expand_tools"],
        }
    )

    def initial_request(request):
        names = [tool.name for tool in request.tools]
        assert names == ["alpha", "tool_expand_tools"]
        assert "zzz_target" not in names
        assert request.metadata["tool_selection"]["hidden_index_count"] == 2
        assert any(
            message.metadata.get("runtime_tool_index") for message in request.messages
        )

    def expanded_request(request):
        assert "zzz_target" in [tool.name for tool in request.tools]
        assert request.metadata["tool_selection"]["expanded_tools"] == ("zzz_target",)

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                assertion=initial_request,
                events=(
                    completed(
                        calls=(
                            ModelToolCall(
                                tool_call_id="call_expand",
                                name="tool_expand_tools",
                                arguments={"tool_names": ["zzz_target"]},
                            ),
                        )
                    ),
                ),
            ),
            ScriptedModelStep(
                assertion=expanded_request,
                events=(completed("expanded"),),
            ),
        )
    )
    tools = (expand, alpha, beta, target)
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=tools,
        handlers={tool.name: tool_handler for tool in tools},
        tool_selection_policy=policy,
    )

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED


@pytest.mark.asyncio
async def test_plan_invocation_keeps_the_agent_tool_catalog_visible():
    def assert_all_tools_visible(request):
        assert [tool.name for tool in request.tools] == [
            "read_value",
            "write_value",
        ]

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                assertion=assert_all_tools_visible,
                events=(completed(calls=(tool_call("read_value"),)),),
            ),
            ScriptedModelStep(events=(completed("inspected"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(
        model,
        tools=(READ_TOOL, WRITE_TOOL),
        invocation_mode="plan",
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert [call.tool_name for call in executor.calls] == ["read_value"]
    assert executor._results == {}
    assert executor._call_fingerprints == {}


@pytest.mark.asyncio
async def test_model_request_localizes_builtin_tool_metadata():
    tool = ToolDefinition(
        name="file_read",
        description="Read text file within a line range.",
        input_schema={
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
            "additionalProperties": False,
        },
    )
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("已完成"),)),))
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=(tool,),
        handlers={"file_read": tool_handler},
        response_language="zh-CN",
    )

    await loop.execute(handle.run_id, CONTEXT)

    projected = model.requests[0].tools[0]
    assert projected.description.startswith("读取文本文件")
    assert projected.input_schema["properties"]["file_path"]["description"] == (
        "文件虚拟路径"
    )


class SignalSequence:
    def __init__(self, *values: ContinuationSignals):
        self.values = list(values)

    def __call__(self, run_id: str) -> ContinuationSignals:
        assert run_id
        return self.values.pop(0) if self.values else ContinuationSignals()


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
    assert types.count("message.delta") == 1
    assert (
        next(event.data.delta for event in events if event.type == "message.delta")
        == "hello"
    )
    assert "message.completed" in types
    assert "continuation.decided" in types
    assert types[-3:] == ["step.completed", "turn.completed", "run.completed"]
    assert [event.run_sequence for event in events] == list(range(1, len(events) + 1))


@pytest.mark.asyncio
async def test_explicit_task_done_signal_completes_and_is_recorded():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("All requested work is done."),)),)
    )
    signals = SignalSequence(ContinuationSignals(explicit_status="task_done"))
    runtime, handle, loop, _ = await setup_loop(
        model, continuation_signal_provider=signals
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    decisions = [event for event in events if event.type == "continuation.decided"]

    assert result.state == RunState.COMPLETED
    assert decisions[-1].data.action == "complete_run"
    assert decisions[-1].data.reason_code == "status.complete"


@pytest.mark.asyncio
async def test_continue_work_signal_is_one_step_and_then_final_text_completes():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("Still working."),)),
            ScriptedModelStep(events=(completed("Now complete."),)),
        )
    )
    signals = SignalSequence(ContinuationSignals(explicit_status="continue_work"))
    runtime, handle, loop, _ = await setup_loop(
        model, continuation_signal_provider=signals
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    reasons = [
        event.data.reason_code
        for event in events
        if event.type == "continuation.decided"
    ]

    assert result.state == RunState.COMPLETED
    assert len(model.requests) == 2
    assert reasons == ["status.continue", "text.final"]


@pytest.mark.asyncio
async def test_need_user_input_signal_suspends_and_resumes_with_canonical_input():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("Which target should I use?"),)),
            ScriptedModelStep(events=(completed("Deployed to staging."),)),
        )
    )
    signals = SignalSequence(
        ContinuationSignals(
            explicit_status="need_user_input",
            explicit_status_note="Choose production or staging.",
        )
    )
    runtime, handle, loop, _ = await setup_loop(
        model, continuation_signal_provider=signals
    )

    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)

    assert suspended.state == RunState.SUSPENDED
    assert interaction.allowed_decisions == ("submit", "cancel")
    assert interaction.payload["status"] == "need_user_input"
    assert interaction.payload["prompt"] == "Choose production or staging."
    assert interaction.payload["questions"]
    assert interaction.payload["language"] == "en"
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="submit",
            payload={"text": "Use staging."},
            idempotency_key="submit-target",
        ),
        CONTEXT,
    )
    completed_run = await loop.resume(handle.run_id, CONTEXT)

    assert completed_run.state == RunState.COMPLETED
    assert model.requests[1].messages[-1].content == (TextBlock(text="Use staging."),)


@pytest.mark.asyncio
async def test_validated_questionnaire_result_completes_without_calling_judge():
    questionnaire_tool = ToolDefinition(
        name="questionnaire_async",
        description="Ask the user a structured question.",
        input_schema={"type": "object", "properties": {}},
    )

    async def questionnaire_handler(call, context):
        del context
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(
                JsonBlock(
                    value={
                        "success": True,
                        "status": "awaiting_user_input",
                        "validation_passed": True,
                        "title": "Choose a target",
                        "questions": [
                            {
                                "id": "target",
                                "type": "single",
                                "title": "Where should I deploy?",
                                "options": ["staging", "production"],
                            }
                        ],
                        "should_end": True,
                    }
                ),
            ),
        )

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    completed(
                        "Choose a deployment target.",
                        calls=(tool_call("questionnaire_async", {}),),
                    ),
                )
            ),
        )
    )
    judge = ScriptedModelProvider(())
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(judge))
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=(questionnaire_tool,),
        handlers={"questionnaire_async": questionnaire_handler},
        continuation_policy=policy,
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    decision = next(event for event in events if event.type == "continuation.decided")

    assert result.state == RunState.COMPLETED
    assert decision.data.reason_code == "tool.questionnaire_ready"
    assert decision.data.details["source"] == "questionnaire_async"
    assert not any(event.type == "interaction.requested" for event in events)
    assert judge.requests == []


@pytest.mark.asyncio
async def test_empty_questionnaire_reply_reasks_instead_of_failing_the_run():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("Which target should I use?"),)),)
    )
    signals = SignalSequence(
        ContinuationSignals(
            explicit_status="need_user_input",
            explicit_status_note="Choose production or staging.",
        )
    )
    runtime, handle, loop, _ = await setup_loop(
        model, continuation_signal_provider=signals, response_language="zh-CN"
    )
    first = await loop.execute(handle.run_id, CONTEXT)
    first_suspension = await runtime.session_store.get_suspension(first.suspension_id)
    first_interaction = await runtime.session_store.get_interaction(
        first_suspension.interaction_id
    )
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=first_suspension.suspension_id,
            interaction_id=first_interaction.interaction_id,
            expected_revision=first.revision,
            expected_suspension_revision=first_suspension.expected_revision,
            expected_interaction_revision=first_interaction.expected_revision,
            decision="submit",
            payload={},
            idempotency_key="submit-empty-target",
        ),
        CONTEXT,
    )

    second = await loop.resume(handle.run_id, CONTEXT)
    second_suspension = await runtime.session_store.get_suspension(second.suspension_id)
    second_interaction = await runtime.session_store.get_interaction(
        second_suspension.interaction_id
    )

    assert second.state == RunState.SUSPENDED
    assert second_interaction.interaction_id != first_interaction.interaction_id
    assert second_interaction.payload["reason_code"] == "interaction.input_required"
    assert second_interaction.payload["language"] == "zh"
    assert second_interaction.payload["questions"]


@pytest.mark.asyncio
async def test_blocked_signal_suspends_with_recoverable_interaction():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("Repository access is required."),)),)
    )
    signals = SignalSequence(
        ContinuationSignals(
            explicit_status="blocked",
            explicit_status_note="Grant repository access, then continue.",
        )
    )
    runtime, handle, loop, _ = await setup_loop(
        model, continuation_signal_provider=signals
    )

    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    events = await runtime.session_store.read_events(handle.run_id)
    decision = next(event for event in events if event.type == "continuation.decided")

    assert suspended.state == RunState.SUSPENDED
    assert interaction.interaction_type.value == "user_input"
    assert interaction.allowed_decisions == ("submit", "cancel")
    assert interaction.payload["status"] == "blocked"
    assert interaction.payload["prompt"] == ("Grant repository access, then continue.")
    assert interaction.payload["questions"]
    assert decision.data.reason_code == "status.blocked"


@pytest.mark.asyncio
async def test_failed_explicit_status_requests_recovery_guidance():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("The operation failed."),)),)
    )
    signals = SignalSequence(ContinuationSignals(explicit_status="failed"))
    runtime, handle, loop, _ = await setup_loop(
        model, continuation_signal_provider=signals
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)

    assert result.state == RunState.SUSPENDED
    assert events[-1].type == "run.suspended"
    suspension = await runtime.session_store.get_suspension(result.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["reason_code"] == "status.failed"
    assert interaction.payload["questions"]


@pytest.mark.asyncio
async def test_recovery_questionnaire_uses_run_response_language():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("操作未能完成。"),)),)
    )
    signals = SignalSequence(ContinuationSignals(explicit_status="failed"))
    runtime, handle, loop, _ = await setup_loop(
        model,
        continuation_signal_provider=signals,
        response_language="zh-CN",
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    suspension = await runtime.session_store.get_suspension(result.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)

    assert interaction.payload["language"] == "zh"
    assert interaction.payload["title"] == "Agent 需要你的引导"
    assert interaction.payload["questions"][0]["title"] == "接下来应该怎么做？"


@pytest.mark.asyncio
async def test_judge_usage_and_metadata_are_committed_to_run_events():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("The report is ready."),)),)
    )
    judge = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="judge_response",
                            text='{"decision":"completed","reason":"Verified"}',
                            finish_reason="stop",
                            usage=UsageSummary(input_tokens=13, output_tokens=4),
                        ),
                    ),
                )
            ),
        )
    )
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(judge))
    runtime, handle, loop, _ = await setup_loop(
        model,
        continuation_policy=policy,
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    decision = next(event for event in events if event.type == "continuation.decided")
    usage = [event.data.usage for event in events if event.type == "usage.recorded"]

    assert result.state == RunState.COMPLETED
    assert decision.data.reason_code == "judge.completed"
    assert decision.data.details == {
        "policy": "llm_judge",
        "implementation": "v1",
    }
    assert [(value.input_tokens, value.output_tokens) for value in usage] == [
        (5, 2),
        (13, 4),
    ]


@pytest.mark.asyncio
async def test_judge_need_user_input_completes_without_suspension():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("Which target should I use?"),)),)
    )
    judge = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    completed(
                        '{"decision":"need_user_input",'
                        '"reason":"A deployment target is required."}'
                    ),
                )
            ),
        )
    )
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(judge))
    runtime, handle, loop, _ = await setup_loop(
        model,
        continuation_policy=policy,
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    decision = next(event for event in events if event.type == "continuation.decided")

    assert result.state == RunState.COMPLETED
    assert decision.data.action == "complete_run"
    assert decision.data.reason_code == "judge.need_user_input"
    assert decision.data.details["completion_status"] == "need_user_input"
    assert not any(event.type == "run.suspended" for event in events)


@pytest.mark.asyncio
async def test_v1_judge_continue_keeps_tool_choice_auto_and_injects_guidance():
    def assert_first_request(request):
        assert request.tool_choice == "auto"

    def assert_auto_request(request):
        assert request.tool_choice == "auto"
        guidance = request.messages[-1].content[0].text
        assert "Continue because: Verification is still missing." in guidance

    def assert_after_tool_request(request):
        assert request.tool_choice == "auto"
        assert not request.messages[-1].metadata.get("runtime_continuation_guidance")

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                assertion=assert_first_request,
                events=(completed("I still need to verify the value."),),
            ),
            ScriptedModelStep(
                assertion=assert_auto_request,
                events=(completed("", calls=(tool_call(),)),),
            ),
            ScriptedModelStep(
                assertion=assert_after_tool_request,
                events=(completed("The verified value is 42."),),
            ),
        )
    )
    judge = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    completed(
                        '{"decision":"continue",'
                        '"reason":"Verification is still missing."}'
                    ),
                )
            ),
            ScriptedModelStep(
                events=(
                    completed(
                        '{"decision":"completed","reason":"Verification succeeded."}'
                    ),
                )
            ),
        )
    )
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(judge))
    runtime, handle, loop, executor = await setup_loop(
        model,
        continuation_policy=policy,
    )

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert len(executor.calls) == 1
    assert len(judge.requests) == 2


@pytest.mark.asyncio
async def test_invalid_judge_output_does_not_leak_parser_error_into_next_request():
    def assert_auto_request(request):
        assert request.tool_choice == "auto"
        assert all(
            not message.metadata.get("runtime_continuation_guidance")
            for message in request.messages
        )

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("The first answer is ready."),)),
            ScriptedModelStep(
                assertion=assert_auto_request,
                events=(completed("", calls=(tool_call(),)),),
            ),
            ScriptedModelStep(events=(completed("The verified answer is ready."),)),
        )
    )
    judge = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed(""),)),
            ScriptedModelStep(
                events=(
                    completed(
                        '{"decision":"completed","reason":"Verification succeeded."}'
                    ),
                )
            ),
        )
    )
    runtime, handle, loop, executor = await setup_loop(
        model,
        continuation_policy=LLMJudgeContinuationPolicy(LLMContinuationJudge(judge)),
    )

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert len(executor.calls) == 1


@pytest.mark.asyncio
async def test_typed_flow_boundary_completes_node_without_finish_reason_inference():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("Node output is ready."),)),)
    )
    runtime, handle, loop, _ = await setup_loop(
        model,
        flow_boundary="complete_node",
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    decision = next(event for event in events if event.type == "continuation.decided")

    assert result.state == RunState.COMPLETED
    assert decision.data.action == "complete_turn"
    assert decision.data.reason_code == "flow.node_complete"


@pytest.mark.asyncio
async def test_continue_node_flow_boundary_is_consumed_once():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("Continue the node."),)),
            ScriptedModelStep(events=(completed("Node is now complete."),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(
        model,
        flow_boundary="continue_node",
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    reasons = [
        event.data.reason_code
        for event in events
        if event.type == "continuation.decided"
    ]

    assert result.state == RunState.COMPLETED
    assert reasons == ["flow.node_continue", "text.final"]
    assert len(model.requests) == 2


@pytest.mark.asyncio
async def test_flow_boundary_survives_tool_dispatch_until_node_output_is_ready():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(completed("", calls=(tool_call("read_value"),)),)
            ),
            ScriptedModelStep(events=(completed("Node output: 42"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(
        model,
        flow_boundary="complete_node",
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    reasons = [
        event.data.reason_code
        for event in events
        if event.type == "continuation.decided"
    ]

    assert result.state == RunState.COMPLETED
    assert reasons == ["tool.pending", "flow.node_complete"]
    assert len(executor.calls) == 1
    assert len(model.requests) == 2


@pytest.mark.asyncio
async def test_text_stream_preserves_markdown_whitespace_between_deltas():
    chunks = ("已完成。", "\n\n", "## ", "实时标题", "\n\n", "- ", "列表项")
    markdown = "".join(chunks)
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    *(
                        ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta=chunk)
                        for chunk in chunks
                    ),
                    completed(markdown),
                )
            ),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model)

    await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    streamed = "".join(
        event.data.delta
        for event in events
        if event.type == "message.delta"
        and isinstance(event.data, ItemEventData)
        and isinstance(event.data.delta, str)
    )

    assert streamed == markdown


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
    assert run.state == RunState.SUSPENDED
    assert events[-1].type == "run.suspended"
    suspension = await runtime.session_store.get_suspension(run.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["reason_code"] == "budget.deadline"
    assert interaction.payload["questions"]


@pytest.mark.asyncio
async def test_model_call_to_unavailable_tool_requests_recovery_guidance():
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

    assert run.state == RunState.SUSPENDED
    assert executor.calls == []
    assert events[-1].type == "run.suspended"
    suspension = await runtime.session_store.get_suspension(run.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["reason_code"] == "tool.not_found"


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
@pytest.mark.parametrize("feedback", ["", "请先补充测试方案，再提交计划。"])
async def test_declined_write_never_dispatches_and_model_receives_decline_result(feedback):
    def assert_decline(request):
        tool_result = request.messages[-1]
        assert tool_result.role == "tool"
        assert "declined" in tool_result.content[0].text
        if feedback:
            assert feedback in tool_result.content[1].text
        else:
            assert len(tool_result.content) == 1

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
            payload={"text": feedback},
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
    if feedback:
        events = await runtime.session_store.read_events(handle.run_id)
        results = [
            event.data.item.data
            for event in events
            if event.type == "item.completed"
            and isinstance(event.data, ItemEventData)
            and event.data.item is not None
            and isinstance(event.data.item.data, ToolResultItemData)
        ]
        assert any(feedback in block.text for item in results for block in item.content if isinstance(block, TextBlock))



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
async def test_model_failure_matrix_requests_typed_recovery_questionnaire(
    step, error_code
):
    runtime, handle, loop, _ = await setup_loop(ScriptedModelProvider((step,)))
    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    assert result.state == RunState.SUSPENDED
    assert events[-1].type == "run.suspended"
    suspension = await runtime.session_store.get_suspension(result.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["reason_code"] == error_code
    assert interaction.payload["questions"]
    assert interaction.allowed_decisions == ("retry", "change_direction", "cancel")


@pytest.mark.asyncio
async def test_empty_semantic_response_retries_transparently_before_suspending():
    empty = RuntimeErrorInfo(
        code="model.empty_semantic_response",
        category=ErrorCategory.PROVIDER_TRANSIENT,
        message=(
            "provider reported output tokens but returned no supported text, "
            "reasoning, or Tool call fields"
        ),
        retryable=True,
        safe_to_resume=True,
        metadata={"output_tokens": 1721},
    )
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(), error=empty),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model)

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert len(model.requests) == 2
    events = await runtime.session_store.read_events(handle.run_id)
    retries = [event for event in events if event.type == "step.retry_scheduled"]
    assert len(retries) == 1
    assert retries[0].data.error.code == "model.empty_semantic_response"
    assert not any(event.type == "interaction.requested" for event in events)


@pytest.mark.asyncio
async def test_pre_stream_context_overflow_reduces_once_with_adaptive_reserve():
    overflow = RuntimeErrorInfo(
        code="model.context_window_exceeded",
        category=ErrorCategory.VALIDATION,
        message="provider rejected the request context",
        retryable=True,
        safe_to_resume=True,
        metadata={"response_started": False},
    )
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(), error=overflow),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )
    assembler = DefaultContextAssembler(budget=ContextBudget(max_input_tokens=2_000))
    runtime, handle, loop, _ = await setup_loop(model, context_assembler=assembler)

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert len(model.requests) == 2
    first_budget = model.requests[0].metadata["request_budget"]
    second_budget = model.requests[1].metadata["request_budget"]
    assert (
        second_budget["protocol_overhead_tokens"]
        >= first_budget["protocol_overhead_tokens"] + 512
    )
    events = await runtime.session_store.read_events(handle.run_id)
    retries = [event for event in events if event.type == "step.retry_scheduled"]
    assert len(retries) == 1
    assert retries[0].data.error.code == "model.context_window_exceeded"


class BlockingModelProvider:
    def __init__(self):
        self.started = asyncio.Event()
        self.closed = asyncio.Event()
        self.requests = []
        self._release = asyncio.Event()

    async def _stream(self, request):
        self.requests.append(request)
        self.started.set()
        try:
            await self._release.wait()
            if False:
                yield completed()
        finally:
            self.closed.set()

    def stream(self, request):
        return self._stream(request)


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["pause", "cancel"])
async def test_blocked_model_stream_observes_durable_control_without_a_delta(control):
    model = BlockingModelProvider()
    runtime, handle, loop, _ = await setup_loop(model)
    execution = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(model.started.wait(), timeout=1)
    current = await runtime.get_run(handle.run_id)
    if control == "pause":
        await runtime.pause_run(
            PauseRun(
                run_id=handle.run_id,
                expected_revision=current.revision,
                idempotency_key="pause-blocked-stream",
            ),
            CONTEXT,
        )
    else:
        await runtime.cancel_run(
            CancelRun(
                run_id=handle.run_id,
                expected_revision=current.revision,
                idempotency_key="cancel-blocked-stream",
            ),
            CONTEXT,
        )

    result = await asyncio.wait_for(execution, timeout=1)

    assert result.state == (
        RunState.SUSPENDED if control == "pause" else RunState.CANCELLED
    )
    assert model.closed.is_set()


@pytest.mark.asyncio
async def test_deadline_interrupts_a_blocked_model_stream():
    model = BlockingModelProvider()
    runtime, handle, loop, _ = await setup_loop(model, deadline_seconds=0.05)

    result = await asyncio.wait_for(loop.execute(handle.run_id, CONTEXT), timeout=1)

    assert result.state == RunState.SUSPENDED
    assert model.closed.is_set()
    suspension = await runtime.session_store.get_suspension(result.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["reason_code"] == "budget.deadline"


@pytest.mark.asyncio
async def test_cooperative_tool_is_cancelled_and_checkpointed_for_pause():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    tool = ToolDefinition(
        name="cooperative_wait",
        description="wait cooperatively",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
        cancel_semantics=CancelSemantics.COOPERATIVE,
    )
    call = ModelToolCall(tool_call_id="call_cooperative", name=tool.name, arguments={})

    async def handler(tool_call, _context):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
        )

    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("", calls=(call,)),)),)
    )
    runtime, handle, loop, _ = await setup_loop(
        model, tools=(tool,), handlers={tool.name: handler}
    )
    execution = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(started.wait(), timeout=1)
    current = await runtime.get_run(handle.run_id)
    await runtime.pause_run(
        PauseRun(
            run_id=handle.run_id,
            expected_revision=current.revision,
            idempotency_key="pause-cooperative-tool",
        ),
        CONTEXT,
    )

    result = await asyncio.wait_for(execution, timeout=1)

    assert result.state == RunState.SUSPENDED
    assert cancelled.is_set()
    events = await runtime.session_store.read_events(handle.run_id)
    assert any(event.type == "tool.call.cancelled" for event in events)
    cancelled_item = next(
        event.data.item.data
        for event in events
        if isinstance(event.data, ItemEventData)
        and event.data.item is not None
        and isinstance(event.data.item.data, ToolResultItemData)
    )
    assert cancelled_item.metadata["cancellation_confirmed"] is True


@pytest.mark.asyncio
async def test_non_cancellable_tool_settles_before_pause_without_state_conflict():
    started = asyncio.Event()
    release = asyncio.Event()
    tool = ToolDefinition(
        name="non_cancellable_wait",
        description="wait until settled",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
        cancel_semantics=CancelSemantics.NOT_SUPPORTED,
    )
    call = ModelToolCall(
        tool_call_id="call_non_cancellable", name=tool.name, arguments={}
    )

    async def handler(tool_call, _context):
        started.set()
        await release.wait()
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
            content=(TextBlock(text="settled"),),
        )

    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("", calls=(call,)),)),)
    )
    runtime, handle, loop, _ = await setup_loop(
        model, tools=(tool,), handlers={tool.name: handler}
    )
    execution = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(started.wait(), timeout=1)
    current = await runtime.get_run(handle.run_id)
    await runtime.pause_run(
        PauseRun(
            run_id=handle.run_id,
            expected_revision=current.revision,
            idempotency_key="pause-non-cancellable-tool",
        ),
        CONTEXT,
    )
    await asyncio.sleep(0.15)
    assert not execution.done()
    release.set()

    result = await asyncio.wait_for(execution, timeout=1)

    assert result.state == RunState.SUSPENDED
    events = await runtime.session_store.read_events(handle.run_id)
    assert any(event.type == "tool.call.succeeded" for event in events)


@pytest.mark.asyncio
async def test_deadline_cooperatively_cancels_a_blocked_tool():
    started = asyncio.Event()
    cancelled = asyncio.Event()
    tool = ToolDefinition(
        name="deadline_wait",
        description="wait cooperatively",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
        cancel_semantics=CancelSemantics.COOPERATIVE,
    )
    call = ModelToolCall(tool_call_id="call_deadline", name=tool.name, arguments={})

    async def handler(tool_call, _context):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
        )

    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("", calls=(call,)),)),)
    )
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=(tool,),
        handlers={tool.name: handler},
        deadline_seconds=0.05,
    )

    result = await asyncio.wait_for(loop.execute(handle.run_id, CONTEXT), timeout=1)

    assert started.is_set() and cancelled.is_set()
    assert result.state == RunState.SUSPENDED
    suspension = await runtime.session_store.get_suspension(result.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["reason_code"] == "budget.deadline"


@pytest.mark.asyncio
async def test_repeated_empty_semantic_responses_explain_exhausted_retries():
    empty = RuntimeErrorInfo(
        code="model.empty_semantic_response",
        category=ErrorCategory.PROVIDER_TRANSIENT,
        message="provider returned token usage without semantic output",
        retryable=True,
        safe_to_resume=True,
        metadata={"output_tokens": 1721, "finish_reason": "stop"},
    )
    model = ScriptedModelProvider(
        tuple(ScriptedModelStep(events=(), error=empty) for _ in range(3))
    )
    runtime, handle, loop, _ = await setup_loop(model, response_language="zh")

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.SUSPENDED
    assert len(model.requests) == 3
    suspension = await runtime.session_store.get_suspension(result.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    error = interaction.payload["error"]
    assert error["code"] == "model.empty_semantic_response"
    assert error["metadata"]["transparent_retries_exhausted"] == 2
    assert "没有返回可用的文本" in interaction.payload["prompt"]


@pytest.mark.asyncio
async def test_reasoning_only_response_does_not_pollute_next_model_request():
    def no_empty_assistant_messages(request):
        assert not any(
            message.role == "assistant"
            and not message.content
            and not message.tool_calls
            for message in request.messages
        )

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="reasoning_only",
                            reasoning="internal reasoning",
                            finish_reason="stop",
                            usage=UsageSummary(output_tokens=12),
                        ),
                    ),
                )
            ),
            ScriptedModelStep(
                assertion=no_empty_assistant_messages,
                events=(completed("done"),),
            ),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model)

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    rebuilt = await loop.ledger_rebuilder.rebuild(
        await runtime.session_store.get_start_command(handle.run_id),
        run_id=handle.run_id,
    )
    assert not any(
        message.role == "assistant" and not message.content and not message.tool_calls
        for message in rebuilt
    )


@pytest.mark.asyncio
async def test_automatic_memory_recall_checkpoint_resumes_without_digest_mismatch():
    class RecallQuery:
        async def generate(self, user_input, *, run_id):
            assert user_input == "do task"
            assert run_id
            return "current task"

    memory_tool = ToolDefinition(
        name="search_memory",
        description="search memory",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
    )
    failure = RuntimeErrorInfo(
        code="model.rate_limited",
        category=ErrorCategory.RATE_LIMITED,
        message="rate limited",
        retryable=True,
        safe_to_resume=True,
    )
    model = ScriptedModelProvider((ScriptedModelStep(events=(), error=failure),))
    runtime, handle, loop, _ = await setup_loop(
        model,
        tools=(memory_tool,),
        handlers={"search_memory": tool_handler},
        automatic_memory_recall=True,
        memory_recall_query_generator=RecallQuery(),
    )
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="cancel",
            idempotency_key="cancel_after_memory_recall",
        ),
        CONTEXT,
    )

    result = await loop.resume(handle.run_id, CONTEXT)

    assert result.state == RunState.CANCELLED


@pytest.mark.asyncio
async def test_step_budget_requests_guidance_instead_of_looping_forever():
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),)
    )
    runtime, handle, loop, executor = await setup_loop(model, max_steps=1)
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state == RunState.SUSPENDED
    assert len(executor.calls) == 1
    suspension = await runtime.session_store.get_suspension(result.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    assert interaction.payload["reason_code"] == "budget.max_steps"
    assert interaction.payload["reset_step_budget"] is True


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
async def test_provider_stream_closes_even_when_final_batch_flush_fails(monkeypatch):
    class ClosingStream:
        def __init__(self):
            self.sent = False
            self.closed = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.sent:
                raise StopAsyncIteration
            self.sent = True
            return completed("done")

        async def aclose(self):
            self.closed = True

    stream = ClosingStream()

    class ClosingModel:
        async def capabilities(self, model_binding):
            return ModelCapabilities(
                supports_streaming=True,
                supports_tools=False,
                supports_parallel_tool_calls=False,
                supports_reasoning=False,
                supports_multimodal_input=False,
                supports_structured_output=False,
            )

        def stream(self, request):
            return stream

    async def fail_flush(self):
        raise OSError("injected flush failure")

    monkeypatch.setattr(StreamEventBatcher, "flush", fail_flush)
    runtime, handle, loop, _ = await setup_loop(ClosingModel(), tools=(), handlers={})
    result = await loop.execute(handle.run_id, CONTEXT)
    assert result.state in {RunState.FAILED, RunState.SUSPENDED}
    assert stream.closed is True


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
    state = AgentLoopCheckpointCodec.decode(checkpoint.state)
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

    runtime = ephemeral_runtime()
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
    assert checkpoint.checkpoint_codec_version == "agent-loop/3"
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
    restored_runtime = ephemeral_runtime()
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
async def test_generic_write_failure_after_dispatch_is_unknown_not_failed():
    class ResponseLostExecutor:
        def __init__(self):
            self.remote_commits = 0

        async def execute(self, call, context):
            del call, context
            self.remote_commits += 1
            raise RuntimeError("response lost after remote commit")

    executor = ResponseLostExecutor()
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("", calls=(tool_call("write_value"),)),)),)
    )
    runtime, handle, loop, _ = await setup_loop(model, tools=(WRITE_TOOL,))
    loop.tool_executor = executor
    loop.tool_policy = DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.AUTO_APPROVE
    )

    suspended = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    types = [event.type for event in events]

    assert suspended.state == RunState.SUSPENDED
    assert executor.remote_commits == 1
    assert "tool.call.unknown" in types
    assert "tool.call.failed" not in types


@pytest.mark.asyncio
async def test_authoritative_write_tool_error_is_failed_without_losing_content():
    class RejectedWriteExecutor:
        async def execute(self, call, context):
            del context
            return ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text="remote rejected the write: quota exceeded"),),
                error=RuntimeErrorInfo(
                    code="remote.write_rejected",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="write rejected",
                    safe_to_resume=True,
                    metadata={"tool_result_received": True},
                ),
                metadata={"tool_result_received": True},
            )

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(completed("", calls=(tool_call("write_value"),)),)
            ),
            ScriptedModelStep(events=(completed("handled"),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model, tools=(WRITE_TOOL,))
    loop.tool_executor = RejectedWriteExecutor()
    loop.tool_policy = DefaultToolPolicy(
        approval_strategy=ApprovalStrategy.AUTO_APPROVE
    )

    result = await loop.execute(handle.run_id, CONTEXT)
    types = [
        event.type for event in await runtime.session_store.read_events(handle.run_id)
    ]
    tool_message = next(
        message for message in model.requests[1].messages if message.role == "tool"
    )

    assert result.state == RunState.COMPLETED
    assert "tool.call.failed" in types
    assert "tool.call.unknown" not in types
    assert tool_message.content[0].text == "remote rejected the write: quota exceeded"


@pytest.mark.asyncio
async def test_read_tool_generic_failure_remains_a_known_failure():
    class FailedReadExecutor:
        async def execute(self, call, context):
            del call, context
            raise RuntimeError("read provider unavailable")

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),
            ScriptedModelStep(events=(completed("handled"),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(model, tools=(READ_TOOL,))
    loop.tool_executor = FailedReadExecutor()

    result = await loop.execute(handle.run_id, CONTEXT)
    types = [
        event.type for event in await runtime.session_store.read_events(handle.run_id)
    ]

    assert result.state == RunState.COMPLETED
    assert "tool.call.failed" in types
    assert "tool.call.unknown" not in types


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
    state = AgentLoopCheckpointCodec.decode(checkpoint.state)

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


# ---------- 审批记忆：approve_and_remember ----------


def _session_memory(runtime):
    return SessionApprovalMemory(runtime.session_store)


@pytest.mark.asyncio
@pytest.mark.parametrize("updated_policy", ["deny", "always", "changed-matcher"])
async def test_pending_approval_cannot_override_tightened_host_policy(updated_policy):
    from sagents.v2.agent.policy.tool_policy import (
        ToolOperationAssessment, ToolPolicyAction, exact_arguments_matcher,
    )

    model = ScriptedModelProvider((
        ScriptedModelStep(events=(completed("", calls=(_write_call("call_1"),)),)),
        ScriptedModelStep(events=(completed("done"),)),
    ))
    runtime, handle, loop, executor = await setup_loop(
        model, tool_policy=DefaultToolPolicy(allow_persistent_approval=True),
        approval_memory=_session_memory,
    )
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, suspended)
    await runtime.reply_interaction(_approval_reply(
        handle.run_id, suspended, suspension, interaction,
        "approve_and_remember", "remember_before_policy_change",
    ), CONTEXT)
    if updated_policy == "deny":
        loop.tool_policy = DefaultToolPolicy(
            operation_assessor=lambda _: ToolOperationAssessment(
                action=ToolPolicyAction.DENY, reason="host now forbids this operation"
            ), operation_assessor_id="deny/v1",
        )
    elif updated_policy == "always":
        loop.tool_policy = DefaultToolPolicy(approval_strategy=ApprovalStrategy.ALWAYS_ASK)
    else:
        loop.tool_policy = DefaultToolPolicy(
            allow_persistent_approval=True,
            approval_matcher=lambda ctx: exact_arguments_matcher(ctx).model_copy(
                update={"fingerprint": "new-matcher"}
            ), approval_matcher_id="new/v1",
        )
    result = await loop.resume(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert len(executor.calls) == (0 if updated_policy == "deny" else 1)
    assert await loop.approval_memory.list_remembered(session_id=result.session_id) == ()
    events = await runtime.session_store.read_events(handle.run_id)
    assert "policy.approval.remembered" not in [event.type for event in events]
    if updated_policy == "deny":
        assert any(event.type == "policy.decision.recorded" and event.data.decision == "deny"
                   for event in events)


def _write_call(call_id: str, key: str = "a", value: str = "1") -> ModelToolCall:
    return ModelToolCall(
        tool_call_id=call_id, name="write_value", arguments={"key": key, "value": value}
    )


async def _pending_interaction(runtime, suspended):
    suspension = await runtime.session_store.get_suspension(suspended.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    return suspension, interaction


def _approval_reply(run_id, suspended, suspension, interaction, decision, key, **payload):
    return ReplyInteraction(
        run_id=run_id,
        suspension_id=suspension.suspension_id,
        interaction_id=interaction.interaction_id,
        expected_revision=suspended.revision,
        expected_suspension_revision=suspension.expected_revision,
        expected_interaction_revision=interaction.expected_revision,
        decision=decision,
        payload=payload,
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_approve_and_remember_skips_approval_for_the_same_call_in_the_session():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(_write_call("call_1"),)),)),
            ScriptedModelStep(events=(completed("", calls=(_write_call("call_2"),)),)),
            ScriptedModelStep(
                events=(completed("", calls=(_write_call("call_3", key="b"),)),)
            ),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(
        model,
        tool_policy=DefaultToolPolicy(allow_persistent_approval=True),
        approval_memory=_session_memory,
    )
    memory = loop.approval_memory
    session_id = (await runtime.get_run(handle.run_id)).session_id

    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, suspended)
    assert interaction.allowed_decisions == (
        "approve_once",
        "approve_and_remember",
        "deny",
        "cancel",
    )
    assert interaction.payload["persistent_approval_allowed"] is True
    assert interaction.payload["approval_scopes"] == ["session"]
    assert interaction.payload["approval_matcher"]["tool_name"] == "write_value"

    await runtime.reply_interaction(
        _approval_reply(
            handle.run_id,
            suspended,
            suspension,
            interaction,
            "approve_and_remember",
            "remember_1",
        ),
        CONTEXT,
    )
    again = await loop.resume(handle.run_id, CONTEXT)

    # call_2 参数完全相同 → 直接放行；call_3 参数不同 → 再次挂起。
    assert again.state == RunState.SUSPENDED
    assert [call.tool_call_id for call in executor.calls] == ["call_1", "call_2"]
    remembered = await memory.list_remembered(session_id=session_id)
    assert len(remembered) == 1
    assert remembered[0].scope == "session"
    assert remembered[0].remembered_by == "user_1"
    events = await runtime.session_store.read_events(handle.run_id)
    types = [event.type for event in events]
    assert types.count("tool.call.awaiting_approval") == 2
    assert types.count("policy.approval.remembered") == 1
    assert types.index("policy.approval.remembered") < types.index(
        "tool.call.dispatching"
    )
    audit = next(event for event in events if event.type == "policy.approval.remembered")
    assert audit.data.remembered_by == "user_1"
    assert audit.data.remembered_scope == "session"
    assert audit.data.decision == "approve_and_remember"
    auto_allowed = [
        event
        for event in events
        if event.type == "policy.decision.recorded"
        and event.data.remembered_by == "user_1"
    ]
    assert len(auto_allowed) == 1
    assert auto_allowed[0].data.decision == "allow"
    assert auto_allowed[0].data.remembered_scope == "session"

    suspension, interaction = await _pending_interaction(runtime, again)
    assert (
        interaction.payload["approval_matcher"]["fingerprint"]
        != remembered[0].matcher.fingerprint
    )
    await runtime.reply_interaction(
        _approval_reply(
            handle.run_id, again, suspension, interaction, "approve_once", "approve_3"
        ),
        CONTEXT,
    )
    final = await loop.resume(handle.run_id, CONTEXT)

    assert final.state == RunState.COMPLETED
    assert len(executor.calls) == 3
    # approve_once 不写记忆。
    assert len(await memory.list_remembered(session_id=session_id)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_policy", "with_memory"),
    [
        pytest.param(None, True, id="default-policy-with-memory"),
        pytest.param(
            DefaultToolPolicy(allow_persistent_approval=True),
            False,
            id="persistent-policy-without-memory",
        ),
        pytest.param(
            DefaultToolPolicy(
                approval_strategy=ApprovalStrategy.ALWAYS_ASK,
                allow_persistent_approval=True,
            ),
            True,
            id="always-ask-with-memory",
        ),
    ],
)
async def test_remember_is_only_offered_when_policy_and_memory_both_allow(
    tool_policy, with_memory
):
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("", calls=(_write_call("call_1"),)),)),)
    )
    runtime, handle, loop, _executor = await setup_loop(
        model,
        tool_policy=tool_policy,
        approval_memory=_session_memory if with_memory else None,
    )

    suspended = await loop.execute(handle.run_id, CONTEXT)
    _suspension, interaction = await _pending_interaction(runtime, suspended)

    assert interaction.allowed_decisions == ("approve_once", "deny", "cancel")
    assert "approval_scopes" not in interaction.payload


@pytest.mark.asyncio
async def test_remembered_approval_never_overrides_a_denial():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(_write_call("call_1"),)),)),
            ScriptedModelStep(events=(completed("done"),)),
            ScriptedModelStep(events=(completed("", calls=(_write_call("call_2"),)),)),
            ScriptedModelStep(events=(completed("denied anyway"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(
        model,
        tool_policy=DefaultToolPolicy(allow_persistent_approval=True),
        approval_memory=_session_memory,
    )
    session_id = (await runtime.get_run(handle.run_id)).session_id
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, suspended)
    await runtime.reply_interaction(
        _approval_reply(
            handle.run_id,
            suspended,
            suspension,
            interaction,
            "approve_and_remember",
            "remember_1",
        ),
        CONTEXT,
    )
    assert (await loop.resume(handle.run_id, CONTEXT)).state == RunState.COMPLETED
    assert len(await loop.approval_memory.list_remembered(session_id=session_id)) == 1

    # 同一 Session 里换一个没有 filesystem:write scope 的 actor：策略先 DENY，
    # 记忆只能收敛 REQUIRE_INTERACTION，绝不把 DENY 变成 ALLOW。
    unscoped = RequestContext(
        actor=ActorRef(
            principal_id="user_1",
            principal_type=PrincipalType.USER,
            tenant_id="tenant_1",
        )
    )
    second = await runtime.start_run(
        StartRun(
            session_id=session_id,
            agent_id="agent_test",
            input=(InputItem(role="user", content=(TextBlock(text="again"),)),),
            config=RunConfig(model_bindings={"primary": "test-model"}, max_steps=10),
            resolved_spec_hash="sha256:agent",
            idempotency_key="start_2",
        ),
        unscoped,
    )
    result = await loop.execute(second.run_id, unscoped)

    assert result.state == RunState.COMPLETED
    assert [call.tool_call_id for call in executor.calls] == ["call_1"]
    events = await runtime.session_store.read_events(second.run_id)
    decisions = [event for event in events if event.type == "policy.decision.recorded"]
    assert [event.data.decision for event in decisions] == ["deny"]
    assert decisions[0].data.remembered_by is None
    assert "tool.call.dispatching" not in [event.type for event in events]


@pytest.mark.asyncio
async def test_unsupported_scope_is_tightened_to_session():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(_write_call("call_1"),)),)),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )
    runtime, handle, loop, _executor = await setup_loop(
        model,
        tool_policy=DefaultToolPolicy(allow_persistent_approval=True),
        approval_memory=_session_memory,
    )
    session_id = (await runtime.get_run(handle.run_id)).session_id
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, suspended)

    await runtime.reply_interaction(
        _approval_reply(
            handle.run_id,
            suspended,
            suspension,
            interaction,
            "approve_and_remember",
            "remember_workspace",
            scope="workspace",
        ),
        CONTEXT,
    )
    assert (await loop.resume(handle.run_id, CONTEXT)).state == RunState.COMPLETED

    remembered = await loop.approval_memory.list_remembered(session_id=session_id)
    assert [value.scope for value in remembered] == ["session"]
    audit = next(
        event
        for event in await runtime.session_store.read_events(handle.run_id)
        if event.type == "policy.approval.remembered"
    )
    assert audit.data.remembered_scope == "session"


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["cancel", "mark_failed", "confirm_succeeded"])
@pytest.mark.parametrize("language", ["en", "zh"])
async def test_manual_tool_resolution_survives_subsequent_approval(decision, language):
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(tool_call(),)),)),
            ScriptedModelStep(events=(completed("", calls=(_write_call("call_2"),)),)),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(
        model, response_language=language
    )
    uncertain = UncertainToolExecutor(())
    loop.tool_executor = uncertain
    suspended = await loop.execute(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, suspended)
    await runtime.reply_interaction(
        _approval_reply(
            handle.run_id, suspended, suspension, interaction, decision, "resolve"
        ),
        CONTEXT,
    )
    loop.tool_executor = executor
    suspended = await loop.resume(handle.run_id, CONTEXT)
    assert suspended.state == RunState.SUSPENDED
    suspension, interaction = await _pending_interaction(runtime, suspended)
    await runtime.reply_interaction(
        _approval_reply(
            handle.run_id, suspended, suspension, interaction, "approve_once", "approve"
        ),
        CONTEXT,
    )
    result = await loop.resume(handle.run_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    assert len(uncertain.calls) == 1
    assert [call.tool_call_id for call in executor.calls] == ["call_2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("first_decision", ["approve_once", "deny"])
@pytest.mark.parametrize("legacy_checkpoint", [False, True])
async def test_approval_restores_whole_tool_batch_before_next_model_request(
    first_decision,
    legacy_checkpoint,
):
    calls = (
        tool_call("write_value"),
        ModelToolCall(
            tool_call_id="call_2",
            name="write_value",
            arguments={"key": "b", "value": "2"},
        ),
        ModelToolCall(tool_call_id="call_3", name="read_value", arguments={"key": "b"}),
    )
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=calls),)),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(model)
    run = await loop.execute(handle.run_id, CONTEXT)
    for index, decision in enumerate((first_decision, "approve_once")):
        assert run.state == RunState.SUSPENDED
        assert len(model.requests) == 1
        suspension, interaction = await _pending_interaction(runtime, run)
        if legacy_checkpoint:
            checkpoint = await runtime.session_store.get_checkpoint(run.checkpoint_id)
            runtime.session_store._checkpoints[checkpoint.checkpoint_id] = (
                checkpoint.model_copy(
                    update={
                        "state": {
                            key: value
                            for key, value in checkpoint.state.items()
                            if not key.startswith("pending_response_")
                            and key != "pending_questionnaire_completed"
                        }
                    }
                )
            )
        await runtime.reply_interaction(
            _approval_reply(
                run.run_id, run, suspension, interaction, decision, f"batch:{index}"
            ),
            CONTEXT,
        )
        # A new engine must recover the queue exclusively from the checkpoint
        # and canonical ledger, without any old loop-local response object.
        loop = AgentLoopEngine(
            runtime=runtime,
            model=model,
            tool_catalog=InMemoryToolCatalog((READ_TOOL, WRITE_TOOL)),
            tool_executor=executor,
        )
        run = await loop.resume(run.run_id, CONTEXT)
    assert run.state == RunState.COMPLETED
    assert [call.tool_call_id for call in executor.calls] == (
        ["call_1", "call_2", "call_3"]
        if first_decision == "approve_once"
        else ["call_2", "call_3"]
    )
    request = model.requests[-1]
    assert [
        call.tool_call_id for message in request.messages for call in message.tool_calls
    ] == ["call_1", "call_2", "call_3"]
    assert [
        message.tool_call_id for message in request.messages if message.role == "tool"
    ] == ["call_1", "call_2", "call_3"]
    events = await runtime.session_store.read_events(run.run_id)
    assert len([event for event in events if event.type == "step.started"]) == 2
    assert len([event for event in events if event.type == "step.completed"]) == 2


@pytest.mark.asyncio
async def test_pause_during_tool_preserves_remaining_batch():
    started, finish = asyncio.Event(), asyncio.Event()

    async def blocking(call, context):
        if call.tool_call_id == "call_1":
            started.set()
            await finish.wait()
        return await tool_handler(call, context)

    calls = (
        tool_call(),
        ModelToolCall(tool_call_id="call_2", name="read_value", arguments={"key": "b"}),
    )
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=calls),)),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(
        model, tools=(READ_TOOL,), handlers={"read_value": blocking}
    )
    task = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(started.wait(), 1)
    run = await runtime.get_run(handle.run_id)
    await runtime.pause_run(
        PauseRun(
            run_id=run.run_id,
            expected_revision=run.revision,
            idempotency_key="pause-batch",
        ),
        CONTEXT,
    )
    finish.set()
    run = await asyncio.wait_for(task, 1)
    assert run.state == RunState.SUSPENDED
    suspension = await runtime.session_store.get_suspension(run.suspension_id)
    await runtime.resume_run(
        ResumeRun(
            run_id=run.run_id,
            suspension_id=run.suspension_id,
            expected_revision=run.revision,
            expected_suspension_revision=suspension.expected_revision,
            idempotency_key="resume-batch",
        ),
        CONTEXT,
    )
    run = await loop.resume(run.run_id, CONTEXT)
    assert run.state == RunState.COMPLETED
    assert [call.tool_call_id for call in executor.calls] == ["call_1", "call_2"]
    assert [
        message.tool_call_id
        for message in model.requests[-1].messages
        if message.role == "tool"
    ] == ["call_1", "call_2"]


@pytest.mark.asyncio
async def test_worker_restart_restores_token_budget_before_continuing_model():
    started = asyncio.Event()

    async def interrupted(call, context):
        started.set()
        await asyncio.Event().wait()

    runtime, handle, loop, _ = await setup_loop(
        ScriptedModelProvider(
            (
                ScriptedModelStep(
                    events=(
                        completed(
                            "",
                            calls=(tool_call(),),
                            input_tokens=900,
                            output_tokens=100,
                        ),
                    )
                ),
            )
        ),
        tools=(READ_TOOL,),
        handlers={"read_value": interrupted},
        max_total_tokens=1000,
    )
    task = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    model = ScriptedModelProvider(())
    loop = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((READ_TOOL,)),
        tool_executor=InMemoryToolExecutor(
            {"read_value": READ_TOOL}, {"read_value": tool_handler}
        ),
    )
    run = await loop.recover_interrupted(handle.run_id, CONTEXT)
    checkpoint = await runtime.session_store.get_checkpoint(run.checkpoint_id)
    state = AgentLoopCheckpointCodec.decode(checkpoint.state)
    assert (state.total_input_tokens, state.total_output_tokens) == (900, 100)
    suspension, interaction = await _pending_interaction(runtime, run)
    await runtime.reply_interaction(
        _approval_reply(
            run.run_id,
            run,
            suspension,
            interaction,
            "confirm_succeeded",
            "confirm-recovered",
        ),
        CONTEXT,
    )
    run = await loop.resume(run.run_id, CONTEXT)
    assert run.state == RunState.SUSPENDED
    events = await runtime.session_store.read_events(run.run_id)
    reasons = [
        event.data.reason_code
        for event in events
        if event.type == "continuation.decided"
    ]
    assert reasons[-1] == "budget.max_tokens"
    checkpoint = await runtime.session_store.get_checkpoint(run.checkpoint_id)
    state = AgentLoopCheckpointCodec.decode(checkpoint.state)
    assert (state.total_input_tokens, state.total_output_tokens) == (900, 100)
    assert model.requests == []


@pytest.mark.asyncio
async def test_worker_recovery_keeps_unstarted_calls_in_same_response():
    started = asyncio.Event()

    async def interrupted(call, context):
        started.set()
        await asyncio.Event().wait()

    calls = (
        tool_call(),
        ModelToolCall(tool_call_id="call_2", name="read_value", arguments={"key": "b"}),
    )
    runtime, handle, loop, _ = await setup_loop(
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("", calls=calls),)),)
        ),
        tools=(READ_TOOL,),
        handlers={"read_value": interrupted},
    )
    task = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("done"),)),))
    executor = InMemoryToolExecutor(
        {"read_value": READ_TOOL}, {"read_value": tool_handler}
    )
    loop = AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=InMemoryToolCatalog((READ_TOOL,)),
        tool_executor=executor,
    )
    run = await loop.recover_interrupted(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, run)
    await runtime.reply_interaction(
        _approval_reply(
            run.run_id,
            run,
            suspension,
            interaction,
            "confirm_succeeded",
            "recover-batch",
        ),
        CONTEXT,
    )
    run = await loop.resume(run.run_id, CONTEXT)
    assert run.state == RunState.COMPLETED
    assert [call.tool_call_id for call in executor.calls] == ["call_2"]
    assert [
        message.tool_call_id
        for message in model.requests[-1].messages
        if message.role == "tool"
    ] == ["call_1", "call_2"]


@pytest.mark.asyncio
@pytest.mark.parametrize("questionnaire_first", [True, False])
async def test_questionnaire_completion_survives_batch_approval(questionnaire_first):
    questionnaire = ToolDefinition(
        name="questionnaire_async", description="Ask a question", input_schema={}
    )
    payload = {
        "success": True,
        "status": "awaiting_user_input",
        "validation_passed": True,
        "should_end": True,
        "questions": [{"id": "choice", "title": "Choose", "options": ["a", "b"]}],
    }

    async def ask(call, context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(JsonBlock(value=payload),),
        )

    calls = (
        ModelToolCall(
            tool_call_id="question", name="questionnaire_async", arguments={}
        ),
        tool_call("write_value"),
    )
    if not questionnaire_first:
        calls = tuple(reversed(calls))
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("", calls=calls),)),)
    )
    judge = ScriptedModelProvider(())
    policy = LLMJudgeContinuationPolicy(LLMContinuationJudge(judge))
    runtime, handle, loop, executor = await setup_loop(
        model,
        tools=(questionnaire, WRITE_TOOL),
        handlers={"questionnaire_async": ask, "write_value": tool_handler},
        continuation_policy=policy,
    )
    run = await loop.execute(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, run)
    await runtime.reply_interaction(
        _approval_reply(
            run.run_id, run, suspension, interaction, "approve_once", "question-batch"
        ),
        CONTEXT,
    )
    run = await loop.resume(run.run_id, CONTEXT)
    assert run.state == RunState.COMPLETED
    assert len(executor.calls) == 2
    assert len(model.requests) == 1
    assert judge.requests == []
    events = await runtime.session_store.read_events(run.run_id)
    assert (
        next(
            event.data.reason_code
            for event in events
            if event.type == "continuation.decided"
        )
        == "tool.questionnaire_ready"
    )


@pytest.mark.asyncio
async def test_unavailable_tool_guidance_starts_new_model_decision():
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    completed(
                        "",
                        calls=(
                            ModelToolCall(
                                tool_call_id="missing", name="not_enabled", arguments={}
                            ),
                        ),
                    ),
                )
            ),
            ScriptedModelStep(events=(completed("done without that tool"),)),
        )
    )
    runtime, handle, loop, executor = await setup_loop(model, tools=(READ_TOOL,))
    run = await loop.execute(handle.run_id, CONTEXT)
    suspension, interaction = await _pending_interaction(runtime, run)
    reply = _approval_reply(
        run.run_id, run, suspension, interaction, "submit", "missing-tool-guidance"
    )
    await runtime.reply_interaction(
        reply.model_copy(update={"payload": {"text": "Skip that tool."}}), CONTEXT
    )
    run = await loop.resume(run.run_id, CONTEXT)
    assert run.state == RunState.COMPLETED
    assert len(model.requests) == 2
    assert model.requests[-1].messages[-1].content == (
        TextBlock(text="Skip that tool."),
    )
    assert executor.calls == []


async def reply_pending_interaction(runtime, handle, snapshot, decision, key):
    """回答当前挂起的交互，返回该交互以便断言其 allowed_decisions。"""

    suspension = await runtime.session_store.get_suspension(snapshot.suspension_id)
    interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=handle.run_id,
            suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id,
            expected_revision=snapshot.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision=decision,
            idempotency_key=key,
        ),
        CONTEXT,
    )
    return interaction


def persisted_tool_result(events, tool_call_id):
    """从 canonical Item 事件里取出某次工具调用落盘的结果 Item。"""

    for event in events:
        if event.type != "item.completed":
            continue
        item = event.data.item
        if (
            isinstance(item.data, ToolResultItemData)
            and item.data.tool_call_id == tool_call_id
        ):
            return item
    raise AssertionError(f"no persisted tool result for {tool_call_id}")


def two_write_steps_model():
    """两步都调用 write_value（各需一次审批），第三步收尾。"""

    return ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(tool_call("write_value"),)),)),
            ScriptedModelStep(
                events=(
                    completed(
                        "",
                        calls=(
                            ModelToolCall(
                                tool_call_id="call_2",
                                name="write_value",
                                arguments={"key": "b", "value": "2"},
                            ),
                        ),
                    ),
                )
            ),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["cancel", "mark_failed"])
async def test_manual_reconciliation_failure_keeps_the_checkpoint_ledger_resumable(
    decision,
):
    """人工核对以 cancel / mark_failed 结束后，下一次挂起再 resume 不能报 ledger 不一致。

    写进 checkpoint 的 ledger 摘要按内存 messages 计算，resume 时按 canonical Item
    事件重建；两者必须一致，所以内存里的工具结果消息必须来自真正落盘的 Item。
    """

    dispatches = []

    async def first_call_outcome_unknown(call, context):
        dispatches.append(call.tool_call_id)
        if len(dispatches) == 1:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="remote.rejected",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="remote rejected the write",
                    safe_to_resume=True,
                )
            )
        return await tool_handler(call, context)

    model = two_write_steps_model()
    runtime, handle, loop, _ = await setup_loop(
        model,
        handlers={"read_value": tool_handler, "write_value": first_call_outcome_unknown},
    )

    awaiting_first = await loop.execute(handle.run_id, CONTEXT)
    await reply_pending_interaction(
        runtime, handle, awaiting_first, "approve_once", "approve_1"
    )
    unknown = await loop.resume(handle.run_id, CONTEXT)
    interaction = await reply_pending_interaction(
        runtime, handle, unknown, decision, "resolve_1"
    )
    awaiting_second = await loop.resume(handle.run_id, CONTEXT)

    assert unknown.state == RunState.SUSPENDED
    assert interaction.allowed_decisions == ("confirm_succeeded", "mark_failed", "cancel")
    assert awaiting_second.state == RunState.SUSPENDED

    await reply_pending_interaction(
        runtime, handle, awaiting_second, "approve_once", "approve_2"
    )
    result = await loop.resume(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    types = [event.type for event in events]
    persisted = persisted_tool_result(events, "call_1")
    tool_message = next(
        message
        for message in model.requests[1].messages
        if message.role == "tool" and message.tool_call_id == "call_1"
    )

    assert result.state == RunState.COMPLETED
    assert dispatches == ["call_1", "call_2"]
    assert types.count("tool.call.unknown") == 1
    assert ("tool.call.cancelled" if decision == "cancel" else "tool.call.reconciled") in types
    assert persisted.status == (
        ItemStatus.DECLINED if decision == "cancel" else ItemStatus.FAILED
    )
    assert persisted.data.error is not None
    assert persisted.data.error.code == "tool.outcome_manually_failed"
    assert tool_message.content == persisted.data.content
    assert tool_message.metadata["manually_confirmed"] is True


@pytest.mark.asyncio
async def test_authoritative_tool_error_content_is_persisted_and_resumable():
    """带 tool_result_received 的失败：模型看到的内容与落盘 Item 一致，之后仍可 resume。"""

    class RejectedWriteExecutor:
        async def execute(self, call, context):
            del context
            return ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text="remote rejected the write: quota exceeded"),),
                error=RuntimeErrorInfo(
                    code="remote.write_rejected",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message="write rejected",
                    safe_to_resume=True,
                    metadata={"tool_result_received": True},
                ),
                metadata={"tool_result_received": True},
            )

    model = two_write_steps_model()
    runtime, handle, loop, _ = await setup_loop(model, tools=(WRITE_TOOL,))
    loop.tool_executor = RejectedWriteExecutor()

    awaiting_first = await loop.execute(handle.run_id, CONTEXT)
    await reply_pending_interaction(
        runtime, handle, awaiting_first, "approve_once", "approve_1"
    )
    awaiting_second = await loop.resume(handle.run_id, CONTEXT)
    assert awaiting_second.state == RunState.SUSPENDED
    await reply_pending_interaction(
        runtime, handle, awaiting_second, "approve_once", "approve_2"
    )
    result = await loop.resume(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    types = [event.type for event in events]
    persisted = persisted_tool_result(events, "call_1")
    tool_message = next(
        message
        for message in model.requests[1].messages
        if message.role == "tool" and message.tool_call_id == "call_1"
    )

    assert result.state == RunState.COMPLETED
    assert types.count("tool.call.failed") == 2
    assert "tool.call.unknown" not in types
    assert persisted.status == ItemStatus.FAILED
    assert persisted.data.content[0].text == "remote rejected the write: quota exceeded"
    assert persisted.data.error is not None
    assert persisted.data.error.message_key == "error.provider_permanent"
    assert tool_message.content == persisted.data.content


@pytest.mark.asyncio
async def test_write_failure_marked_not_applied_is_a_known_failure():
    """写工具的错误若带 side_effect_state=not_applied，就是普通失败，不进人工核对。"""

    async def denied_before_write(call, context):
        del call, context
        raise SageV2Error(
            RuntimeErrorInfo(
                code="sandbox.permission_denied",
                category=ErrorCategory.POLICY_DENIED,
                message="path is outside the workspace",
                safe_to_resume=True,
                metadata={"side_effect_state": "not_applied"},
            )
        )

    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(completed("", calls=(tool_call("write_value"),)),)),
            ScriptedModelStep(events=(completed("handled"),)),
        )
    )
    runtime, handle, loop, _ = await setup_loop(
        model, handlers={"read_value": tool_handler, "write_value": denied_before_write}
    )
    loop.tool_policy = DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)

    result = await loop.execute(handle.run_id, CONTEXT)
    events = await runtime.session_store.read_events(handle.run_id)
    types = [event.type for event in events]
    failed = next(event for event in events if event.type == "tool.call.failed")

    assert result.state == RunState.COMPLETED
    assert "tool.call.unknown" not in types
    assert "interaction.requested" not in types
    assert failed.data.error.code == "sandbox.permission_denied"
    assert failed.data.error.metadata["side_effect_state"] == "not_applied"
