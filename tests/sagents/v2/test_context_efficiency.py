from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from sagents.v2.context import (
    ContextBudget,
    ContextReductionScope,
    InMemoryConversationSummaryStore,
    JsonHeuristicTokenEstimator,
    PersistentSummaryContextReducer,
    TiktokenTokenEstimator,
    UnicodeHeuristicTokenEstimator,
    WindowContextReducer,
)
from sagents.v2.context.runtime_metadata import RunMetadataContextProvider
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage, ModelToolCall


def message(text, role="assistant", **kwargs):
    return ModelMessage(role=role, content=(TextBlock(text=text),), **kwargs)


def scope(key="session"):
    return ContextReductionScope(context_key=key, session_id=key, run_id=key)


class Summary:
    def __init__(self, text="history summary"):
        self.requests = []
        self.text = text

    async def summarize(self, request):
        self.requests.append(request)
        return self.text


class Counting(JsonHeuristicTokenEstimator):
    def __init__(self):
        super().__init__()
        self.visits = 0

    def estimate(self, messages):
        self.visits += len(messages)
        return super().estimate(messages)


@pytest.mark.asyncio
async def test_window_serializes_long_history_once_and_preserves_current_turn():
    estimator = Counting()
    source = tuple(message(f"{i} " + "history " * 200) for i in range(800))
    source += (message("current", "user"), message("current draft"))
    result = await WindowContextReducer(estimator).reduce(
        source, ContextBudget(max_input_tokens=4000)
    )
    assert estimator.visits == len(source)
    assert result.messages[-2:] == source[-2:]
    assert result.historical_messages + result.messages == source
    assert result.estimated_tokens <= 4000


@pytest.mark.asyncio
async def test_custom_nonadditive_estimator_retains_full_request_semantics():
    class Estimator:
        def estimate(self, messages):
            return len(messages) ** 2 + 10

    source = tuple(message(str(i)) for i in range(10)) + (message("current", "user"),)
    result = await WindowContextReducer(Estimator()).reduce(
        source, ContextBudget(max_input_tokens=20)
    )
    assert len(result.messages) == 3
    assert result.estimated_tokens == 19


@pytest.mark.asyncio
async def test_system_budget_fails_before_any_summary_call():
    summarizer = Summary()
    reducer = PersistentSummaryContextReducer(
        InMemoryConversationSummaryStore(), summarizer=summarizer
    )
    with pytest.raises(SageV2Error, match="system instructions"):
        await reducer.reduce(
            (message("system " * 100, "system"), message("current", "user")),
            ContextBudget(max_input_tokens=10000, max_system_tokens=50),
            scope=scope(),
        )
    assert not summarizer.requests


@pytest.mark.asyncio
async def test_recent_historical_protection_is_bounded_by_tokens():
    source = tuple(message(f"{i} " + "history " * 100) for i in range(6)) + (
        message("current", "user"),
    )

    async def project(recent_tokens):
        summarizer = Summary()
        result = await PersistentSummaryContextReducer(
            InMemoryConversationSummaryStore(),
            summarizer=summarizer,
            protected_recent_units=4,
            summary_target_tokens=64,
        ).reduce(
            source,
            ContextBudget(
                max_input_tokens=100000,
                max_messages=6,
                protected_recent_tokens=recent_tokens,
            ),
            scope=scope(),
        )
        return result, summarizer

    small, small_summary = await project(0)
    large, _ = await project(8192)
    assert small.historical_messages == source[:-1]
    assert len(large.historical_messages) < len(small.historical_messages)
    assert small.messages[-1] == source[-1]
    assert len(small_summary.requests) == 1


@pytest.mark.asyncio
async def test_oversized_summary_does_not_repeat_overlapping_model_work():
    summarizer = Summary("summary " * 400)
    store = InMemoryConversationSummaryStore()
    source = (message("history " * 3000), message("latest", "user"))
    with pytest.raises(SageV2Error):
        await PersistentSummaryContextReducer(
            store, summarizer=summarizer, summary_target_tokens=32
        ).reduce(source, ContextBudget(max_input_tokens=500), scope=scope())
    assert len(summarizer.requests) == 1
    assert await store.get("session") is None


@pytest.mark.asyncio
async def test_summary_work_limit_is_checked_before_model_calls():
    summarizer = Summary()
    source = tuple(message("history " * 70 + str(i)) for i in range(12)) + (
        message("latest", "user"),
    )
    with pytest.raises(SageV2Error) as caught:
        await PersistentSummaryContextReducer(
            InMemoryConversationSummaryStore(),
            summarizer=summarizer,
            summary_target_tokens=32,
            max_summary_source_tokens=600,
            max_summary_calls=1,
        ).reduce(
            source,
            ContextBudget(max_input_tokens=1000, protected_recent_tokens=0),
            scope=scope(),
        )
    assert caught.value.info.code == "context.summary_work_limit"
    assert not summarizer.requests


@pytest.mark.asyncio
async def test_summary_batches_keep_tool_pairs_together_and_bound_source():
    summarizer = Summary()
    call = ModelToolCall(tool_call_id="call", name="read", arguments={})
    source = (
        message("history " * 130),
        ModelMessage(role="assistant", tool_calls=(call,)),
        message("result " * 80, "tool", tool_call_id="call"),
        message("latest", "user"),
    )
    await PersistentSummaryContextReducer(
        InMemoryConversationSummaryStore(),
        summarizer=summarizer,
        summary_target_tokens=32,
        max_summary_source_tokens=700,
    ).reduce(
        source,
        ContextBudget(
            max_input_tokens=100000, max_messages=2, protected_recent_tokens=0
        ),
        scope=scope(),
    )
    assert len(summarizer.requests) == 2
    assert [m.role for m in summarizer.requests[-1].messages] == ["assistant", "tool"]


@pytest.mark.asyncio
async def test_reference_compaction_keeps_existing_summary():
    summarizer = Summary()
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(
        store, summarizer=summarizer, summary_target_tokens=32
    )
    source = (message("old " * 300), message("current", "user"))
    await reducer.reduce(
        source, ContextBudget(max_input_tokens=100000, max_messages=2), scope=scope()
    )
    # Force a summary first: source is already two messages, so use a large old prefix.
    source = (message("old " * 3000), message("current", "user"))
    first = await reducer.reduce(
        source, ContextBudget(max_input_tokens=1000), scope=scope()
    )
    call = ModelToolCall(tool_call_id="call", name="read", arguments={})
    extended = (
        *source,
        ModelMessage(role="assistant", tool_calls=(call,)),
        message(
            "huge " * 10000,
            "tool",
            tool_call_id="call",
            metadata={"context_reference": "artifact://result"},
        ),
    )
    second = await reducer.reduce(
        extended, ContextBudget(max_input_tokens=1000), scope=scope()
    )
    assert second.messages[0] == first.messages[0]
    assert second.messages[-1].metadata["context_compacted_to_reference"]
    assert extended[0] in second.historical_messages
    assert extended[-1] in second.historical_messages
    assert len(summarizer.requests) == 1


@pytest.mark.parametrize(
    "estimator", [JsonHeuristicTokenEstimator(), UnicodeHeuristicTokenEstimator()]
)
def test_cache_invalidates_nested_mutations_and_is_bounded(estimator):
    value = message("original", metadata={"nested": {"value": "a"}})
    before = estimator.estimate((value,))
    value.metadata["nested"]["value"] = "changed " * 100
    assert estimator.estimate((value,)) > before
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(
            pool.map(lambda i: estimator.estimate((message(str(i)),)), range(2100))
        )
    assert all(result > 0 for result in results)
    assert len(estimator._cache) == 2048
    assert all(
        isinstance(key[1], bytes) and len(key[1]) == 32 for key in estimator._cache
    )


@pytest.mark.asyncio
async def test_parallel_accounting_has_shared_capacity_and_does_not_block_loop():
    lock = threading.Lock()
    active = peak = 0

    class Slow(JsonHeuristicTokenEstimator):
        def _text_tokens(self, value):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(active, peak)
            try:
                time.sleep(0.02)
                return super()._text_tokens(value)
            finally:
                with lock:
                    active -= 1

    tasks = [
        asyncio.create_task(Slow().estimate_async((message(str(i)),)))
        for i in range(16)
    ]
    ticks = 0
    while not all(task.done() for task in tasks):
        ticks += 1
        await asyncio.sleep(0.005)
    assert all(value > 0 for value in await asyncio.gather(*tasks))
    assert peak == 2
    assert ticks >= 10


@pytest.mark.asyncio
async def test_cancellation_does_not_release_a_running_cpu_worker_slot():
    started = threading.Event()
    release = threading.Event()
    active = peak = 0
    lock = threading.Lock()

    class Blocking(JsonHeuristicTokenEstimator):
        def _text_tokens(self, value):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if active == 2:
                    started.set()
            try:
                release.wait(timeout=5)
                return super()._text_tokens(value)
            finally:
                with lock:
                    active -= 1

    tasks = [
        asyncio.create_task(Blocking().estimate_async((message(str(i)),)))
        for i in range(4)
    ]
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(0.001)
        tasks[0].cancel()
        tasks[1].cancel()
        await asyncio.sleep(0.03)
        assert peak == 2
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)


def test_workspace_memory_is_bounded_but_core_instructions_are_not_silently_cut():
    provider = RunMetadataContextProvider()
    memory = provider._identity_document("MEMORY", "记忆" * 100000, "zh")
    assert len(memory) < 4200
    assert "Excerpt only" in memory
    with pytest.raises(SageV2Error):
        provider._identity_document("AGENT", "instruction " * 5000, "en")


def test_tiktoken_cache_reuses_counts_but_tracks_changed_content():
    class Encoder:
        def __init__(self):
            self.calls = 0

        def encode(self, text):
            self.calls += 1
            return list(text)

    encoder = Encoder()
    estimator = TiktokenTokenEstimator(encoder=encoder)
    original = message("first")
    before = estimator.estimate((original,))
    assert estimator.estimate((original.model_copy(deep=True),)) == before
    assert encoder.calls == 1
    assert estimator.estimate((message("second and longer"),)) > before
    assert encoder.calls == 2


def test_manifest_system_and_protected_limits_respect_global_ceiling():
    from sagents.v2.package.presets.factory import BuiltinPackageFactory
    from sagents.v2.package.manifest.resolver import CompositionResolver

    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.context-zones",
        model="test",
        base_url="https://model.invalid/v1",
    )
    data = package.model_dump(mode="json")
    agent_id = data["entrypoint"]["agent"]
    data["agents"][agent_id]["budgets"].update(
        system_tokens=12000, protected_recent_tokens=4096
    )
    data["policies"]["budgets"].update(system_tokens=8000, protected_recent_tokens=0)
    resolved = CompositionResolver().resolve(type(package).model_validate(data))
    assert resolved.policy_ceilings[agent_id].max_system_tokens == 8000
    assert resolved.policy_ceilings[agent_id].protected_recent_tokens == 0


@pytest.mark.asyncio
async def test_public_builder_rejects_unbounded_input_before_model_request(tmp_path):
    from sagents.v2 import SAgentBuilder
    from sagents.v2.contracts.commands import InputItem, StartRun
    from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
    from sagents.v2.model import ScriptedModelProvider
    from sagents.v2.package.presets import BuiltinPackageFactory

    package = BuiltinPackageFactory.create(
        "assistant",
        package_id="test.default-budget",
        model="test",
        base_url="https://model.invalid/v1",
    )
    model = ScriptedModelProvider(())
    application = await (
        SAgentBuilder()
        .with_defaults(session_root=tmp_path)
        .with_model_provider(model)
        .build(package)
    )
    try:
        stream = await application.entrypoint().run_stream(
            StartRun(
                agent_id=package.entrypoint.agent,
                input=(
                    InputItem(role="user", content=(TextBlock(text="x" * 140000),)),
                ),
                resolved_spec_hash=application.composition_hash,
                idempotency_key="large",
            ),
            RequestContext(
                actor=ActorRef(principal_id="user", principal_type=PrincipalType.USER)
            ),
        )
        result = await stream.wait()
        events = await application.entrypoint().runtime.session_store.read_events(
            result.run_id
        )
        failure = next(event for event in events if event.type == "run.failed")
        assert failure.data.error.code == "context.budget_exhausted"
        assert model.requests == []
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_summary_capacity_is_shared_across_plugin_instances():
    from sagents.v2.context import ModelConversationSummarizer

    active = peak = 0

    class SummaryPlugin(ModelConversationSummarizer):
        async def _summarize(self, request):
            nonlocal active, peak
            active += 1
            peak = max(active, peak)
            try:
                await asyncio.sleep(0.01)
                return "summary"
            finally:
                active -= 1

    values = await asyncio.gather(
        *(SummaryPlugin(None).summarize(None) for _ in range(16))
    )
    assert values == ["summary"] * 16
    assert peak == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("summary", [False, True])
async def test_developer_instructions_are_never_removed_to_fit_context(summary):
    reducer = (
        PersistentSummaryContextReducer(InMemoryConversationSummaryStore())
        if summary
        else WindowContextReducer()
    )
    source = (
        message("mandatory instruction " * 500, "developer"),
        message("old history"),
        message("current", "user"),
    )
    with pytest.raises(SageV2Error):
        await reducer.reduce(source, ContextBudget(max_input_tokens=100), scope=scope())


@pytest.mark.asyncio
async def test_large_existing_summary_can_shrink_with_new_history():
    summarizer = Summary("old summary " * 100)
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(
        store, summarizer=summarizer, summary_target_tokens=512
    )
    original = (message("old history " * 1000), message("first request", "user"))
    first = await reducer.reduce(
        original, ContextBudget(max_input_tokens=1500), scope=scope()
    )
    assert first.strategy == "persistent_summary"
    summarizer.text = "compact updated summary"
    extended = (*original, message("new history " * 100), message("current", "user"))
    result = await reducer.reduce(
        extended, ContextBudget(max_input_tokens=250), scope=scope()
    )
    assert result.estimated_tokens <= 250
    assert result.messages[-1] == extended[-1]
    assert (
        summarizer.requests[-1].previous_summary == "old summary " * 99 + "old summary"
    )
    assert len(summarizer.requests) == 2
