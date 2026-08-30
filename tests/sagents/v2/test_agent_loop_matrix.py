from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.agent.engine import AgentLoopEngine
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
from sagents.v2.tool.selection import (
    HybridToolSelectionPolicy,
    RecentToolSelectionPolicy,
)
from sagents.v2.agent.policy.continuation import (
    ContinuationAction,
    ContinuationDecision,
    ContinuationSignals,
    InteractionDraft,
)
from sagents.v2.agent.policy.judge import (
    LLMContinuationJudge,
    LLMJudgeContinuationPolicy,
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
from sagents.v2.testing.runtime import ephemeral_runtime


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
    loop = AgentLoopEngine(**loop_kwargs)
    return runtime, handle, loop, executor


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
    policy = HybridToolSelectionPolicy(
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
