from __future__ import annotations

import asyncio
import json

import pytest

from sagents.v2.context import (
    ContextBudget,
    ContextReductionScope,
    ExtractiveConversationSummarizer,
    InMemoryConversationSummaryStore,
    ModelConversationSummarizer,
    PersistentSummaryContextReducer,
    SessionDerivedConversationSummaryStore,
)
from sagents.v2.context.assembler import DefaultContextAssembler
from sagents.v2.context.summary import SummarizationRequest
from sagents.v2.model import (
    ModelEventKind,
    ModelMessage,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ScriptedModelProvider,
    ScriptedModelStep,
)
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import ImageBlock, JsonBlock, TextBlock, UsageSummary


class RecordingSummarizer:
    def __init__(self):
        self.requests: list[SummarizationRequest] = []

    async def summarize(self, request: SummarizationRequest) -> str:
        self.requests.append(request)
        labels = ",".join(message.role for message in request.messages)
        previous = (
            f" previous={request.previous_summary}" if request.previous_summary else ""
        )
        return f"summary({labels}){previous}"


class ExpandingSummarizer:
    async def summarize(self, request: SummarizationRequest) -> str:
        return "expanded summary " * 2_000


def scope(context_key="session_1"):
    return ContextReductionScope(
        context_key=context_key,
        session_id="session_1",
        run_id="run_1",
        source_sequence=12,
    )


def test_summary_context_key_is_bounded_and_opaque_for_legal_identifiers():
    session_id = "tenant:snapshot:" + "x" * 176
    key = DefaultContextAssembler._summary_context_key(
        session_id, run_id="run:snapshot:child"
    )

    assert key.startswith("context_")
    assert len(key) == 72
    assert session_id not in key


@pytest.mark.asyncio
async def test_session_derived_store_upgrades_legacy_summary_on_read():
    class LegacyDerivedState:
        async def get_derived_state(self, session_id, namespace, key):
            assert (session_id, namespace, key) == (
                "session_1",
                "context-summary",
                "context_legacy",
            )
            return {
                "summary_id": "summary_1",
                "context_key": "context_legacy",
                "revision": 1,
                "source_digest": "sha256:legacy",
                "covered_message_digests": ["sha256:message"],
                "source_message_count": 1,
                "text": "legacy summary",
                "estimated_tokens": 3,
                "source_sequence": 4,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }

    store = SessionDerivedConversationSummaryStore(LegacyDerivedState())
    summary = await store.get("context_legacy", session_id="session_1")

    assert summary is not None
    assert summary.session_id == "session_1"


def ledger():
    call = ModelToolCall(tool_call_id="call_1", name="lookup", arguments={})
    return (
        ModelMessage(role="system", content=(TextBlock(text="system"),)),
        ModelMessage(role="user", content=(TextBlock(text="old question"),)),
        ModelMessage(role="assistant", tool_calls=(call,)),
        ModelMessage(
            role="tool", tool_call_id="call_1", content=(TextBlock(text="result"),)
        ),
        ModelMessage(role="assistant", content=(TextBlock(text="old answer"),)),
        ModelMessage(role="user", content=(TextBlock(text="latest question"),)),
    )


def test_summary_units_never_drop_an_unmatched_tool_message():
    call = ModelToolCall(tool_call_id="call_expected", name="lookup", arguments={})
    messages = (
        ModelMessage(role="assistant", tool_calls=(call,)),
        ModelMessage(
            role="tool",
            tool_call_id="call_unmatched",
            content=(TextBlock(text="must survive"),),
        ),
        ModelMessage(role="user", content=(TextBlock(text="continue"),)),
    )

    units = __import__(
        "sagents.v2.context.partition", fromlist=["conversation_units"]
    ).conversation_units(messages)

    assert units == [(messages[0],), (messages[1],), (messages[2],)]


@pytest.mark.asyncio
async def test_persistent_summary_replaces_old_units_without_splitting_tool_pairs():
    store = InMemoryConversationSummaryStore()
    summarizer = RecordingSummarizer()
    reducer = PersistentSummaryContextReducer(
        store,
        summarizer=summarizer,
        protected_recent_units=2,
        summary_target_tokens=128,
    )

    projection = await reducer.reduce(
        ledger(), ContextBudget(max_input_tokens=100_000, max_messages=4), scope=scope()
    )

    assert projection.strategy == "persistent_summary"
    assert projection.dropped_message_count == 3
    assert projection.historical_messages == ledger()[1:4]
    assert [message.role for message in projection.messages] == [
        "system",
        "system",
        "assistant",
        "user",
    ]
    assert projection.messages[1].metadata["context_summary"] is True
    assert [message.role for message in summarizer.requests[0].messages] == [
        "user",
        "assistant",
        "tool",
    ]
    stored = await store.get("session_1")
    assert stored is not None
    assert stored.revision == 1
    assert stored.source_sequence == 12


@pytest.mark.asyncio
async def test_existing_summary_is_reused_and_rolled_forward_on_later_turns():
    store = InMemoryConversationSummaryStore()
    summarizer = RecordingSummarizer()
    reducer = PersistentSummaryContextReducer(
        store, summarizer=summarizer, protected_recent_units=2
    )
    budget = ContextBudget(max_input_tokens=100_000, max_messages=4)
    await reducer.reduce(ledger(), budget, scope=scope())
    extended = (
        *ledger(),
        ModelMessage(role="assistant", content=(TextBlock(text="new answer"),)),
        ModelMessage(role="user", content=(TextBlock(text="new request"),)),
    )

    projection = await reducer.reduce(extended, budget, scope=scope())

    stored = await store.get("session_1")
    assert stored is not None
    assert stored.revision == 2
    assert summarizer.requests[-1].previous_summary == "summary(user,assistant,tool)"
    assert projection.historical_messages == extended[1:6]
    assert projection.messages[-1].content[0].text == "new request"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_summary_survives_history_provenance_reconstruction(legacy):
    from sagents.v2.context.summary import message_digests_async

    store = InMemoryConversationSummaryStore()
    summarizer = RecordingSummarizer()
    reducer = PersistentSummaryContextReducer(
        store,
        summarizer=summarizer,
        protected_recent_units=2,
        summary_target_tokens=128,
    )
    source = ledger()
    # Simulate a prefix from prior Runs, followed by new active-Run messages.
    source = (
        source[0],
        source[1].model_copy(
            update={
                "metadata": {"source_run_id": "old-run", "source_item_id": "old-item"}
            }
        ),
        *source[2:],
    )
    budget = ContextBudget(max_input_tokens=100_000, max_messages=4)
    await reducer.reduce(source, budget, scope=scope())
    saved = await store.get("session_1")
    if legacy:
        saved = saved.model_copy(
            update={
                "covered_message_digests": await message_digests_async(
                    source[1:4], include_source_metadata=True
                )
            }
        )
        await store.save(saved, expected_revision=saved.revision)
    rebuilt = tuple(
        m.model_copy(
            update={
                "metadata": {
                    **m.metadata,
                    "source_session_id": "session_1",
                    "source_run_id": "rebuilt-run",
                    "source_item_id": f"item-{i}",
                }
            }
        )
        if i >= 2
        else m
        for i, m in enumerate(source)
    )
    result = await reducer.reduce(rebuilt, budget, scope=scope())
    assert result.strategy == "persistent_summary"
    assert len(summarizer.requests) == 1
    assert await store.get("session_1") == saved
    for field in ("content", "metadata"):
        changed = rebuilt[1].model_copy(
            update={
                field: (
                    (TextBlock(text="rewritten fact"),)
                    if field == "content"
                    else {**rebuilt[1].metadata, "tool_context": True}
                )
            }
        )
        validated, _ = await reducer._validated_previous(saved, (changed, *rebuilt[2:]))
        assert validated is None


@pytest.mark.asyncio
async def test_exhausted_summary_timeout_preserves_previous_summary_and_history(
    monkeypatch,
):
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(
        store, summarizer=RecordingSummarizer(), protected_recent_units=2
    )
    budget = ContextBudget(max_input_tokens=100_000, max_messages=4)
    await reducer.reduce(ledger(), budget, scope=scope())
    previous = await store.get("session_1")
    source = (
        *ledger(),
        ModelMessage(role="assistant", content=(TextBlock(text="new answer"),)),
        ModelMessage(role="user", content=(TextBlock(text="new request"),)),
    )
    original = tuple(message.model_dump() for message in source)
    summarizer = ModelConversationSummarizer(ScriptedModelProvider(()))

    async def fail(request, progress):
        raise summarizer._timeout_error("idle", progress)

    async def sleep(delay):
        pass

    monkeypatch.setattr(summarizer, "_summarize", fail)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    reducer.summarizer = summarizer
    with pytest.raises(SageV2Error) as caught:
        await reducer.reduce(source, budget, scope=scope())
    assert caught.value.info.metadata["timeout_retries_exhausted"] is True
    assert await store.get("session_1") == previous
    assert tuple(message.model_dump() for message in source) == original


@pytest.mark.asyncio
async def test_rewritten_prefix_never_applies_stale_summary():
    store = InMemoryConversationSummaryStore()
    summarizer = RecordingSummarizer()
    reducer = PersistentSummaryContextReducer(
        store, summarizer=summarizer, protected_recent_units=2
    )
    budget = ContextBudget(max_input_tokens=100_000, max_messages=4)
    await reducer.reduce(ledger(), budget, scope=scope())
    rewritten = list(ledger())
    rewritten[1] = ModelMessage(
        role="user", content=(TextBlock(text="rewritten history"),)
    )

    await reducer.reduce(tuple(rewritten), budget, scope=scope())

    stored = await store.get("session_1")
    assert stored is not None
    assert stored.revision == 2
    assert summarizer.requests[-1].previous_summary is None


@pytest.mark.asyncio
async def test_incompatible_prefix_keeps_checkpoint_when_reduction_fails():
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(
        store, summarizer=RecordingSummarizer(), protected_recent_units=2
    )
    await reducer.reduce(
        ledger(), ContextBudget(max_input_tokens=100_000, max_messages=4), scope=scope()
    )
    original = await store.get("session_1")
    rewritten = list(ledger())
    rewritten[1] = ModelMessage(
        role="user", content=(TextBlock(text="rewritten history"),)
    )

    reducer.summarizer = ExpandingSummarizer()
    with pytest.raises(SageV2Error) as caught:
        await reducer.reduce(
            tuple(rewritten),
            ContextBudget(max_input_tokens=80, max_messages=1),
            scope=scope(),
        )
    assert caught.value.info.code == "context.summary_no_progress"
    kept = await store.get("session_1")
    assert kept is not None
    assert kept.summary_id == original.summary_id
    assert kept.text == original.text
    assert kept.revision == original.revision


@pytest.mark.asyncio
async def test_summary_state_is_isolated_by_context_key():
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(store, protected_recent_units=2)
    budget = ContextBudget(max_input_tokens=100_000, max_messages=4)

    await reducer.reduce(ledger(), budget, scope=scope("session_1"))
    await reducer.reduce(ledger(), budget, scope=scope("session_1:snapshot:run_2"))

    assert await store.get("session_1") is not None
    assert await store.get("session_1:snapshot:run_2") is not None


@pytest.mark.asyncio
async def test_stateful_reducer_requires_explicit_session_run_scope():
    reducer = PersistentSummaryContextReducer(InMemoryConversationSummaryStore())
    with pytest.raises(SageV2Error) as caught:
        await reducer.reduce(ledger(), ContextBudget(max_input_tokens=100_000))
    assert caught.value.info.code == "context.summary_scope_required"


@pytest.mark.asyncio
async def test_summary_must_reduce_only_the_selected_compressible_content():
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(
        store,
        summarizer=ExpandingSummarizer(),
        protected_recent_units=1,
    )
    source = (
        ModelMessage(role="user", content=(TextBlock(text="old " * 400),)),
        ModelMessage(role="assistant", content=(TextBlock(text="answer " * 400),)),
        ModelMessage(role="user", content=(TextBlock(text="latest request"),)),
    )

    with pytest.raises(SageV2Error) as caught:
        await reducer.reduce(
            source,
            ContextBudget(
                max_input_tokens=2_000,
                reserve_input_tokens=900,
                max_messages=2,
            ),
            scope=scope(),
        )

    assert caught.value.info.code == "context.summary_no_progress"
    assert await store.get("session_1") is None


@pytest.mark.asyncio
async def test_latest_real_user_and_everything_after_it_are_never_summarized():
    reducer = PersistentSummaryContextReducer(
        InMemoryConversationSummaryStore(),
        summarizer=RecordingSummarizer(),
        protected_recent_units=1,
    )
    source = (
        ModelMessage(role="user", content=(TextBlock(text="old question " * 100),)),
        ModelMessage(role="assistant", content=(TextBlock(text="old answer " * 100),)),
        ModelMessage(role="user", content=(TextBlock(text="latest question"),)),
        ModelMessage(role="assistant", content=(TextBlock(text="draft response"),)),
    )

    projection = await reducer.reduce(
        source,
        ContextBudget(max_input_tokens=100_000, max_messages=3),
        scope=scope(),
    )

    assert projection.historical_messages == source[:2]
    assert [message.content[0].text for message in projection.messages[-2:]] == [
        "latest question",
        "draft response",
    ]


@pytest.mark.asyncio
async def test_oversized_protected_tool_unit_uses_explicit_durable_reference():
    call = ModelToolCall(tool_call_id="call_large", name="read_large", arguments={})
    source = (
        ModelMessage(role="user", content=(TextBlock(text="inspect it"),)),
        ModelMessage(role="assistant", tool_calls=(call,)),
        ModelMessage(
            role="tool",
            tool_call_id="call_large",
            content=(TextBlock(text="large output " * 2_000),),
            metadata={
                "context_reference": {
                    "uri": "artifact://tool-result/call_large",
                    "digest": "sha256:large",
                }
            },
        ),
    )
    reducer = PersistentSummaryContextReducer(
        InMemoryConversationSummaryStore(), protected_recent_units=2
    )

    projection = await reducer.reduce(
        source,
        ContextBudget(max_input_tokens=300),
        scope=scope().model_copy(update={"force": True}),
    )

    assert projection.strategy == "reference_compaction"
    assert projection.historical_messages == (source[-1],)
    assert projection.messages[-1].metadata["context_compacted_to_reference"]
    assert "artifact://tool-result/call_large" in (
        projection.messages[-1].content[0].text
    )


def _summary_completion(text: str) -> ModelStreamEvent:
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="summary_response",
            text=text,
            finish_reason="stop",
            usage=UsageSummary(),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_count", [1, 2, 3, 4, 5, 8])
async def test_pressure_progressively_retires_recent_batches_even_inside_window(batch_count):
    summarizer = RecordingSummarizer()
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(store, summarizer=summarizer)
    user = ModelMessage(role="user", content=(TextBlock(text="exact request"),))

    def batch(index):
        call_id = f"call_{index}"
        return (
            ModelMessage(role="assistant", tool_calls=(
                ModelToolCall(tool_call_id=call_id, name="query", arguments={}),
            )),
            ModelMessage(role="tool", tool_call_id=call_id,
                         content=(TextBlock(text="x" * 5000),)),
        )

    batches = [batch(i) for i in range(batch_count)]
    source = (user, *(m for unit in batches for m in unit))
    forced = scope().model_copy(update={"force": True, "allow_summary_rewrite": False})
    projection = await reducer.reduce(source, scope=forced)
    retained_count = min(batch_count - 1, 4)
    expected = tuple(m for unit in batches[-retained_count:] for m in unit) if retained_count else ()
    assert projection.messages == (projection.messages[0], user, *expected)
    previous_covered = projection.dropped_message_count
    for _ in range(retained_count):
        projection = await reducer.reduce(source, scope=forced)
        assert projection.dropped_message_count == previous_covered + 2
        previous_covered = projection.dropped_message_count
    assert previous_covered == len(source)
    assert len(summarizer.requests) == retained_count + 1
    # The last complete Tool pair is reducible too; the user anchor stays exact.
    assert projection.messages[1:] == (user,)
    assert projection.historical_messages == source
    await reducer.reduce(source, scope=forced)
    assert len(summarizer.requests) == retained_count + 1


@pytest.mark.asyncio
async def test_pressure_does_not_regenerate_checkpoint_without_reducible_history():
    from sagents.v2.context.summary import create_summary, message_digests_async

    summarizer = RecordingSummarizer()
    store = InMemoryConversationSummaryStore()
    source = (ModelMessage(role="user", content=(TextBlock(text="exact request"),)),)
    await store.save(
        create_summary(
            scope=scope(), previous=None, covered_messages=source,
            covered_digests=await message_digests_async(source), text="checkpoint",
        ),
        expected_revision=None,
    )
    reducer = PersistentSummaryContextReducer(store, summarizer=summarizer)

    projection = await reducer.reduce(
        source, scope=scope().model_copy(update={"force": True, "allow_summary_rewrite": False})
    )

    assert summarizer.requests == []
    assert projection.messages[-1] == source[0]
    assert (await store.get("session_1")).revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["tool_outcomes", "todo_state_at_compaction_boundary"])
async def test_summary_echoed_derived_fields_are_rebuilt_without_model_retry(field):
    payload = {"summary": "verified", **{
        key: [] for key in ModelConversationSummarizer._FIELDS[1:]
    }, field: {"invented": "must not become authoritative"}}
    model = ScriptedModelProvider((
        ScriptedModelStep(events=(_summary_completion(json.dumps(payload)),)),
    ))
    value = await ModelConversationSummarizer(model).summarize(
        SummarizationRequest(scope=scope(), messages=ledger()[1:4], target_tokens=512)
    )

    decoded = json.loads(value)
    assert len(model.requests) == 1
    assert "invented" not in decoded.get(field, {})
    assert decoded["tool_outcomes"]["lookup "]["status"] == "completed"


@pytest.mark.parametrize("change", ["unknown", "missing", "wrong_type"])
def test_summary_still_rejects_invalid_required_contract(change):
    payload = {"summary": "verified", **{
        key: [] for key in ModelConversationSummarizer._FIELDS[1:]
    }}
    if change == "unknown":
        payload["unknown"] = []
    elif change == "missing":
        del payload["open_tasks"]
    else:
        payload["decisions"] = "invalid"
    with pytest.raises(ValueError):
        ModelConversationSummarizer._parse_payload(json.dumps(payload))


@pytest.mark.asyncio
async def test_model_summarizer_retries_and_returns_the_structured_contract():
    payload = {
        "summary": "Goal and verified state",
        "decisions": ["Use v2 ports"],
        "open_tasks": ["Run the suite"],
        "files_touched": ["sagents/v2/example.py"],
        "commands_run": ["pytest -q"],
        "important_errors": [],
        "user_requirements": ["Do not use old code"],
    }
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(events=(_summary_completion("not-json"),)),
            ScriptedModelStep(events=(_summary_completion(json.dumps(payload)),)),
        )
    )
    summarizer = ModelConversationSummarizer(model)

    value = await summarizer.summarize(
        SummarizationRequest(
            scope=scope(),
            messages=ledger()[1:4],
            previous_summary=None,
            target_tokens=512,
        )
    )

    decoded = json.loads(value)
    assert {key: decoded[key] for key in payload} == payload
    assert decoded["tool_outcomes"]["lookup "]["status"] == "completed"
    assert len(model.requests) == 2
    assert model.requests[0].response_schema is not None
    assert model.requests[1].metadata == {
        "purpose": "conversation_summary",
        "attempt": 2,
        "response_language": "en",
    }


@pytest.mark.asyncio
async def test_model_summarizer_does_not_copy_media_payloads_into_source_text():
    payload = {
        "summary": "An image was inspected.",
        "decisions": [],
        "open_tasks": [],
        "files_touched": [],
        "commands_run": [],
        "important_errors": [],
        "user_requirements": [],
    }
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(_summary_completion(json.dumps(payload)),)),)
    )
    summarizer = ModelConversationSummarizer(model)
    base64_payload = "A" * 20_000
    data_url = f"data:image/png;base64,{base64_payload}"

    await summarizer.summarize(
        SummarizationRequest(
            scope=scope(),
            messages=(
                ModelMessage(
                    role="tool",
                    tool_call_id="call_image",
                    content=(
                        TextBlock(text=f"prefix {data_url} suffix"),
                        JsonBlock(value={"nested": {"image": data_url}}),
                        ImageBlock(
                            uri=data_url,
                            mime_type="image/png",
                            alt="/workspace/cat.png",
                        ),
                    ),
                ),
            ),
            target_tokens=512,
        )
    )

    source = model.requests[0].messages[1].content[0].text
    assert base64_payload not in source
    assert data_url not in source
    assert source.count("<redacted data URL; mime=image/png; base64_len=20000>") == 2
    assert "[image attached: mime=image/png, alt=/workspace/cat.png]" in source


@pytest.mark.asyncio
async def test_extractive_summarizers_replace_images_with_safe_placeholders():
    data_url = "data:image/jpeg;base64," + ("B" * 20_000)
    request = SummarizationRequest(
        scope=scope(),
        messages=(
            ModelMessage(
                role="tool",
                tool_call_id="call_image",
                content=(
                    ImageBlock(
                        uri=data_url,
                        mime_type="image/jpeg",
                        alt="photo.jpg",
                    ),
                ),
            ),
        ),
        target_tokens=512,
    )
    summarizers = (
        ExtractiveConversationSummarizer(),
        PersistentSummaryContextReducer(InMemoryConversationSummaryStore()).summarizer,
    )

    for summarizer in summarizers:
        summary = await summarizer.summarize(request)
        assert "B" * 100 not in summary
        assert "base64" not in summary
        assert "[image attached: mime=image/jpeg, alt=photo.jpg]" in summary


@pytest.mark.asyncio
async def test_model_summarizer_propagates_chinese_response_language():
    payload = {
        "summary": "目标与已验证状态",
        "decisions": [],
        "open_tasks": [],
        "files_touched": [],
        "commands_run": [],
        "important_errors": [],
        "user_requirements": [],
    }
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(_summary_completion(json.dumps(payload)),)),)
    )
    summarizer = ModelConversationSummarizer(model)

    await summarizer.summarize(
        SummarizationRequest(
            scope=scope().model_copy(update={"response_language": "zh-CN"}),
            messages=ledger()[1:4],
            target_tokens=512,
        )
    )

    assert model.requests[0].metadata["response_language"] == "zh"
    assert "使用中文" in model.requests[0].messages[0].content[0].text


@pytest.mark.asyncio
async def test_model_summarizer_bounds_the_entire_auxiliary_stream():
    class SlowSummaryModel:
        async def capabilities(self, model_binding):
            del model_binding
            return await ScriptedModelProvider(()).capabilities("summary")

        def stream(self, request):
            del request

            async def events():
                yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="{")
                await asyncio.sleep(0.03)
                yield _summary_completion("{}")

            return events()

    summarizer = ModelConversationSummarizer(SlowSummaryModel(), timeout_seconds=0.01)
    summarizer._MAX_TIMEOUT_RETRIES = 0  # Test the deadline independently of backoff.

    with pytest.raises(SageV2Error) as caught:
        await summarizer.summarize(
            SummarizationRequest(
                scope=scope(),
                messages=ledger()[1:4],
                target_tokens=512,
            )
        )

    assert caught.value.info.code == "context.summarizer.model_timeout"
    assert caught.value.info.metadata["timeout_kind"] == "total"
    assert caught.value.info.metadata["text_delta_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["continuous", "idle", "total", "completed_tail"])
async def test_summary_stream_distinguishes_progress_stalls_and_completion(mode):
    payload = json.dumps(
        {
            "summary": "Verified history",
            "decisions": [],
            "open_tasks": [],
            "files_touched": [],
            "commands_run": [],
            "important_errors": [],
            "user_requirements": [],
        }
    )
    closed = asyncio.Event()

    class StreamingSummaryModel:
        async def capabilities(self, binding):
            return await ScriptedModelProvider(()).capabilities(binding)

        def stream(self, request):
            async def events():
                try:
                    yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="{")
                    if mode == "idle":
                        await asyncio.Event().wait()
                    elif mode == "total":
                        while True:
                            await asyncio.sleep(0.01)
                            yield ModelStreamEvent(
                                kind=ModelEventKind.REASONING_DELTA, delta="thinking"
                            )
                    elif mode == "continuous":
                        for _ in range(7):
                            await asyncio.sleep(0.02)
                            yield ModelStreamEvent(
                                kind=ModelEventKind.TEXT_DELTA, delta="x"
                            )
                    yield _summary_completion(payload)
                    if mode == "completed_tail":
                        # COMPLETED is authoritative; EOF may never arrive.
                        await asyncio.Event().wait()
                finally:
                    closed.set()

            return events()

    summarizer = ModelConversationSummarizer(
        StreamingSummaryModel(),
        timeout_seconds=0.08 if mode == "total" else 0.5,
        idle_timeout_seconds=0.06,
    )
    summarizer._MAX_TIMEOUT_RETRIES = 0
    request = SummarizationRequest(
        scope=scope(), messages=ledger()[1:4], target_tokens=512
    )
    if mode in {"idle", "total"}:
        with pytest.raises(SageV2Error) as caught:
            await summarizer.summarize(request)
        assert caught.value.info.code == "context.summarizer.model_timeout"
        assert caught.value.info.metadata["timeout_kind"] == mode
        assert caught.value.info.metadata["text_delta_count"] == 1
    else:
        result = await summarizer.summarize(request)
        assert json.loads(result)["summary"] == "Verified history"
    assert closed.is_set()


def test_summary_has_a_separate_total_budget_from_short_auxiliary_calls():
    summarizer = ModelConversationSummarizer(ScriptedModelProvider(()))
    assert summarizer.timeout_seconds == 300
    assert summarizer.idle_timeout_seconds == 60


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["idle", "total", "provider"])
@pytest.mark.parametrize("recover", [True, False])
async def test_summary_timeout_retries_are_bounded_and_logged(
    monkeypatch, kind, recover
):
    import httpx
    import sagents.v2.context.plugins.summarizer_model as module
    from sagents.v2.model.wire import provider_error
    from sagents.v2.runtime.observability.logs import StructuredLogger

    class Sink:
        def __init__(self):
            self.records = []

        def write(self, record):
            self.records.append(record)

    sink = Sink()
    monkeypatch.setattr(module, "LOGGER", StructuredLogger(sink, "summary-test"))
    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    summarizer = ModelConversationSummarizer(ScriptedModelProvider(()))
    attempts = []

    async def summarize(request, progress):
        attempts.append(request)
        progress["text_delta_count"] = 1
        if recover and len(attempts) == 4:
            return '{"summary":"recovered"}'
        if kind == "total":
            raise TimeoutError()
        if kind == "provider":
            try:
                raise httpx.ReadTimeout("provider stalled")
            except httpx.ReadTimeout as exc:
                raise provider_error(exc) from exc
        raise summarizer._timeout_error("idle", progress)

    monkeypatch.setattr(summarizer, "_summarize", summarize)
    request = SummarizationRequest(
        scope=scope(), messages=ledger()[1:4], target_tokens=512
    )
    if recover:
        assert json.loads(await summarizer.summarize(request))["summary"] == "recovered"
    else:
        with pytest.raises(SageV2Error) as caught:
            await summarizer.summarize(request)
        assert caught.value.info.code == "context.summarizer.model_timeout"
        assert caught.value.info.metadata["timeout_kind"] == kind
        assert caught.value.info.metadata["timeout_attempt"] == 4
        assert caught.value.info.metadata["timeout_retries_exhausted"] is True
    assert attempts == [request] * 4
    assert delays == [2, 4, 8]
    retries = [
        record
        for record in sink.records
        if record.event == "context.summary.timeout_retry"
    ]
    assert len(retries) == 3
    assert [record.attributes["timeout_attempt"] for record in retries] == [1, 2, 3]
    assert all(record.attributes["timeout_kind"] == kind for record in retries)
    assert all(
        record.session_id == "session_1" and record.run_id == "run_1"
        for record in sink.records
    )
    assert len({record.correlation_id for record in sink.records}) == 1
    assert sink.records[-1].event == (
        "context.summary.completed" if recover else "context.summary.timeout_exhausted"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_summary_does_not_retry_non_timeout_or_cancellation(monkeypatch, cancel):
    summarizer = ModelConversationSummarizer(ScriptedModelProvider(()))
    attempts = []

    async def summarize(request, progress):
        attempts.append(request)
        if cancel:
            raise asyncio.CancelledError()
        raise ValueError("invalid source")

    monkeypatch.setattr(summarizer, "_summarize", summarize)
    with pytest.raises(asyncio.CancelledError if cancel else ValueError):
        await summarizer.summarize(
            SummarizationRequest(
                scope=scope(), messages=ledger()[1:4], target_tokens=512
            )
        )
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_summary_timeout_includes_capability_discovery():
    class SlowCapabilities:
        async def capabilities(self, binding):
            await asyncio.Event().wait()

        def stream(self, request):
            raise AssertionError("must time out before starting a stream")

    summarizer = ModelConversationSummarizer(SlowCapabilities(), timeout_seconds=0.01)
    summarizer._MAX_TIMEOUT_RETRIES = 0
    with pytest.raises(SageV2Error) as caught:
        await summarizer.summarize(
            SummarizationRequest(
                scope=scope(), messages=ledger()[1:4], target_tokens=512
            )
        )
    assert caught.value.info.code == "context.summarizer.model_timeout"
    assert caught.value.info.metadata["timeout_kind"] == "total"
    assert caught.value.info.metadata["attempt"] == 0


class BoundedSummaryRecorder:
    def __init__(self, fail_on=None):
        self.requests = []
        self.fail_on = fail_on

    async def summarize(self, request):
        self.requests.append(request)
        if len(self.requests) == self.fail_on:
            raise RuntimeError("summary provider failed")
        return "bounded rolling summary"


def oversized_parallel_unit():
    return (
        ModelMessage(
            role="assistant",
            tool_calls=(
                ModelToolCall(
                    tool_call_id="project", name="get_item", arguments={"id": "item"}
                ),
                ModelToolCall(
                    tool_call_id="shell",
                    name="execute_shell_command",
                    arguments={"command": "inspect"},
                ),
            ),
        ),
        ModelMessage(
            role="tool",
            tool_call_id="project",
            content=(TextBlock(text="PROJECT_BEGIN" + "p" * 13_745 + "PROJECT_END"),),
        ),
        ModelMessage(
            role="tool",
            tool_call_id="shell",
            content=(TextBlock(text="SHELL_BEGIN" + "s" * 78_520 + "SHELL_END"),),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["中文摘要😀" * 1000, '路径\\和"引号\n' * 1000])
async def test_model_summary_preserves_complete_api_output_without_local_clipping(text):
    payload = {field: [] for field in ModelConversationSummarizer._FIELDS}
    payload["summary"] = text
    payload["user_requirements"] = [text]
    model = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(_summary_completion(json.dumps(payload, ensure_ascii=False)),)
            ),
        )
    )
    result = json.loads(
        await ModelConversationSummarizer(model).summarize(
            SummarizationRequest(
                scope=scope(), messages=ledger()[1:4], target_tokens=512
            )
        )
    )
    assert result["summary"] == text.strip()
    assert result["user_requirements"] == [text.strip()]


@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [False, True])
async def test_summary_transient_provider_errors_retry_without_losing_progress(
    monkeypatch, recover
):
    import sagents.v2.context.plugins.summarizer_model as module
    from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo

    delays = []

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    summarizer = ModelConversationSummarizer(ScriptedModelProvider(()))
    attempts = []

    async def summarize(request, progress):
        attempts.append(request)
        if recover and len(attempts) == 4:
            return "recovered summary"
        raise SageV2Error(
            RuntimeErrorInfo(
                code="model.provider_transient",
                category=ErrorCategory.PROVIDER_TRANSIENT,
                message="upstream unavailable",
                retryable=True,
            )
        )

    monkeypatch.setattr(summarizer, "_summarize", summarize)
    request = SummarizationRequest(
        scope=scope(), messages=ledger()[1:4], target_tokens=512
    )
    if recover:
        assert await summarizer.summarize(request) == "recovered summary"
    else:
        with pytest.raises(SageV2Error) as caught:
            await summarizer.summarize(request)
        assert caught.value.info.code == "model.provider_transient"
    assert attempts == [request] * 4
    assert delays == [2, 4, 8]
