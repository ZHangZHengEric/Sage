"""Time anchors belong to the original message, including legacy Runs."""
from datetime import datetime, timezone

import pytest

from sagents.v2.agent.engine import AgentLoopEngine
from sagents.v2.context import DefaultContextAssembler, RunMetadataContextProvider
from sagents.v2.context.contracts import ContextBudget, ContextReductionScope
from sagents.v2.context.message_time import FROZEN_TIME_KEY, frozen_time_context
from sagents.v2.context.plugins._shared.progress_summary import extract_snapshot
from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
from sagents.v2.context.plugins.summary_ephemeral import InMemoryConversationSummaryStore
from sagents.v2.context.plugins.summary_only import SummaryOnlyContextReducer
from sagents.v2.context.summary import SummarizationRequest, create_summary, message_digest
from sagents.v2.contracts.commands import RunConfig
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage, ScriptedModelProvider
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from tests.sagents.v2.test_session_history_context_matrix import CONTEXT, command, completed, execute


@pytest.mark.parametrize("old,now,tz", [
    ("2026-11-15T22:27:24.984660+08:00, Sunday", "2026-11-18T23:19:05.713491+08:00, Wednesday", "Asia/Shanghai"),
    ("2026-11-15T23:59:59+08:00", "2026-11-16T00:00:01+08:00", "Asia/Shanghai"),
    ("2026-11-18T09:00:00+08:00", "2026-11-18T23:19:05+08:00", "Asia/Shanghai"),
    ("2026-11-15T23:30:00-05:00", "2026-11-18T23:19:05+08:00", "America/New_York"),
])
async def test_legacy_times_are_recovered_for_inference_without_changing_ledger(tmp_path, old, now, tz):
    source = command("明天带孩子去医院", "original").model_copy(update={"config": RunConfig(metadata={
        "server_v2.external.run_id": "original",
        "system_context": {"current_time": old, "current_timezone": tz,
                           "todo_list": "old-todo", "working_directory": "old-directory", "other": "old-value"},
    })})
    store = FilesystemSessionStore(tmp_path)
    runtime = HarnessRuntime(store)
    first = await runtime.start_run(source, CONTEXT)
    await execute(runtime, first, ScriptedModelProvider((ScriptedModelStep(events=(completed("noted"),)),)))
    await store.close()

    store = FilesystemSessionStore(tmp_path)
    try:
        runtime = HarnessRuntime(store)
        current = command("晚上好", "current", session_id=first.session_id).model_copy(update={
            "config": RunConfig(metadata={"system_context": {
                "current_time": now, "current_timezone": "Asia/Shanghai", "other": "current-value"},
                "response_language": "zh"})})
        second = await runtime.start_run(current, CONTEXT)
        assembler = DefaultContextAssembler(history_reader=store, providers=(RunMetadataContextProvider(),))
        ledger = await assembler.initial_ledger(current, run_id=second.run_id)
        digest = AgentLoopEngine._ledger_digest(ledger)
        rebuilt = await assembler.history.rebuild(current, run_id=second.run_id)
        assert digest == AgentLoopEngine._ledger_digest(rebuilt)
        for _ in range(2):
            messages = await assembler.prepare_messages(current, ledger, run_id=second.run_id)
            users = [message for message in messages if message.role == "user"]
            assert old in str(users[0].content) and tz in str(users[0].content)
            assert now not in str(users[0].content)
            assert not any(value in str(users[0].content) for value in ("old-todo", "old-directory", "old-value", "current-value"))
            assert now in str(users[-1].content) and "current-value" in str(users[-1].content)
        assert AgentLoopEngine._ledger_digest(ledger) == digest
        assert (await store.get_start_command(first.run_id)).input[0].metadata == {}
    finally:
        await store.close()


async def test_missing_legacy_clock_uses_original_acceptance_in_its_timezone(tmp_path):
    accepted = datetime(2026, 11, 15, 15, 59, tzinfo=timezone.utc)
    store = FilesystemSessionStore(tmp_path, clock=lambda: accepted)
    try:
        runtime = HarnessRuntime(store)
        original = command("明天去医院", "original").model_copy(update={"config": RunConfig(metadata={
            "server_v2.external.run_id": "original", "system_context": {"current_timezone": "Asia/Tokyo"}})})
        first = await runtime.start_run(original, CONTEXT)
        await execute(runtime, first, ScriptedModelProvider((ScriptedModelStep(events=(completed("noted"),)),)))
        current = command("晚上好", "later", session_id=first.session_id)
        second = await runtime.start_run(current, CONTEXT)
        assembler = DefaultContextAssembler(history_reader=store, providers=(RunMetadataContextProvider(),))
        view = await assembler.prepare_messages(current,
            await assembler.initial_ledger(current, run_id=second.run_id), run_id=second.run_id)
        historical = next(message for message in view if message.role == "user")
        assert "2026-11-16T00:59:00+09:00" in str(historical.content)
        assert "Asia/Tokyo" in str(historical.content)
    finally:
        await store.close()


async def test_compression_preserves_time_and_invalidates_an_undated_summary():
    source_time = "2026-11-15T22:27:24.984660+08:00, Sunday"
    frozen = frozen_time_context({"system_context": {"current_time": source_time, "current_timezone": "Asia/Shanghai"}})
    old = ModelMessage(role="user", content=(TextBlock(text="明天带孩子去医院。" + "原始背景。" * 120),))
    answer = ModelMessage(role="assistant", content=(TextBlock(text="收到。" * 100),))
    latest = ModelMessage(role="user", content=(TextBlock(text="晚上好"),))
    scope = ContextReductionScope(context_key="dated", session_id="dated", run_id="later", source_sequence=10)
    store = InMemoryConversationSummaryStore()
    previous = create_summary(scope=scope, covered_messages=(old, answer),
                              covered_digests=(message_digest(old), message_digest(answer)),
                              text="孩子明天还要去医院", previous=None)
    await store.save(previous, expected_revision=None)
    dated = old.model_copy(update={"metadata": {FROZEN_TIME_KEY: frozen}})
    canonical = (dated, answer, latest)
    request = SummarizationRequest(scope=scope, messages=(dated, answer), target_tokens=400)
    # Both model and extractive summarization receive time-only context.
    source = ModelConversationSummarizer(ScriptedModelProvider(()))._source(request)
    assert source_time in source and "Asia/Shanghai" in source
    extractive = await extract_snapshot(request)
    assert source_time in extractive and "Asia/Shanghai" in extractive
    reducer = SummaryOnlyContextReducer(store, protected_recent_units=1)
    projection = await reducer.reduce(canonical, ContextBudget(max_input_tokens=10000, max_messages=2),
        scope=scope.model_copy(update={"canonical_messages": canonical, "canonical_indices": (0, 1, 2)}))
    assert projection.strategy == "persistent_summary"
    assert source_time in str(projection.messages) and "Asia/Shanghai" in str(projection.messages)
    saved = await store.get("dated", session_id="dated")
    assert saved.revision == previous.revision + 1
    assert source_time in saved.text


async def test_time_only_projection_discards_other_historical_runtime_keys():
    from sagents.v2.context.message_time import historical_time_context

    original = ModelMessage(role="user", content=(TextBlock(text=(
        "<runtime_context><system_context>"
        "<current_time>2026-11-15T22:27:24+08:00</current_time>"
        "<current_timezone>Asia/Shanghai</current_timezone>"
        "<session_id>old-session</session_id><todo_list>old-plan</todo_list>"
        "<working_directory>/workspace/old</working_directory>"
        "<project>old-project</project></system_context></runtime_context>"
        "<user_request>明天去医院</user_request>"
    )),))
    assembler = DefaultContextAssembler()
    prepared = await assembler.prepare_messages(command("晚上好", "new"), (
        original, ModelMessage(role="user", content=(TextBlock(text="晚上好"),)),
    ))
    historical = prepared[0]
    assert historical_time_context(historical) == (
        "<current_time>2026-11-15T22:27:24+08:00</current_time>\n"
        "<current_timezone>Asia/Shanghai</current_timezone>"
    )
    assert "明天去医院" in str(historical.content)
    assert not any(key in str(historical.content)
                   for key in ("session_id", "todo_list", "working_directory", "project"))


async def test_legacy_run_resumes_from_original_checkpoint_with_dated_history(tmp_path):
    from sagents.v2.agent.policy import ApprovalStrategy, DefaultToolPolicy
    from sagents.v2.contracts.commands import ReplyInteraction
    from sagents.v2.model import ModelToolCall
    from sagents.v2.tool import (
        InMemoryToolCatalog, InMemoryToolExecutor, SideEffectLevel, ToolDefinition, ToolExecutionResult,
    )

    old_time = "2026-11-15T22:27:24+08:00"
    current_time = "2026-11-18T23:19:05+08:00"
    definition = ToolDefinition(name="check", description="Check", input_schema={"type": "object"},
                                side_effect_level=SideEffectLevel.READ)

    async def check(call, context):
        return ToolExecutionResult(tool_call_id=call.tool_call_id, content=(TextBlock(text="checked"),))

    def loop(runtime, model):
        return AgentLoopEngine(runtime=runtime, model=model,
            tool_catalog=InMemoryToolCatalog((definition,)),
            tool_executor=InMemoryToolExecutor({"check": definition}, {"check": check}),
            tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.ALWAYS_ASK),
            context_assembler=DefaultContextAssembler(
                history_reader=runtime.session_store, providers=(RunMetadataContextProvider(),)))

    store = FilesystemSessionStore(tmp_path)
    try:
        runtime = HarnessRuntime(store)
        original = command("明天去医院", "original").model_copy(update={"config": RunConfig(metadata={
            "server_v2.external.run_id": "original", "system_context": {
                "current_time": old_time, "current_timezone": "Asia/Shanghai"}})})
        first = await runtime.start_run(original, CONTEXT)
        await execute(runtime, first, ScriptedModelProvider((ScriptedModelStep(events=(completed("noted"),)),)))
        current = command("晚上好", "later", session_id=first.session_id).model_copy(update={"config": RunConfig(
            metadata={"server_v2.external.run_id": "later", "system_context": {
                "current_time": current_time, "current_timezone": "Asia/Shanghai"}})})
        second = await runtime.start_run(current, CONTEXT)
        model = ScriptedModelProvider((ScriptedModelStep(events=(completed(calls=(
            ModelToolCall(tool_call_id="check-one", name="check", arguments={}),)),)),))
        suspended = await loop(runtime, model).execute(second.run_id, CONTEXT)
        assert suspended.state.value == "suspended"
    finally:
        await store.close()

    store = FilesystemSessionStore(tmp_path)
    try:
        runtime = HarnessRuntime(store)
        suspension = await store.get_suspension(suspended.suspension_id)
        interaction = await store.get_interaction(suspension.interaction_id)
        await runtime.reply_interaction(ReplyInteraction(
            run_id=second.run_id, suspension_id=suspension.suspension_id,
            interaction_id=interaction.interaction_id, expected_revision=suspended.revision,
            expected_suspension_revision=suspension.expected_revision,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve_once", idempotency_key="approve-check",
        ), CONTEXT)
        model = ScriptedModelProvider((ScriptedModelStep(events=(completed("Done"),)),))
        result = await loop(runtime, model).resume(second.run_id, CONTEXT)
        assert result.state.value == "completed"
        users = [message for message in model.requests[0].messages if message.role == "user"]
        assert old_time in str(users[0].content)
        assert current_time not in str(users[0].content)
        assert current_time in str(users[-1].content)
        assert (await store.get_start_command(first.run_id)).input[0].metadata == {}
    finally:
        await store.close()
