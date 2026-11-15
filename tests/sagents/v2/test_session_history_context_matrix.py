from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.contracts import DerivedStateStore, SessionStore
    from sagents.v2.tool.official.runtime import OfficialToolRuntime

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.context import DefaultContextAssembler, InMemoryConversationSummaryStore, RunMetadataContextProvider, SummaryOnlyContextReducer
from sagents.v2.context.plugins.run_history_window import RecentRunHistoryWindow
from sagents.v2.context.plugins.summary_session import SessionDerivedConversationSummaryStore
from sagents.v2.contracts.commands import CancelRun, InputItem, ReplyInteraction, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.events import ContinuationEventData
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposalStatus,
    SessionMergeStrategy,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.model import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ScriptedModelProvider,
)
from sagents.v2.session_memory.plugins.sqlite_bm25 import SqliteBm25SessionMemoryProvider
from sagents.v2.session_memory.service import SessionMemoryService
from sagents.v2.tool.decorated import DecoratedToolProvider
from sagents.v2.tool.official.memory import MemoryTools
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.runtime.session import EventDraft, FilesystemSessionStore


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


def command(
    text: str,
    key: str,
    *,
    session_id: str | None = None,
    mode: SessionConcurrencyMode = SessionConcurrencyMode.SERIAL,
    base_revision: int | None = None,
) -> StartRun:
    return StartRun(
        session_id=session_id,
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text=text),)),),
        session_concurrency_mode=mode,
        base_session_revision=base_revision,
        resolved_spec_hash="sha256:agent",
        idempotency_key=key,
    )


def completed(
    text: str = "",
    *,
    calls: tuple[ModelToolCall, ...] = (),
    provider_state: dict | None = None,
):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="response_1",
            text=text,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else "stop",
            provider_state=provider_state or {},
        ),
    )


def message_texts(request) -> list[tuple[str, str]]:
    return [
        (
            message.role,
            "\n".join(
                block.text for block in message.content if isinstance(block, TextBlock)
            ),
        )
        for message in request.messages
    ]


async def execute(runtime, handle, model, *, definitions=(), handlers=None):
    definitions = tuple(definitions)
    catalog = InMemoryToolCatalog(definitions)
    executor = InMemoryToolExecutor(
        {value.name: value for value in definitions}, handlers or {}
    )
    return await AgentLoopEngine(
        runtime=runtime,
        model=model,
        tool_catalog=catalog,
        tool_executor=executor,
    ).execute(handle.run_id, CONTEXT)


@pytest.mark.asyncio
async def test_user_cancel_without_tool_reply_allows_next_turn_after_restart(tmp_path):
    from sagents.v2.context.session_history import SessionEventModelProjector

    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(cast('SessionStore', store))
    first = await runtime.start_run(command("start tool", "cancel-first"), CONTEXT)
    started = asyncio.Event()
    definition = ToolDefinition(
        name="save_value", description="Save a value", input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
    )

    async def no_reply(call, context):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(execute(
        runtime, first,
        ScriptedModelProvider((ScriptedModelStep(events=(completed(calls=(
            ModelToolCall(tool_call_id="cancelled-call", name="save_value", arguments={}),
        )),)),)),
        definitions=(definition,), handlers={"save_value": no_reply},
    ))
    try:
        await asyncio.wait_for(started.wait(), 5)
        run = await runtime.get_run(first.run_id)
        receipt = await runtime.cancel_run(CancelRun(
            run_id=run.run_id, expected_revision=run.revision,
            idempotency_key="user-cancel", reason="user_cancelled",
        ), CONTEXT)
        assert receipt.decision.value == "accepted"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await store.close()

    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(cast('SessionStore', store))
    try:
        assert (await runtime.get_run(first.run_id)).state.value == "cancelled"
        assert await store.list_dispatchable_runs() == ()
        events = await store.read_events(first.run_id)
        projected = SessionEventModelProjector().project(events)
        missing = [m for m in projected if m.role == "tool" and m.tool_call_id == "cancelled-call"]
        assert len(missing) == 1
        assert missing[0].metadata["tool_result_received"] is False
        assert missing[0].metadata["execution_outcome"] == "unknown"
        # Active/suspended histories must keep their original recovery semantics.
        active_history = SessionEventModelProjector().project(tuple(
            event for event in events if event.type != "run.cancelled"
        ))
        assert not any(m.metadata.get("synthetic") for m in active_history)
        # A real result, including one recorded late, always takes precedence.
        from sagents.v2.contracts.items import ToolCallItemData, ToolResultItemData
        call_event = next(event for event in events if getattr(event.data, "item", None)
                          and isinstance(event.data.item.data, ToolCallItemData))
        late_result = call_event.model_copy(update={"data": call_event.data.model_copy(update={
            "item": call_event.data.item.model_copy(update={
                "item_id": "late-result", "data": ToolResultItemData(
                    tool_call_id="cancelled-call", content=(TextBlock(text="actual result"),),
                    metadata={"tool_result_received": True},
                ),
            }),
        })})
        received = [m for m in SessionEventModelProjector().project((*events, late_result)) if m.role == "tool"]
        assert len(received) == 1
        assert cast(TextBlock, received[0].content[0]).text == "actual result"
        assert received[0].metadata["tool_result_received"] is True
        second = await runtime.start_run(
            command("new question", "after-cancel", session_id=first.session_id), CONTEXT,
        )
        provider = ScriptedModelProvider((ScriptedModelStep(events=(completed("new answer"),)),))
        result = await execute(runtime, second, provider)
        assert result.state.value == "completed"
        assert any(m.tool_call_id == "cancelled-call" for m in provider.requests[0].messages if m.role == "tool")
        assert cast(TextBlock, provider.requests[0].messages[-1].content[0]).text == "new question"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_serial_run_projects_completed_history_from_previous_runs():
    runtime = ephemeral_runtime()
    first = await runtime.start_run(command("first question", "first"), CONTEXT)
    await execute(
        runtime,
        first,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("first answer"),)),)
        ),
    )

    second = await runtime.start_run(
        command("follow up", "second", session_id=first.session_id), CONTEXT
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("second answer"),)),)
    )
    await execute(runtime, second, model)

    assert message_texts(model.requests[0]) == [
        ("user", "first question"),
        ("assistant", "first answer"),
        ("user", "follow up"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("limits", [
    {"max_turns": 1},
    {"max_age_seconds": 60},
    {"max_age_seconds": 600, "max_turns": 1},
    {"max_age_seconds": 60, "max_turns": 2},
])
@pytest.mark.parametrize("mode", [
    SessionConcurrencyMode.SERIAL,
    SessionConcurrencyMode.FORK,
    SessionConcurrencyMode.SNAPSHOT_ISOLATED,
])
async def test_run_history_window_preserves_prefix_search_and_overflow_recovery(tmp_path, limits, mode):
    now = datetime.now(timezone.utc)
    runtime = ephemeral_runtime(clock=lambda: now)
    old_text = "The original release codename was Saturn."
    trusted_instruction = "Apply the permanent Heliotrope rule."
    old_command = command(old_text, "old")
    old = await runtime.start_run(old_command.model_copy(update={"input": (
        *old_command.input,
        InputItem(role="developer", content=(TextBlock(text=trusted_instruction),)),
    )}), CONTEXT.model_copy(update={"actor": CONTEXT.actor.model_copy(update={
        "scopes": ("session.trusted_input",),
    })}))
    await execute(runtime, old, ScriptedModelProvider((ScriptedModelStep(events=(completed("Noted."),)),)))
    now += timedelta(minutes=10)
    recent_text = ("Keep the following recent discussion in context. " * 20).strip()
    recent_command = command(recent_text, "recent", session_id=old.session_id)
    recent = await runtime.start_run(recent_command.model_copy(update={"input": (
        *recent_command.input,
        InputItem(role="user", content=(TextBlock(text="Another input in the same Turn."),)),
    )}), CONTEXT)
    await execute(runtime, recent, ScriptedModelProvider((ScriptedModelStep(events=(completed("Understood."),)),)))
    current_text = "What was the release codename?"
    current = await runtime.start_run(
        command(current_text, "current", session_id=old.session_id, mode=mode), CONTEXT,
    )
    now += timedelta(minutes=10)

    summary_requests = []

    class Summarizer:
        async def summarize(self, request):
            summary_requests.append(request)
            return "A recent discussion was retained."

    memory = SessionMemoryService(SqliteBm25SessionMemoryProvider(tmp_path))
    summary_store = InMemoryConversationSummaryStore()

    def assembler():
        return DefaultContextAssembler(
            history_reader=runtime.session_store,
            history_window=RecentRunHistoryWindow(**limits),
            projection_observer=memory,
            reducer=SummaryOnlyContextReducer(summary_store, summarizer=Summarizer(), protected_recent_units=1),
        )

    tool = DecoratedToolProvider(MemoryTools(cast("OfficialToolRuntime", SimpleNamespace(
        session_memory_service=memory,
    ))))
    search_call = ModelToolCall(tool_call_id="find-old", name="search_memory", arguments={"query": "Saturn"})
    model = ScriptedModelProvider((
        ScriptedModelStep(events=(completed(calls=(search_call,)),)),
        ScriptedModelStep(events=(), error=RuntimeErrorInfo(
            code="model.context_window_exceeded", message="request too long", category=ErrorCategory.VALIDATION,
        )),
        ScriptedModelStep(events=(completed("Saturn."),)),
    ))
    result = await AgentLoopEngine(
        runtime=runtime, model=model, tool_catalog=tool.catalog,
        tool_executor=tool.executor, context_assembler=assembler(),
    ).execute(current.run_id, CONTEXT)

    assert result.state.value == "completed"
    first, second, recovered = model.requests
    assert message_texts(first) == [
        ("developer", trusted_instruction),
        ("user", recent_text), ("user", "Another input in the same Turn."),
        ("assistant", "Understood."), ("user", current_text),
    ]
    assert second.messages[:len(first.messages)] == first.messages
    search_result = next(message for message in second.messages if message.role == "tool")
    assert search_result.content[0].model_dump()["value"]["session_results"][0]["content"] == old_text
    assert len(summary_requests) == 1
    assert old_text not in str(summary_requests[0].messages)
    assert ("developer", trusted_instruction) in message_texts(recovered)
    assert any(text == current_text for _, text in message_texts(recovered))
    assert any("A recent discussion was retained." in text for _, text in message_texts(recovered))

    rebuilt = assembler()
    stored_command = await runtime.session_store.get_start_command(current.run_id)
    assert rebuilt.history is not None
    ledger = await rebuilt.history.rebuild(stored_command, run_id=current.run_id)
    projection = await rebuilt.prepare_projection(stored_command, ledger, run_id=current.run_id)
    assert ledger[0].content[0] == TextBlock(text=old_text)
    assert projection.historical_messages[0] == ledger[0]
    assert all(message.role != "developer" for message in projection.historical_messages)
    assert not await memory.recall(
        run_id=current.run_id, session_id=result.session_id, text="Heliotrope", limit=5,
    )
    assert not await memory.recall(
        run_id=current.run_id, session_id="unrelated-session", text="Saturn", limit=5,
    )
    assert len(summary_requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("index_unavailable", [False, True])
async def test_window_indexes_history_before_automatic_recall(tmp_path, monkeypatch, index_unavailable):
    runtime = ephemeral_runtime()
    old_text = "The Saturn codename."
    seed_model = ScriptedModelProvider((
        ScriptedModelStep(events=(completed("Noted."),)),
        ScriptedModelStep(events=(completed("Good morning."),)),
    ))
    old = await runtime.start_run(command(old_text, "old"), CONTEXT)
    await execute(runtime, old, seed_model)
    recent = await runtime.start_run(command("Hello", "recent", session_id=old.session_id), CONTEXT)
    await execute(runtime, recent, seed_model)
    current = await runtime.start_run(command("Saturn", "current", session_id=old.session_id), CONTEXT)

    provider = SqliteBm25SessionMemoryProvider(tmp_path)
    if index_unavailable:
        async def unavailable(_records):
            raise OSError("test history index unavailable")

        monkeypatch.setattr(provider, "sync", unavailable)

    memory = SessionMemoryService(provider)
    tool = DecoratedToolProvider(MemoryTools(cast("OfficialToolRuntime", SimpleNamespace(
        session_memory_service=memory,
    ))))
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("Done."),)),))
    result = await AgentLoopEngine(
        runtime=runtime, model=model, tool_catalog=tool.catalog, tool_executor=tool.executor,
        automatic_memory_recall=True,
        context_assembler=DefaultContextAssembler(
            history_reader=runtime.session_store,
            history_window=RecentRunHistoryWindow(max_turns=1),
            projection_observer=memory,
        ),
    ).execute(current.run_id, CONTEXT)

    if index_unavailable:
        assert result.state.value == "failed"
        error = (await runtime.get_run_result(current.run_id)).error
        assert error is not None and error.code == "loop.preparation_failed"
        assert not model.requests
        return

    assert result.state.value == "completed"
    request = model.requests[0]
    assert all(old_text not in text for role, text in message_texts(request) if role == "user")
    result_message = next(message for message in request.messages if message.role == "tool")
    assert old_text in str(result_message.content)


@pytest.mark.asyncio
@pytest.mark.parametrize("summarized", [False, True])
async def test_approved_history_search_restores_boundary_after_reopening_store(tmp_path, summarized):
    summary_calls = []

    class Summarizer:
        async def summarize(self, request):
            summary_calls.append(request)
            return "The recent exchange recorded a second reference."

    def make_loop(runtime, model):
        memory = SessionMemoryService(SqliteBm25SessionMemoryProvider(tmp_path / "memory"))
        tool = DecoratedToolProvider(MemoryTools(cast("OfficialToolRuntime", SimpleNamespace(
            session_memory_service=memory,
        ))))
        return AgentLoopEngine(
            runtime=runtime, model=model, tool_catalog=tool.catalog, tool_executor=tool.executor,
            tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.ALWAYS_ASK),
            context_assembler=DefaultContextAssembler(
                history_reader=runtime.session_store,
                history_window=RecentRunHistoryWindow(max_turns=1), projection_observer=memory,
                reducer=SummaryOnlyContextReducer(
                    SessionDerivedConversationSummaryStore(cast("DerivedStateStore", runtime.session_store)),
                    summarizer=Summarizer(), protected_recent_units=1,
                ),
            ),
        )

    old_text = "The codename on file is Saturn."
    second_reference = "Saturn also has a second reference."
    recent_text = second_reference + " Supporting detail follows." * 50
    store = FilesystemSessionStore(tmp_path / "sessions")
    try:
        runtime = HarnessRuntime(cast("SessionStore", store))
        seed = ScriptedModelProvider((
            ScriptedModelStep(events=(completed("Noted."),)),
            ScriptedModelStep(events=(completed("Hello!"),)),
        ))
        old = await runtime.start_run(command(old_text, "old"), CONTEXT)
        await execute(runtime, old, seed)
        recent = await runtime.start_run(command(recent_text, "recent", session_id=old.session_id), CONTEXT)
        await execute(runtime, recent, seed)
        handle = await runtime.start_run(command("Find the old codename", "find", session_id=old.session_id), CONTEXT)
        lookup = ModelToolCall(tool_call_id="find-old", name="search_memory", arguments={"query": "Saturn"})
        model = ScriptedModelProvider((ScriptedModelStep(events=(completed(calls=(lookup,)),)),))
        loop = make_loop(runtime, model)
        if summarized:
            cast(DefaultContextAssembler, loop.context_assembler).request_compression(handle.run_id)
        run = await loop.execute(handle.run_id, CONTEXT)
        assert run.state.value == "suspended"
        assert old_text not in str(model.requests[0].messages)
    finally:
        await store.close()

    store = FilesystemSessionStore(tmp_path / "sessions")
    try:
        runtime = HarnessRuntime(cast("SessionStore", store))
        assert run.suspension_id is not None
        suspension = await store.get_suspension(run.suspension_id)
        assert suspension.interaction_id is not None
        interaction = await store.get_interaction(suspension.interaction_id)
        reply = await runtime.reply_interaction(ReplyInteraction(
            run_id=run.run_id, suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id, expected_revision=run.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve_once", idempotency_key="allow-search",
        ), CONTEXT)
        assert reply.decision.value == "accepted"
        model = ScriptedModelProvider((ScriptedModelStep(events=(completed("Done."),)),))
        result = await make_loop(runtime, model).resume(run.run_id, CONTEXT)
        assert result.state.value == "completed"
        result_message = next(message for message in model.requests[0].messages if message.role == "tool")
        assert old_text in str(result_message.content)
        assert (second_reference in str(result_message.content)) == summarized
        assert len(summary_calls) == int(summarized)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_explicit_continuation_keeps_expired_original_request():
    now = datetime.now(timezone.utc)
    runtime = ephemeral_runtime(clock=lambda: now)
    source = await runtime.start_run(command("Original task brief", "original"), CONTEXT)
    original = await runtime.get_run(source.run_id)
    await runtime.cancel_run(CancelRun(
        run_id=source.run_id, expected_revision=original.revision,
        idempotency_key="cancel-original", reason="user_cancelled",
    ), CONTEXT)
    now += timedelta(minutes=5)

    request = StartRun(
        session_id=source.session_id, agent_id="agent_1", input=(),
        resolved_spec_hash="sha256:agent", idempotency_key="continue-original",
        continuation_of_run_id=source.run_id, continuation_instruction="Finish the last scene.",
    )
    handle = await runtime.start_run(request, CONTEXT)
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("Done."),)),))
    result = await AgentLoopEngine(
        runtime=runtime, model=model, tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}),
        context_assembler=DefaultContextAssembler(
            history_reader=runtime.session_store, providers=(RunMetadataContextProvider(),),
            history_window=RecentRunHistoryWindow(max_age_seconds=60),
        ),
    ).execute(handle.run_id, CONTEXT)
    assert result.state.value == "completed"
    user_text = next(text for role, text in message_texts(model.requests[0]) if role == "user")
    assert "Original task brief" in user_text
    assert "Finish the last scene." in user_text


@pytest.mark.asyncio
async def test_time_window_expires_history_that_contains_only_a_questionnaire():
    now = datetime.now(timezone.utc)
    runtime = ephemeral_runtime(clock=lambda: now)
    store = runtime.session_store
    old_command = command("", "old").model_copy(update={"input": ()})
    old = await runtime.start_run(old_command, CONTEXT)
    original = await store.get_run(old.run_id)
    await store.commit_run(
        run_id=old.run_id, context=CONTEXT, expected_revision=original.revision,
        expected_states={RunState.QUEUED}, new_state=RunState.CANCELLED,
        drafts=(EventDraft(type="continuation.decided", data=ContinuationEventData(
            action="complete_run", reason_code="questionnaire", reason="test",
            decision_hash="sha256:test", details={"questionnaire": {"title": "Old question"}},
        )),), idempotency_key="record-questionnaire",
    )
    now += timedelta(minutes=5)
    request = command("Hello", "current", session_id=old.session_id)
    current = await runtime.start_run(request, CONTEXT)
    assembler = DefaultContextAssembler(
        history_reader=store, history_window=RecentRunHistoryWindow(max_age_seconds=60),
    )
    ledger = await assembler.initial_ledger(request, run_id=current.run_id)
    projection = await assembler.prepare_projection(request, ledger, run_id=current.run_id)
    assert "Old question" not in str(projection.messages)
    assert "Old question" in str(projection.historical_messages)


@pytest.mark.asyncio
async def test_provider_state_survives_tool_round_trip_and_session_rebuild():
    runtime = ephemeral_runtime()
    call = ModelToolCall(
        tool_call_id="call_reasoning",
        name="lookup",
        arguments={"q": "state"},
    )
    state = {
        "openai_compatible": {
            "reasoning_details": [{"type": "reasoning", "value": "opaque"}]
        }
    }
    definition = ToolDefinition(
        name="lookup",
        description="lookup",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.READ,
    )
    first = await runtime.start_run(command("first", "state-first"), CONTEXT)
    first_model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(completed(calls=(call,), provider_state=state),)
            ),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )

    async def lookup(tool_call, _context):
        return ToolExecutionResult(
            tool_call_id=tool_call.tool_call_id,
            operation_id=tool_call.operation_id,
            content=(TextBlock(text="result"),),
            metadata={
                "context_reference": {
                    "uri": "artifact://tool-result/call_reasoning"
                }
            },
        )

    await execute(
        runtime,
        first,
        first_model,
        definitions=(definition,),
        handlers={"lookup": lookup},
    )

    assert first_model.requests[1].messages[-2].provider_state == state
    assert first_model.requests[1].messages[-1].metadata[
        "context_reference"
    ]["uri"] == "artifact://tool-result/call_reasoning"
    second = await runtime.start_run(
        command("follow up", "state-second", session_id=first.session_id),
        CONTEXT,
    )
    second_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("again"),)),)
    )
    await execute(runtime, second, second_model)
    replayed = next(
        message
        for message in second_model.requests[0].messages
        if message.tool_calls
        and message.tool_calls[0].tool_call_id == "call_reasoning"
    )
    assert replayed.provider_state == state
    replayed_tool = next(
        message
        for message in second_model.requests[0].messages
        if message.role == "tool" and message.tool_call_id == "call_reasoning"
    )
    assert replayed_tool.metadata["context_reference"]["uri"] == (
        "artifact://tool-result/call_reasoning"
    )


@pytest.mark.asyncio
async def test_fork_materializes_parent_history_at_its_stable_base_sequence():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(command("parent question", "parent"), CONTEXT)
    await execute(
        runtime,
        parent,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("parent answer"),)),)
        ),
    )
    parent_snapshot = await runtime.session_store.get_session(parent.session_id)

    child = await runtime.start_run(
        command(
            "delegated question",
            "child",
            session_id=parent.session_id,
            mode=SessionConcurrencyMode.FORK,
        ),
        CONTEXT,
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("child answer"),)),)
    )
    await execute(runtime, child, model)

    assert child.session_id != parent.session_id
    assert child.base_session_sequence == parent_snapshot.last_sequence
    assert message_texts(model.requests[0]) == [
        ("user", "parent question"),
        ("assistant", "parent answer"),
        ("user", "delegated question"),
    ]

    late_parent = await runtime.start_run(command(
        "late parent data", "parent-after-fork", session_id=parent.session_id,
    ), CONTEXT)
    await execute(runtime, late_parent, ScriptedModelProvider((
        ScriptedModelStep(events=(completed("Parent-only reply"),)),
    )))
    followup = command("Continue the child", "child-followup", session_id=child.session_id)
    second = await runtime.start_run(followup, CONTEXT)
    assembler = DefaultContextAssembler(history_reader=runtime.session_store,
        history_window=RecentRunHistoryWindow(max_turns=1))
    ledger = await assembler.initial_ledger(followup, run_id=second.run_id)
    projection = await assembler.prepare_projection(followup, ledger, run_id=second.run_id)
    assert "child answer" in str(projection.messages)
    assert "late parent data" not in str(ledger)


@pytest.mark.asyncio
async def test_snapshot_reads_its_base_but_is_not_published_into_serial_history():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(command("seed question", "seed"), CONTEXT)
    await execute(
        runtime,
        seed,
        ScriptedModelProvider((ScriptedModelStep(events=(completed("seed answer"),)),)),
    )
    base = await runtime.session_store.get_session(seed.session_id)

    snapshot = await runtime.start_run(
        command(
            "private candidate",
            "snapshot",
            session_id=seed.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_revision=base.revision,
        ),
        CONTEXT,
    )
    snapshot_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("private answer"),)),)
    )
    await execute(runtime, snapshot, snapshot_model)

    serial = await runtime.start_run(
        command("public follow up", "serial", session_id=seed.session_id), CONTEXT
    )
    serial_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("public answer"),)),)
    )
    await execute(runtime, serial, serial_model)

    assert message_texts(snapshot_model.requests[0]) == [
        ("user", "seed question"),
        ("assistant", "seed answer"),
        ("user", "private candidate"),
    ]
    assert message_texts(serial_model.requests[0]) == [
        ("user", "seed question"),
        ("assistant", "seed answer"),
        ("user", "public follow up"),
    ]


@pytest.mark.asyncio
async def test_snapshot_publication_is_explicit_and_visible_only_after_publish_boundary():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(command("seed", "publish-seed"), CONTEXT)
    await execute(
        runtime,
        seed,
        ScriptedModelProvider((ScriptedModelStep(events=(completed("seed answer"),)),)),
    )
    base = await runtime.session_store.get_session(seed.session_id)
    snapshot = await runtime.start_run(
        command(
            "candidate",
            "publish-snapshot",
            session_id=seed.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_revision=base.revision,
        ),
        CONTEXT,
    )
    snapshot_run = await execute(
        runtime,
        snapshot,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("candidate answer"),)),)
        ),
    )
    proposal = await runtime.propose_session_commit(
        ProposeSessionCommit(
            run_id=snapshot.run_id,
            expected_run_revision=snapshot_run.revision,
            idempotency_key="propose",
        ),
        CONTEXT,
    )
    assert proposal.status == SessionCommitProposalStatus.PENDING
    assert proposal.conflicting_run_ids == ()

    # This Run fixes its history boundary before publication. Publishing later
    # must not retroactively change the ledger it executes from.
    accepted_before_publish = await runtime.start_run(
        command("already accepted", "before-publish", session_id=seed.session_id),
        CONTEXT,
    )
    session = await runtime.session_store.get_session(seed.session_id)
    published = await runtime.publish_session_commit(
        PublishSessionCommit(
            proposal_id=proposal.proposal_id,
            expected_proposal_revision=proposal.revision,
            expected_session_revision=session.revision,
            merge_strategy=SessionMergeStrategy.APPEND_AFTER_CURRENT,
            idempotency_key="publish",
        ),
        CONTEXT,
    )
    assert published.status == SessionCommitProposalStatus.PUBLISHED
    assert published.published_session_sequence is not None

    before_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("before answer"),)),)
    )
    await execute(runtime, accepted_before_publish, before_model)
    assert message_texts(before_model.requests[0]) == [
        ("user", "seed"),
        ("assistant", "seed answer"),
        ("user", "already accepted"),
    ]

    accepted_after_publish = await runtime.start_run(
        command("after publish", "after-publish", session_id=seed.session_id),
        CONTEXT,
    )
    after_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("after answer"),)),)
    )
    await execute(runtime, accepted_after_publish, after_model)
    assert message_texts(after_model.requests[0]) == [
        ("user", "seed"),
        ("assistant", "seed answer"),
        ("user", "candidate"),
        ("assistant", "candidate answer"),
        ("user", "already accepted"),
        ("assistant", "before answer"),
        ("user", "after publish"),
    ]


@pytest.mark.asyncio
async def test_snapshot_conflict_requires_explicit_append_or_can_be_rejected():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(command("seed", "conflict-seed"), CONTEXT)
    await execute(
        runtime,
        seed,
        ScriptedModelProvider((ScriptedModelStep(events=(completed("seed answer"),)),)),
    )
    base = await runtime.session_store.get_session(seed.session_id)
    snapshot = await runtime.start_run(
        command(
            "candidate",
            "conflict-snapshot",
            session_id=seed.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_revision=base.revision,
        ),
        CONTEXT,
    )
    snapshot_run = await execute(
        runtime,
        snapshot,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("candidate answer"),)),)
        ),
    )
    concurrent = await runtime.start_run(
        command("canonical change", "conflict-serial", session_id=seed.session_id),
        CONTEXT,
    )
    await execute(
        runtime,
        concurrent,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("canonical answer"),)),)
        ),
    )
    proposal = await runtime.propose_session_commit(
        ProposeSessionCommit(
            run_id=snapshot.run_id,
            expected_run_revision=snapshot_run.revision,
            idempotency_key="conflict-propose",
        ),
        CONTEXT,
    )
    assert proposal.conflicting_run_ids == (concurrent.run_id,)
    session = await runtime.session_store.get_session(seed.session_id)
    with pytest.raises(SageV2Error) as conflict:
        await runtime.publish_session_commit(
            PublishSessionCommit(
                proposal_id=proposal.proposal_id,
                expected_proposal_revision=proposal.revision,
                expected_session_revision=session.revision,
                idempotency_key="require-clean-base",
            ),
            CONTEXT,
        )
    assert conflict.value.info.code == "session.commit_merge_required"

    rejected = await runtime.reject_session_commit(
        RejectSessionCommit(
            proposal_id=proposal.proposal_id,
            expected_proposal_revision=proposal.revision,
            expected_session_revision=session.revision,
            idempotency_key="reject-conflict",
            reason="candidate is obsolete",
        ),
        CONTEXT,
    )
    assert rejected.status == SessionCommitProposalStatus.REJECTED
    assert rejected.rejection_reason == "candidate is obsolete"


@pytest.mark.asyncio
async def test_stale_snapshot_never_reads_events_committed_after_its_base():
    runtime = ephemeral_runtime()
    seed = await runtime.start_run(command("base question", "stale-seed"), CONTEXT)
    await execute(
        runtime,
        seed,
        ScriptedModelProvider((ScriptedModelStep(events=(completed("base answer"),)),)),
    )
    base = await runtime.session_store.get_session(seed.session_id)
    snapshot = await runtime.start_run(
        command(
            "candidate question",
            "stale-candidate",
            session_id=seed.session_id,
            mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
            base_revision=base.revision,
        ),
        CONTEXT,
    )

    later = await runtime.start_run(
        command("later question", "later", session_id=seed.session_id), CONTEXT
    )
    await execute(
        runtime,
        later,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("later answer"),)),)
        ),
    )
    snapshot_model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("candidate answer"),)),)
    )
    await execute(runtime, snapshot, snapshot_model)

    assert snapshot.base_session_sequence == base.last_sequence
    assert message_texts(snapshot_model.requests[0]) == [
        ("user", "base question"),
        ("assistant", "base answer"),
        ("user", "candidate question"),
    ]


@pytest.mark.asyncio
async def test_sqlite_restart_preserves_the_session_history_anchor(tmp_path):
    path = tmp_path / "runtime.sqlite3"
    repository = FilesystemSessionStore(path)
    runtime = HarnessRuntime(cast('SessionStore', repository))
    first = await runtime.start_run(command("before restart", "restart-first"), CONTEXT)
    await execute(
        runtime,
        first,
        ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("persisted answer"),)),)
        ),
    )
    await repository.close()

    reopened = FilesystemSessionStore(path)
    resumed_runtime = HarnessRuntime(cast('SessionStore', reopened))
    second = await resumed_runtime.start_run(
        command("after restart", "restart-second", session_id=first.session_id), CONTEXT
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("new answer"),)),)
    )
    await execute(resumed_runtime, second, model)

    assert message_texts(model.requests[0]) == [
        ("user", "before restart"),
        ("assistant", "persisted answer"),
        ("user", "after restart"),
    ]
    await reopened.close()


@pytest.mark.asyncio
async def test_tool_call_and_result_items_reconstruct_a_complete_provider_pair():
    runtime = ephemeral_runtime()
    definition = ToolDefinition(
        name="lookup",
        description="look up a value",
        input_schema={"type": "object", "properties": {}},
        side_effect_level=SideEffectLevel.READ,
    )

    async def lookup(call, context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="tool value"),),
        )

    first = await runtime.start_run(command("use the tool", "tool-first"), CONTEXT)
    call = ModelToolCall(tool_call_id="call_1", name="lookup", arguments={})
    await execute(
        runtime,
        first,
        ScriptedModelProvider(
            (
                ScriptedModelStep(events=(completed(calls=(call,)),)),
                ScriptedModelStep(events=(completed("final answer"),)),
            )
        ),
        definitions=(definition,),
        handlers={"lookup": lookup},
    )

    second = await runtime.start_run(
        command("continue", "tool-second", session_id=first.session_id), CONTEXT
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(completed("continued"),)),)
    )
    await execute(runtime, second, model)

    messages = model.requests[0].messages
    assert [message.role for message in messages] == [
        "user",
        "assistant",
        "tool",
        "assistant",
        "user",
    ]
    assert messages[1].tool_calls == (call,)
    assert messages[2].tool_call_id == "call_1"
    assert messages[2].content == (TextBlock(text="tool value"),)


@pytest.mark.asyncio
async def test_explicit_questionnaire_questions_reach_the_next_run():
    from sagents.v2.agent.policy.continuation import ContinuationSignals, InteractionDraft
    from sagents.v2.context.session_history import SessionEventModelProjector

    runtime = ephemeral_runtime()
    first = await runtime.start_run(command("Deploy the service", "ask-target"), CONTEXT)
    questionnaire = {"title": "Deployment target", "questions": [
        {"id": "target", "title": "Which target should receive the service?", "options": ["staging", "production"]},
    ]}
    model = ScriptedModelProvider((ScriptedModelStep(events=(completed("Choose a target."),)),))
    loop = AgentLoopEngine(
        runtime=runtime, model=model,
        tool_catalog=InMemoryToolCatalog(()), tool_executor=InMemoryToolExecutor({}, {}),
        continuation_signal_provider=lambda run_id: ContinuationSignals(interaction=InteractionDraft(
            interaction_type="questionnaire", allowed_decisions=("submit",), payload=questionnaire,
        )),
    )
    assert (await loop.execute(first.run_id, CONTEXT)).state.value == "completed"
    events = await runtime.session_store.read_events(first.run_id)
    history = SessionEventModelProjector().project(events)
    assert sum("Which target should receive" in block.text
               for message in history for block in message.content if isinstance(block, TextBlock)) == 1

    second = await runtime.start_run(command("staging", "answer-target", session_id=first.session_id), CONTEXT)
    def verify_context(request):
        texts = message_texts(request)
        assert any("Which target should receive the service?" in text and "production" in text for _, text in texts)
        assert any(role == "user" and text == "staging" for role, text in texts)
    await execute(runtime, second, ScriptedModelProvider((ScriptedModelStep(
        events=(completed("Deployed."),), assertion=verify_context,
    ),)))
