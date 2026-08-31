from __future__ import annotations

import json

import pytest

from sagents.v2.context import (
    ContextBudget,
    ContextReductionScope,
    InMemoryConversationSummaryStore,
    ModelConversationSummarizer,
    PersistentSummaryContextReducer,
)
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
from sagents.v2.contracts.items import TextBlock, UsageSummary


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
    assert stored.revision == 1
    assert summarizer.requests[-1].previous_summary is None


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

    assert caught.value.info.code == "context.summary_not_reducing"
    assert await store.get("session_1") is None


@pytest.mark.asyncio
async def test_latest_real_user_and_everything_after_it_are_never_summarized():
    reducer = PersistentSummaryContextReducer(
        InMemoryConversationSummaryStore(),
        summarizer=RecordingSummarizer(),
        protected_recent_units=1,
    )
    source = (
        ModelMessage(
            role="user", content=(TextBlock(text="old question " * 100),)
        ),
        ModelMessage(
            role="assistant", content=(TextBlock(text="old answer " * 100),)
        ),
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
        scope=scope(),
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

    assert json.loads(value) == payload
    assert len(model.requests) == 2
    assert model.requests[0].response_schema is not None
    assert model.requests[1].metadata == {
        "purpose": "conversation_summary",
        "attempt": 2,
    }
