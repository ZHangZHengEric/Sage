"""Context recovery invariants: API feedback, atomic checkpoints, finite work."""

from __future__ import annotations

import asyncio
import json

import pytest

from sagents.v2.context import (
    ContextBudget,
    ContextReductionScope,
    DefaultContextAssembler,
    InMemoryConversationSummaryStore,
    PersistentSummaryContextReducer,
)
from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
from sagents.v2.context.summary import SummarizationRequest
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import TextBlock, ImageBlock
from sagents.v2.model import (
    ModelCapabilities,
    ModelEventKind,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.model.recovery import (
    adaptive_summary,
    model_call_budget,
    consume_model_call,
)
from sagents.v2.context.auxiliary import stream_auxiliary_model


def message(text, role="assistant", **kwargs):
    return ModelMessage(role=role, content=(TextBlock(text=text),), **kwargs)


def scope(*, force=True, key="session"):
    return ContextReductionScope(
        context_key=key, session_id=key, run_id=key, force=force
    )


def error(
    code="model.context_window_exceeded",
    category=ErrorCategory.VALIDATION,
    retryable=False,
):
    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=category,
            message=code,
            retryable=retryable,
            safe_to_resume=True,
        )
    )


def command():
    return StartRun(
        agent_id="agent",
        input=(InputItem(role="user", content=(TextBlock(text="current"),)),),
        resolved_spec_hash="sha256:test",
        idempotency_key="start",
    )


class Summary:
    def __init__(self, text="compressed facts"):
        self.requests = []
        self.text = text

    async def summarize(self, request):
        self.requests.append(request)
        return self.text


class FragmentModel:
    """Reject from provider feedback, rather than a preflight token estimate."""

    def __init__(self, limit=1800, fail_at=None):
        self.limit, self.fail_at = limit, fail_at
        self.calls, self.closed = [], 0

    async def capabilities(self, binding):
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=True,
            supports_reasoning=False,
            supports_multimodal_input=True,
            supports_structured_output=True,
            max_output_tokens=8192,
        )

    async def stream(self, request):
        self.calls.append(request)
        try:
            if self.fail_at == len(self.calls):
                raise error(
                    "model.authentication_failed", ErrorCategory.PROVIDER_PERMANENT
                )
            text = request.messages[-1].content[0].text
            if len(text) > self.limit:
                raise error()
            payload = {key: [] for key in ModelConversationSummarizer._FIELDS}
            payload["summary"] = "facts preserved"
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="response",
                    finish_reason="stop",
                    text=json.dumps(payload),
                ),
            )
        finally:
            self.closed += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 1, 256, 10_000, 100_000])
@pytest.mark.parametrize("maximum", [1, 64, 128_000])
async def test_no_input_is_locally_rejected_or_compressed(size, maximum):
    summary = Summary()
    assembler = DefaultContextAssembler(
        budget=ContextBudget(max_input_tokens=maximum),
        reducer=PersistentSummaryContextReducer(
            InMemoryConversationSummaryStore(), summarizer=summary
        ),
    )
    original = (message("界" * size, "user"),)
    projection = await assembler.prepare_projection(command(), original, run_id="run")
    assert projection.messages == original
    assert not summary.requests
    assert original[0].content[0].text == "界" * size


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "usage,expected",
    [(0, False), (799, False), (800, True), (801, True), (100_000, True)],
)
async def test_configured_limit_uses_actual_usage_with_declared_output_reserve(
    usage, expected
):
    summary = Summary()
    assembler = DefaultContextAssembler(
        budget=ContextBudget(max_input_tokens=1000, reserve_output_tokens=200),
        reducer=PersistentSummaryContextReducer(
            InMemoryConversationSummaryStore(), summarizer=summary
        ),
    )
    source = (message("old facts " * 300), message("current", "user"))
    assembler.observe_usage("run", usage)
    await assembler.prepare_projection(command(), source, run_id="run")
    assert bool(summary.requests) == expected
    # The trigger is consumed once; an identical request reuses its checkpoint.
    await assembler.prepare_projection(command(), source, run_id="run")
    assert len(summary.requests) == int(expected)


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_count", [1, 2, 3, 8, 31])
async def test_compression_reuses_checkpoint_and_never_mutates_canonical_source(
    prior_count,
):
    summary, store = Summary(), InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(store, summarizer=summary)
    source = tuple(message(f"fact{i} " * 200) for i in range(prior_count)) + (
        message("exact current request", "user"),
    )
    original = tuple(m.model_dump_json() for m in source)
    projected = await reducer.reduce(source, scope=scope())
    saved = await store.get("session")
    assert saved is not None
    assert projected.historical_messages == source[: saved.source_message_count]
    assert projected.messages[-1] == source[-1]
    reused = await reducer.reduce(source, scope=scope(force=False))
    assert reused.messages == projected.messages
    assert len(summary.requests) == 1
    assert tuple(m.model_dump_json() for m in source) == original


@pytest.mark.asyncio
@pytest.mark.parametrize("trigger", ["usage", "overflow"])
@pytest.mark.parametrize("recent", [1, 4, 8])
async def test_pressure_compresses_completed_active_turn_batches_after_fork_history(
    trigger, recent
):
    summary, store = Summary(), InMemoryConversationSummaryStore()
    assembler = DefaultContextAssembler(
        system_instructions="Mandatory review instructions",
        budget=ContextBudget(max_input_tokens=1000, reserve_output_tokens=200),
        reducer=PersistentSummaryContextReducer(
            store, summarizer=summary, protected_recent_units=recent
        ),
    )
    current = message("Review the exact final version; do not generate media", "user")
    source = [
        message("Inherited production request", "user"),
        message("Inherited production findings " * 100),
        current,
    ]
    batches = []
    for index in range(13):
        calls = tuple(
            ModelToolCall(tool_call_id=f"call_{index}_{n}", name="inspect", arguments={})
            for n in range(2)
        )
        batch = (
            ModelMessage(role="assistant", tool_calls=calls),
            *(
                message(
                    f"Verified result {index} " * 100,
                    "tool",
                    tool_call_id=call.tool_call_id,
                )
                for call in calls
            ),
            ModelMessage(
                role="user",
                content=(
                    ImageBlock(
                        uri=f"https://example.invalid/frame/{index}.png",
                        mime_type="image/png",
                    ),
                ),
                metadata={
                    "tool_context": True,
                    "source_tool_call_id": calls[0].tool_call_id,
                },
            ),
        )
        batches.append(batch)
        source.extend(batch)
    source = tuple(source)
    original = tuple(m.model_dump_json() for m in source)
    if trigger == "usage":
        assembler.observe_usage("run", 800)
    else:
        assembler.request_compression("run")

    projection = await assembler.prepare_projection(command(), source, run_id="run")

    retained = tuple(m for batch in batches[-recent:] for m in batch)
    cut = len(source) - len(retained)
    assert summary.requests[0].messages == source[:cut]
    assert projection.historical_messages == source[:cut]
    assert projection.messages[-len(retained) :] == retained
    assert current in projection.messages
    assert any(
        "Mandatory review instructions" in block.text
        for m in projection.messages
        if m.role == "system"
        for block in m.content
        if block.kind == "text"
    )
    assert sum(b.kind == "image" for m in projection.messages for b in m.content) == recent
    assert tuple(m.model_dump_json() for m in source) == original
    reused = await assembler.prepare_projection(command(), source, run_id="run")
    assert reused.messages == projection.messages
    assert len(summary.requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["empty", "expands", "permanent", "cancel"])
async def test_failed_summary_never_commits_even_a_partial_checkpoint(outcome):
    class Failing(Summary):
        async def summarize(self, request):
            if outcome == "permanent":
                raise error("model.denied", ErrorCategory.PROVIDER_PERMANENT)
            if outcome == "cancel":
                raise asyncio.CancelledError()
            return "" if outcome == "empty" else "expanded" * 10000

    store = InMemoryConversationSummaryStore()
    source = (message("facts " * 200), message("current", "user"))
    with pytest.raises((SageV2Error, asyncio.CancelledError)):
        await PersistentSummaryContextReducer(store, summarizer=Failing()).reduce(
            source, scope=scope()
        )
    assert await store.get("session") is None
    assert source[0].content[0].text == ("facts " * 200).strip()


@pytest.mark.asyncio
@pytest.mark.parametrize("calls", [1, 2, 4, 8])
async def test_summary_split_model_call_quota_is_strict(calls):
    model = FragmentModel(limit=0)
    with pytest.raises(SageV2Error) as exc:
        with model_call_budget() as budget:
            budget.remaining = calls
            await ModelConversationSummarizer(model).summarize(
                SummarizationRequest(
                    scope=scope(),
                    messages=(message("source " * 5000),),
                    target_tokens=64,
                )
            )
    assert exc.value.info.code == "model.context_recovery_exhausted"
    assert len(model.calls) == calls == model.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [1200, 1800, 2500])
async def test_summary_tries_complete_source_then_splits_and_merges(limit):
    model = FragmentModel(limit=limit)
    source = "prefix facts " * 200 + "tail facts " * 200
    summary = await ModelConversationSummarizer(model).summarize(
        SummarizationRequest(
            scope=scope(),
            messages=(message(source),),
            previous_summary="previous facts",
            target_tokens=64,
        )
    )
    assert summary.strip()
    assert source.strip() in model.calls[0].messages[-1].content[0].text
    assert "previous facts" in model.calls[0].messages[-1].content[0].text
    assert len(model.calls) >= 3
    assert model.closed == len(model.calls) <= 64
    successful_sources = [
        r.messages[-1].content[0].text
        for r in model.calls
        if len(r.messages[-1].content[0].text) <= limit
    ]
    assert any("prefix facts" in s for s in successful_sources)
    assert any("tail facts" in s for s in successful_sources)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "expanded"])
async def test_split_empty_or_expanding_summary_stops_without_loop(bad):
    attempts = []

    async def summarize(value):
        attempts.append(value)
        if len(value) > 10:
            raise error()
        return "" if not bad else "expanded" * 20

    with pytest.raises(SageV2Error):
        await adaptive_summary("a" * 20, summarize)
    assert len(attempts) <= 3


@pytest.mark.asyncio
async def test_parallel_tool_results_and_media_are_one_atomic_coverage_unit():
    calls = tuple(
        ModelToolCall(tool_call_id=f"call{i}", name="read", arguments={})
        for i in range(4)
    )
    batch = (
        ModelMessage(role="assistant", tool_calls=calls),
        *(message("result " * 300, "tool", tool_call_id=c.tool_call_id) for c in calls),
        ModelMessage(
            role="user",
            content=(
                ImageBlock(uri="data:image/png;base64,AA==", mime_type="image/png"),
            ),
            metadata={"tool_context": True, "source_tool_call_id": "call0"},
        ),
    )
    source = (*batch, message("next user", "user"))
    summary, store = Summary(), InMemoryConversationSummaryStore()
    projection = await PersistentSummaryContextReducer(
        store, summarizer=summary
    ).reduce(source, scope=scope())
    assert summary.requests[0].messages == batch
    assert projection.historical_messages == batch
    assert projection.messages[-1] == source[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["mandatory", "界" * 1000])
async def test_irreducible_current_request_is_retained_and_stops(text):
    source = (message(text, "user"),)
    store = InMemoryConversationSummaryStore()
    with pytest.raises(SageV2Error, match="no completed history"):
        await PersistentSummaryContextReducer(store).reduce(source, scope=scope())
    assert await store.get("session") is None
    assert source[0].content[0].text == text


@pytest.mark.asyncio
async def test_cancel_during_second_fragment_does_not_commit_first_fragment():
    class CancelModel(FragmentModel):
        async def stream(self, request):
            if len(self.calls) == 2:
                raise asyncio.CancelledError()
            async for event in super().stream(request):
                yield event

    store, model = InMemoryConversationSummaryStore(), CancelModel(limit=1500)
    source = (message("historical fact " * 400), message("current", "user"))
    with pytest.raises(asyncio.CancelledError):
        await PersistentSummaryContextReducer(
            store, summarizer=ModelConversationSummarizer(model)
        ).reduce(source, scope=scope())
    assert await store.get("session") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["permanent", "overflow", "transient", "cancel"])
async def test_auxiliary_recovery_preserves_schema_and_never_executes_tools(
    failure, monkeypatch
):
    async def no_sleep(seconds):
        pass

    monkeypatch.setattr("sagents.v2.model.recovery.asyncio.sleep", no_sleep)

    class Model(FragmentModel):
        async def stream(self, request):
            if request.metadata.get("purpose") == "conversation_summary":
                async for event in super().stream(request):
                    yield event
                return
            self.calls.append(request)
            if failure == "cancel":
                raise asyncio.CancelledError()
            if failure == "permanent":
                raise error("model.auth", ErrorCategory.PROVIDER_PERMANENT)
            if (
                request.metadata.get("context_recovery_attempt") is None
                and failure == "overflow"
            ):
                raise error()
            if len(self.calls) == 1 and failure == "transient":
                raise error("model.busy", ErrorCategory.PROVIDER_TRANSIENT, True)
            assert request.response_schema == {"type": "object"}
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="response",
                    finish_reason="stop",
                    text="done",
                    tool_calls=(
                        ModelToolCall(
                            tool_call_id="never_execute", name="write", arguments={}
                        ),
                    ),
                ),
            )

    model = Model(limit=10000)
    request = ModelRequest(
        request_id="req",
        run_id="run",
        model_binding="primary",
        messages=(message("instructions", "system"), message("history " * 500, "user")),
        response_schema={"type": "object"},
    )
    if failure in {"permanent", "cancel"}:
        with pytest.raises((SageV2Error, asyncio.CancelledError)):
            _ = [e async for e in stream_auxiliary_model(model, request)]
        assert len(model.calls) == 1
    else:
        events = [e async for e in stream_auxiliary_model(model, request)]
        assert len(events) == 1 and events[0].response.text == "done"
        assert request.messages[-1].content[0].text == ("history " * 500).strip()
        assert len(model.calls) == (3 if failure == "overflow" else 2)


@pytest.mark.asyncio
async def test_shared_call_quota_is_task_local_and_resets_after_error():
    async def task(limit):
        with model_call_budget() as budget:
            budget.remaining = limit
            for _ in range(limit):
                consume_model_call()
                await asyncio.sleep(0)
            with pytest.raises(SageV2Error):
                consume_model_call()
            return budget.remaining

    assert await asyncio.gather(task(1), task(5)) == [0, 0]
    with model_call_budget() as fresh:
        assert fresh.remaining == 64


@pytest.mark.asyncio
async def test_usage_pressure_alone_does_not_fail_an_irreducible_request():
    assembler = DefaultContextAssembler(budget=ContextBudget(max_input_tokens=1))
    source = (message("exact user input", "user"),)
    assembler.observe_usage("run", 10000)
    assert (await assembler.prepare_messages(command(), source, run_id="run")) == source
    assembler.request_compression("run")
    with pytest.raises(SageV2Error, match="no completed history"):
        await assembler.prepare_messages(command(), source, run_id="run")


@pytest.mark.asyncio
async def test_identical_reference_projection_is_not_sent_twice_after_rejection():
    call = ModelToolCall(tool_call_id="tool", name="read", arguments={})
    source = (
        message("inspect", "user"),
        ModelMessage(role="assistant", tool_calls=(call,)),
        message(
            "result " * 500,
            "tool",
            tool_call_id="tool",
            metadata={"context_reference": {"uri": "artifact://durable/result"}},
        ),
    )
    assembler = DefaultContextAssembler()
    await assembler.prepare_messages(command(), source, run_id="run")
    assembler.request_compression("run")
    first = await assembler.prepare_messages(command(), source, run_id="run")
    assert first[-1].metadata["context_compacted_to_reference"]
    assembler.request_compression("run")
    second = await assembler.prepare_messages(command(), source, run_id="run")
    assert second != first
    assembler.request_compression("run")
    with pytest.raises(SageV2Error):
        await assembler.prepare_messages(command(), source, run_id="run")


@pytest.mark.asyncio
@pytest.mark.parametrize("results", [1, 2, 8, 32])
async def test_single_oversized_current_parallel_batch_can_be_summarized_atomically(
    results,
):
    calls = tuple(
        ModelToolCall(tool_call_id=f"call{i}", name="read", arguments={})
        for i in range(results)
    )
    source = (
        message("exact current request", "user"),
        ModelMessage(role="assistant", tool_calls=calls),
        *(
            message("large result " * 500, "tool", tool_call_id=c.tool_call_id)
            for c in calls
        ),
    )
    store, summary = InMemoryConversationSummaryStore(), Summary()
    projection = await PersistentSummaryContextReducer(
        store, summarizer=summary
    ).reduce(source, scope=scope())
    assert projection.historical_messages == source
    assert projection.messages[-1] == source[0]
    assert summary.requests[0].messages == source
    assert (await store.get("session")).source_message_count == len(source)


@pytest.mark.asyncio
async def test_old_summary_can_shrink_without_claiming_additional_canonical_coverage():
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(
        store, summarizer=Summary("old summary " * 50)
    )
    source = (message("original facts " * 3000), message("current", "user"))
    await reducer.reduce(source, scope=scope())
    previous = await store.get("session")
    reducer.summarizer = Summary("shorter facts")
    projection = await reducer.reduce(source, scope=scope())
    current = await store.get("session")
    assert current.revision == previous.revision + 1
    assert current.covered_message_digests == previous.covered_message_digests
    assert reducer.summarizer.requests[0].previous_summary == previous.text
    assert projection.messages[-1] == source[-1]


@pytest.mark.asyncio
@pytest.mark.parametrize("indices", [(), (0, 0), (0, 5), (-1, 1), (1, 0)])
async def test_bad_canonical_mapping_never_claims_unprocessed_history(indices):
    source = (message("a " * 500), message("current", "user"))
    store = InMemoryConversationSummaryStore()
    mapped = scope().model_copy(
        update={"canonical_messages": source, "canonical_indices": indices}
    )
    with pytest.raises(SageV2Error) as exc:
        await PersistentSummaryContextReducer(store, summarizer=Summary()).reduce(
            source, scope=mapped
        )
    assert exc.value.info.code == "context.invalid_source_mapping"
    assert await store.get("session") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("argument_key", ["image", "query"])
async def test_summary_source_redacts_media_in_tool_arguments_without_changing_history(
    argument_key,
):
    data = "data:image/png;base64," + "A" * 2000
    source = (
        ModelMessage(
            role="assistant",
            tool_calls=(
                ModelToolCall(
                    tool_call_id="call", name="image", arguments={argument_key: data}
                ),
            ),
        ),
        message(data, "tool", tool_call_id="call"),
    )
    model = FragmentModel(limit=10000)
    result = await ModelConversationSummarizer(model).summarize(
        SummarizationRequest(scope=scope(), messages=source, target_tokens=64)
    )
    serialized = model.calls[0].messages[-1].content[0].text
    assert "A" * 100 not in serialized
    assert "A" * 100 not in result
    assert source[0].tool_calls[0].arguments[argument_key] == data
    assert source[1].content[0].text == data


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reported,input_tokens,cached,compress",
    [
        (False, 2000, 0, False),
        (True, 799, 700, False),
        (True, 800, 700, True),
        (True, 1000, 0, True),
    ],
)
async def test_step_builder_uses_only_reported_total_input_usage(
    reported, input_tokens, cached, compress
):
    from sagents.v2.agent.step_request import DefaultAgentStepRequestBuilder
    from sagents.v2.contracts.items import UsageSummary
    from sagents.v2.tool import DirectToolSelectionPolicy, InMemoryToolCatalog

    assembler = DefaultContextAssembler(
        budget=ContextBudget(max_input_tokens=1000, reserve_output_tokens=200)
    )
    builder = DefaultAgentStepRequestBuilder(
        context_assembler=assembler,
        tool_catalog=InMemoryToolCatalog(()),
        tool_selection_policy=DirectToolSelectionPolicy(),
    )
    request = ModelRequest(
        request_id="request",
        run_id="run",
        model_binding="primary",
        messages=(message("x", "user"),),
    )
    builder.observe_response(
        request,
        ModelResponse(
            response_id="response",
            text="done",
            finish_reason="stop",
            usage=UsageSummary(
                reported=reported, input_tokens=input_tokens, cached_input_tokens=cached
            ),
        ),
    )
    assert ("run" in assembler._compression_requested) == compress


def test_estimator_plugins_and_default_selections_are_removed():
    from sagents.v2.runtime.extensions.official import builtin_extension_registry
    from sagents.v2.composition.defaults import DEFAULT_COMPONENTS
    from sagents.v2.package.manifest.runtime import RuntimeConfig
    import sagents.v2.context as context

    assert not any(
        "token-estimator" in p["plugin_id"]
        for p in builtin_extension_registry().inventory()
    )
    assert "context.token-estimator" not in DEFAULT_COMPONENTS
    assert not any("Estimator" in name for name in context.__all__)
    old = RuntimeConfig(
        capabilities={
            "context.token-estimator": {
                "plugin": "sage.context.token-estimator.tiktoken"
            }
        }
    )
    assert old.capabilities == {}


@pytest.mark.asyncio
async def test_later_permanent_fragment_failure_keeps_previous_checkpoint():
    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(store, summarizer=Summary())
    source = (message("facts " * 1000), message("first request", "user"))
    await reducer.reduce(source, scope=scope())
    previous = await store.get("session")
    model = FragmentModel(limit=2000, fail_at=3)
    reducer.summarizer = ModelConversationSummarizer(model)
    extended = (
        *source,
        message("more facts " * 1000),
        message("second request", "user"),
    )
    with pytest.raises(SageV2Error):
        await reducer.reduce(
            extended,
            ContextBudget(max_input_tokens=10000, max_messages=2),
            scope=scope(),
        )
    assert await store.get("session") == previous
    assert len(model.calls) == model.closed == 3


@pytest.mark.asyncio
async def test_auxiliary_completed_event_is_authoritative_even_if_eof_stalls():
    class Stalls:
        closed = False

        async def stream(self, request):
            try:
                yield ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id="r", text="done", finish_reason="stop"
                    ),
                )
                await asyncio.Event().wait()
            finally:
                self.closed = True

    model = Stalls()
    request = ModelRequest(
        request_id="r",
        run_id="run",
        model_binding="primary",
        messages=(message("input", "user"),),
    )
    async with asyncio.timeout(0.5):
        events = [e async for e in stream_auxiliary_model(model, request)]
    assert events[0].response.text == "done"
    assert model.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("recover", [False, True])
async def test_summary_transport_eof_retries_have_a_hard_limit(recover, monkeypatch):
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(
        "sagents.v2.context.plugins.summarizer_model.asyncio.sleep", sleep
    )

    class EOF(FragmentModel):
        async def stream(self, request):
            if recover and len(self.calls) == 3:
                stream = super().stream(request)
                try:
                    async for event in stream:
                        yield event
                finally:
                    await stream.aclose()
                return
            self.calls.append(request)
            self.closed += 1
            yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="partial")

    model = EOF(limit=10000)
    request = SummarizationRequest(
        scope=scope(), messages=(message("facts"),), target_tokens=64
    )
    if recover:
        assert await ModelConversationSummarizer(model).summarize(request)
    else:
        with pytest.raises(SageV2Error) as exc:
            await ModelConversationSummarizer(model).summarize(request)
        assert exc.value.info.code == "model.stream_incomplete"
    assert len(model.calls) == model.closed == 4
    assert delays == [2, 4, 8]


@pytest.mark.asyncio
async def test_window_retries_advance_and_rewritten_history_invalidates_its_view():
    from sagents.v2.context.plugins.window import WindowContextReducer

    reducer = WindowContextReducer()
    source = tuple(message("fact " + str(i)) for i in range(20)) + (
        message("current", "user"),
    )
    first = await reducer.reduce(source, scope=scope())
    second = await reducer.reduce(source, scope=scope())
    assert second.dropped_message_count > first.dropped_message_count
    assert second.messages[-1] == source[-1]
    replay = await reducer.reduce(source, scope=scope(force=False))
    assert replay.messages == second.messages
    rewritten = (message("replacement"), *source[1:])
    reset = await reducer.reduce(rewritten, scope=scope(force=False))
    assert reset.messages == rewritten


def test_legacy_plugin_settings_do_not_resurrect_input_estimators():
    from sagents.v2.package.manifest.runtime import CapabilitySelection
    from sagents.v2.package.manifest.root import PluginDeclaration, SageManifest

    selection = CapabilitySelection(
        plugin="sage.skill.loading.lazy",
        config={"max_active_tokens": 200, "max_active_characters": 4000},
    )
    assert selection.config == {"max_active_characters": 4000}
    declaration = PluginDeclaration(
        id="sage.skill.loading.lazy", config={"max_active_tokens": 1000}
    )
    assert declaration.config == {}
    from sagents.v2.package.presets import BuiltinPackageFactory

    data = BuiltinPackageFactory.create("assistant", package_id="test").model_dump(
        mode="json"
    )
    data["plugins"] = [
        {"id": "sage.context.token-estimator.tiktoken"},
        {"id": "sage.skill.loading.lazy"},
    ]
    manifest = SageManifest.model_validate(data)
    assert tuple(p.id for p in manifest.plugins) == ("sage.skill.loading.lazy",)


@pytest.mark.asyncio
async def test_summary_configured_model_limit_splits_from_reported_usage_even_after_success():
    from sagents.v2.contracts.items import UsageSummary

    class Reported(FragmentModel):
        async def capabilities(self, binding):
            caps = await super().capabilities(binding)
            return caps.model_copy(update={"max_input_tokens": 1800})

        async def stream(self, request):
            async for event in super().stream(request):
                response = event.response.model_copy(
                    update={
                        "usage": UsageSummary(
                            reported=True,
                            input_tokens=len(request.messages[-1].content[0].text),
                        )
                    }
                )
                yield event.model_copy(update={"response": response})

    model = Reported(limit=100000)
    result = await ModelConversationSummarizer(model).summarize(
        SummarizationRequest(
            scope=scope(), messages=(message("facts " * 1000),), target_tokens=64
        )
    )
    assert result
    assert len(model.calls) >= 3
    assert len(model.calls[0].messages[-1].content[0].text) > 1800


@pytest.mark.asyncio
async def test_auxiliary_configured_model_limit_compresses_accepted_large_response():
    from sagents.v2.contracts.items import UsageSummary

    class Reported(FragmentModel):
        async def capabilities(self, binding):
            caps = await super().capabilities(binding)
            return caps.model_copy(update={"max_input_tokens": 2000})

        async def stream(self, request):
            if request.metadata.get("purpose") == "conversation_summary":
                async for event in super().stream(request):
                    yield event
                return
            self.calls.append(request)
            yield ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id="r",
                    finish_reason="stop",
                    text="accepted",
                    usage=UsageSummary(
                        reported=True,
                        input_tokens=3000
                        if not request.metadata.get("context_recovery_attempt")
                        else 200,
                    ),
                ),
            )

    model = Reported(limit=100000)
    request = ModelRequest(
        request_id="r",
        run_id="run",
        model_binding="primary",
        messages=(message("history " * 500, "user"),),
    )
    events = [e async for e in stream_auxiliary_model(model, request)]
    assert len(events) == 1
    assert model.calls[-1].metadata["context_recovery_attempt"] == 1
    assert len(model.calls) == 3


@pytest.mark.asyncio
async def test_concurrent_identical_compressions_reuse_the_winning_complete_checkpoint():
    arrived = 0
    barrier = asyncio.Event()

    class Concurrent(Summary):
        async def summarize(self, request):
            nonlocal arrived
            arrived += 1
            if arrived == 2:
                barrier.set()
            await barrier.wait()
            return "complete facts"

    store = InMemoryConversationSummaryStore()
    reducer = PersistentSummaryContextReducer(store, summarizer=Concurrent())
    source = (message("facts " * 1000), message("current", "user"))
    first, second = await asyncio.gather(
        reducer.reduce(source, scope=scope()), reducer.reduce(source, scope=scope())
    )
    assert first.messages == second.messages
    saved = await store.get("session")
    assert saved.revision == 1
    assert first.historical_messages == source[: saved.source_message_count]


@pytest.mark.asyncio
async def test_auxiliary_repeated_overflow_stops_after_six_recovery_attempts(
    monkeypatch,
):
    class Reject:
        calls = 0

        async def stream(self, request):
            self.calls += 1
            raise error()
            yield

    class Shrink:
        def __init__(self, model):
            pass

        async def summarize(self, request):
            text = request.messages[0].content[0].text
            return text[: len(text) // 2]

    monkeypatch.setattr(
        "sagents.v2.context.plugins.summarizer_model.ModelConversationSummarizer",
        Shrink,
    )
    model = Reject()
    request = ModelRequest(
        request_id="r",
        run_id="run",
        model_binding="primary",
        messages=(message("x" * 65536, "user"),),
    )
    with pytest.raises(SageV2Error) as exc:
        _ = [e async for e in stream_auxiliary_model(model, request)]
    assert exc.value.info.code == "model.context_window_exceeded"
    assert model.calls == 7
    assert len(request.messages[0].content[0].text) == 65536


def test_structured_split_merge_preserves_both_edge_identifiers_and_full_field_lists():
    first = {key: [] for key in ModelConversationSummarizer._FIELDS}
    first.update(
        summary="验收码 ORION-731",
        user_requirements=["保留 ORION-731"],
        tool_outcomes={"read a": {"status": "completed"}},
        todo_state_at_compaction_boundary=[{"content": "old", "status": "pending"}],
    )
    second = {key: [] for key in ModelConversationSummarizer._FIELDS}
    second.update(
        summary="交付码 LIME-409",
        user_requirements=["保留 LIME-409"],
        tool_outcomes={"read b": {"status": "completed"}},
        todo_state_at_compaction_boundary=[{"content": "new", "status": "completed"}],
    )
    result = json.loads(
        ModelConversationSummarizer._merge_payloads(
            json.dumps(first), json.dumps(second)
        )
    )
    assert "ORION-731" in result["summary"] and "LIME-409" in result["summary"]
    assert result["user_requirements"] == ["保留 ORION-731", "保留 LIME-409"]
    assert set(result["tool_outcomes"]) == {"read a", "read b"}
    assert (
        result["todo_state_at_compaction_boundary"]
        == second["todo_state_at_compaction_boundary"]
    )
