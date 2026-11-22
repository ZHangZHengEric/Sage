from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from sagents.v2.session_memory.contracts import SessionMemoryProvider
    from sagents.v2.tool.official.runtime import OfficialToolRuntime

from types import SimpleNamespace

import pytest

from sagents.v2.context import ContextProjection
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.model import ModelMessage, ModelToolCall
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.session_memory import (
    NoopSessionMemoryProvider,
    SessionMemoryQuery,
    SessionMemoryRecord,
    SessionMemoryService,
    SessionMemoryHit,
    SqliteBm25SessionMemoryProvider,
)
from sagents.v2.tool import ToolCall, ToolInvocation
from sagents.v2.tool.official.memory import MemoryTools


@pytest.mark.asyncio
async def test_verified_summary_reuses_history_ids_without_losing_provenance(monkeypatch):
    from sagents.v2.context.summary import active_summary_validation, message_digest, reuse_summary_validation

    service = SessionMemoryService(NoopSessionMemoryProvider())
    original = ModelMessage(
        role="user", content=(TextBlock(text="historical text"),),
        metadata={"source_item_id": "original"},
    )
    reconstructed = original.model_copy(update={"metadata": {"source_item_id": "reconstructed"}})
    record_id = service.record_id
    hashed = []

    def track(message):
        hashed.append(message)
        return record_id(message)

    monkeypatch.setattr(service, "record_id", track)

    async def observe(message):
        await service.observe_projection(
            "run",
            ContextProjection(messages=(), historical_messages=(message,), source_message_count=1),
            session_id="session",
        )

    with reuse_summary_validation("run"):
        validation = active_summary_validation.get()
        assert validation is not None
        validation.remember((message_digest(original),), (original,))
        await observe(original)
        await observe(original)
        assert hashed == [original]
        assert service._boundaries["run"].historical == {"original"}

        assert message_digest(original) == message_digest(reconstructed)
        await observe(reconstructed)
        assert hashed == [original, reconstructed]
        assert service._boundaries["run"].historical == {"reconstructed"}


@pytest.mark.asyncio
async def test_sqlite_session_memory_is_incremental_scoped_and_excludable(tmp_path):
    provider = SqliteBm25SessionMemoryProvider(tmp_path / "session-memory")
    old = SessionMemoryRecord(
        record_id="old",
        session_id="session_1",
        role="user",
        content="The historic deployment used a canary release.",
        position=0,
    )
    current = SessionMemoryRecord(
        record_id="current",
        session_id="session_1",
        role="user",
        content="The current deployment also discusses canary release.",
        position=1,
    )
    await provider.sync((old, current))
    await provider.sync((old, current))

    hits = await provider.recall(
        SessionMemoryQuery(
            session_id="session_1",
            run_id="run_1",
            text="canary deployment",
            included_record_ids=("old", "current"),
            excluded_record_ids=("current",),
        )
    )

    assert [hit.record.record_id for hit in hits] == ["old"]
    assert (
        await provider.recall(
            SessionMemoryQuery(
                session_id="session_2",
                run_id="run_2",
                text="canary deployment",
            )
        )
        == ()
    )
    await provider.forget_session("session_1")
    assert (
        await provider.recall(
            SessionMemoryQuery(
                session_id="session_1",
                run_id="run_1",
                text="canary deployment",
            )
        )
        == ()
    )


@pytest.mark.asyncio
async def test_sqlite_concurrent_writers_keep_single_search_row(tmp_path):
    providers = [SqliteBm25SessionMemoryProvider(tmp_path) for _ in range(2)]
    record = SessionMemoryRecord(
        record_id="shared", session_id="session", role="tool", content="canary", position=0,
    )
    query = SessionMemoryQuery(session_id="session", run_id="run", text="canary")
    await asyncio.gather(*(provider.sync((record,)) for provider in providers))
    updated = record.model_copy(update={"position": 2})
    await providers[0].sync((updated,))
    assert [hit.record for hit in await providers[1].recall(query)] == [updated]

    edited = updated.model_copy(update={"content": "stable"})
    await asyncio.gather(*(provider.sync((edited,)) for provider in providers))
    assert await providers[0].recall(query) == ()
    hits = await providers[1].recall(query.model_copy(update={"text": "stable"}))
    assert [hit.record for hit in hits] == [edited]


class _RecordingProvider:
    def __init__(self):
        self.recall_queries = []
        self.sync_batches = []

    async def sync(self, records):
        self.sync_batches.append(records)
        self.records = records

    async def recall(self, query):
        self.recall_queries.append(query)
        return ()

    async def forget_session(self, session_id):
        del session_id


@pytest.mark.asyncio
async def test_session_memory_service_returns_only_messages_absent_from_request(
    tmp_path,
):
    old = ModelMessage(
        role="user",
        content=(TextBlock(text="The old release codename was Saturn."),),
        metadata={"source_item_id": "item_old", "source_run_id": "run_old"},
    )
    current = ModelMessage(
        role="user",
        content=(TextBlock(text="What was the release codename?"),),
        metadata={"source_item_id": "item_current", "source_run_id": "run_1"},
    )
    current_search_call = ModelMessage(
        role="assistant",
        content=(),
        tool_calls=(
            ModelToolCall(
                tool_call_id="call_1",
                name="search_memory",
                arguments={"query": "release codename Saturn"},
            ),
        ),
        metadata={"source_item_id": "item_search", "source_run_id": "run_1"},
    )
    ledger = (old, current, current_search_call)
    service = SessionMemoryService(
        SqliteBm25SessionMemoryProvider(tmp_path / "session-memory"),
    )
    await service.observe_projection(
        "run_1",
        ContextProjection(
            messages=(current,),
            historical_messages=(old,),
            estimated_tokens=10,
            source_message_count=2,
        ),
        session_id="session_1",
        source_messages=ledger,
    )

    hits = await service.recall(
        run_id="run_1",
        session_id="session_1",
        text="release codename Saturn",
        limit=5,
        tool_call_id="call_1",
    )
    assert [hit.record.record_id for hit in hits] == ["item_old"]

    await service.observe_projection(
        "run_1",
        ContextProjection(
            messages=(old, current), estimated_tokens=20, source_message_count=2
        ),
        session_id="session_1",
        source_messages=ledger,
    )
    assert (
        await service.recall(
            run_id="run_1",
            session_id="session_1",
            text="release codename Saturn",
            limit=5,
            tool_call_id="call_1",
        )
        == ()
    )


@pytest.mark.asyncio
async def test_session_memory_never_infers_history_when_reducer_declares_none():
    old = ModelMessage(
        role="user",
        content=(TextBlock(text="Visible history"),),
        metadata={"source_item_id": "item_old"},
    )
    current = ModelMessage(
        role="user",
        content=(TextBlock(text="Current question"),),
        metadata={"source_item_id": "item_current"},
    )
    provider = _RecordingProvider()
    service = SessionMemoryService(provider)  # type: ignore[arg-type]

    assert (
        await service.recall(
            run_id="run_1",
            session_id="session_1",
            text="history",
            limit=5,
        )
        == ()
    )
    assert provider.recall_queries == []

    await service.observe_projection(
        "run_1",
        ContextProjection(
            # The old message is absent from the request, but the reducer did
            # not declare it as history. Session Memory must not guess.
            messages=(current,), estimated_tokens=20, source_message_count=2
        ),
        session_id="session_1",
        source_messages=(old, current),
    )

    assert (
        await service.recall(
            run_id="run_1",
            session_id="session_1",
            text="history",
            limit=5,
        )
        == ()
    )
    assert provider.recall_queries == []


@pytest.mark.asyncio
async def test_session_memory_rechecks_backend_hits_against_the_run_boundary():
    def old_item(item_id: str, role: Literal["user", "developer"] = "user"):
        return ModelMessage(
            role=role, content=(TextBlock(text=item_id),),
            metadata={"source_item_id": item_id},
        )

    class UnfilteredProvider(_RecordingProvider):
        async def recall(self, query):
            assert query.included_record_ids == ("valid",)
            return tuple(
                SessionMemoryHit(record=SessionMemoryRecord(
                    record_id=item_id, session_id=session_id, role=role,
                    content=item_id, position=0,
                ), score=1)
                for item_id, session_id, role in (
                    ("valid", "another_session", "user"),
                    ("instruction", "session_1", "developer"),
                    ("visible", "session_1", "user"),
                    ("valid", "session_1", "user"),
                )
            )

    service = SessionMemoryService(UnfilteredProvider())
    visible, valid, instruction = old_item("visible"), old_item("valid"), old_item("instruction", "developer")
    await service.observe_projection(
        "run_1",
        ContextProjection(
            messages=(visible,), historical_messages=(valid, instruction), source_message_count=3,
        ),
        session_id="session_1", source_messages=(valid, instruction, visible),
    )
    hits = await service.recall(run_id="run_1", session_id="session_1", text="any", limit=5)
    assert [(hit.record.session_id, hit.record.record_id) for hit in hits] == [("session_1", "valid")]


class _SessionSearch:
    async def recall(self, **kwargs):
        assert kwargs["tool_call_id"] == "call_1"
        return (
            SessionMemoryHit(
                record=SessionMemoryRecord(
                    record_id="item_old",
                    session_id="session_1",
                    role="user",
                    content="The old release codename was Saturn.",
                    position=0,
                ),
                score=0.8,
            ),
        )


@pytest.mark.asyncio
async def test_search_memory_can_return_session_results_without_long_term_provider():
    invocation = ToolInvocation(
        call=ToolCall(
            tool_call_id="call_1",
            tool_name="search_memory",
            arguments={"query": "release codename"},
            operation_id="operation_1",
            idempotency_key="key_1",
            owner_run_id="run_1",
            owner_agent_id="agent_1",
            owner_session_id="session_1",
        ),
        request_context=RequestContext(
            actor=ActorRef(
                principal_id="user_1",
                principal_type=PrincipalType.USER,
            )
        ),
    )
    result = await MemoryTools(
        cast('OfficialToolRuntime', SimpleNamespace(
            memory_service=None,
            session_memory_service=_SessionSearch(),
        ))
    ).search_memory("release codename", invocation=invocation)

    assert result["long_term_results"] == []
    assert result["results"] == result["session_results"]
    assert result["results"][0]["memory_type"] == "session"


@pytest.mark.parametrize(
    "implementation",
    [NoopSessionMemoryProvider, SqliteBm25SessionMemoryProvider],
)
def test_session_memory_plugin_id_matches_official_registry(implementation):
    registration = builtin_extension_registry().get(implementation.plugin_id)
    assert "session-memory.provider" in {
        offer.capability for offer in registration.descriptor.provides
    }


@pytest.mark.asyncio
async def test_session_memory_indexes_only_new_records_as_history_grows():
    """A growing Session must not re-sync its whole history on every request."""

    provider = _RecordingProvider()
    service = SessionMemoryService(provider)  # type: ignore[arg-type]

    def message(index: int) -> ModelMessage:
        return ModelMessage(
            role="user",
            content=(TextBlock(text=f"turn {index}"),),
            metadata={"source_item_id": f"item_{index}"},
        )

    ledger = (message(0), message(1))
    await service.observe_projection(
        "run_1",
        ContextProjection(
            messages=ledger, estimated_tokens=10, source_message_count=2
        ),
        session_id="session_1",
        source_messages=ledger,
    )
    assert [
        tuple(record.record_id for record in batch) for batch in provider.sync_batches
    ] == [("item_0", "item_1")]

    # Same ledger observed again: nothing changed, so nothing is handed over.
    await service.observe_projection(
        "run_1",
        ContextProjection(
            messages=ledger, estimated_tokens=10, source_message_count=2
        ),
        session_id="session_1",
        source_messages=ledger,
    )
    assert len(provider.sync_batches) == 1

    grown = (*ledger, message(2), message(3))
    await service.observe_projection(
        "run_1",
        ContextProjection(
            messages=grown, estimated_tokens=20, source_message_count=4
        ),
        session_id="session_1",
        source_messages=grown,
    )
    assert tuple(
        record.record_id for record in provider.sync_batches[1]
    ) == ("item_2", "item_3")


@pytest.mark.asyncio
async def test_session_memory_does_not_revisit_an_observed_run_prefix():
    class CountingSessionMemoryService(SessionMemoryService):
        def __init__(self, provider):
            super().__init__(provider)
            self.recorded_batches = []

        def _records(self, session_id, messages, *, start_position=0):
            self.recorded_batches.append(
                (start_position, tuple(message.metadata["source_item_id"] for message in messages))
            )
            return super()._records(
                session_id,
                messages,
                start_position=start_position,
            )

    provider = _RecordingProvider()
    service = CountingSessionMemoryService(cast('SessionMemoryProvider', provider))

    def message(index: int) -> ModelMessage:
        return ModelMessage(
            role="user",
            content=(TextBlock(text=f"turn {index}"),),
            metadata={"source_item_id": f"item_{index}"},
        )

    first = (message(0), message(1))
    await service.observe_projection(
        "run_1",
        ContextProjection(messages=first, estimated_tokens=2, source_message_count=2),
        session_id="session_1",
        source_messages=first,
    )
    await service.observe_projection(
        "run_1",
        ContextProjection(messages=first, estimated_tokens=2, source_message_count=2),
        session_id="session_1",
        source_messages=first,
    )
    grown = (*first, message(2))
    await service.observe_projection(
        "run_1",
        ContextProjection(messages=grown, estimated_tokens=3, source_message_count=3),
        session_id="session_1",
        source_messages=grown,
    )

    assert service.recorded_batches == [
        (0, ("item_0", "item_1")),
        (2, ("item_2",)),
    ]


@pytest.mark.asyncio
async def test_session_memory_indexes_through_the_context_assembler(tmp_path):
    """The assembler is the only production indexing trigger; prove it feeds it."""

    from sagents.v2.context import ContextBudget, DefaultContextAssembler

    old = ModelMessage(
        role="user",
        content=(TextBlock(text="The old release codename was Saturn."),),
        metadata={"source_item_id": "item_old"},
    )
    current = ModelMessage(
        role="user",
        content=(TextBlock(text="Remind me of the codename."),),
        metadata={"source_item_id": "item_current"},
    )

    class _DroppingReducer:
        """Stand in for a reducer that evicts the oldest turn from the request."""

        async def reduce(self, messages, budget, *, scope=None):
            del budget, scope
            kept = tuple(m for m in messages if m.metadata.get("source_item_id") != "item_old")
            return ContextProjection(
                messages=kept,
                historical_messages=(old,),
                estimated_tokens=1,
                source_message_count=len(messages),
            )

    class _Reader:
        async def get_run(self, run_id):
            del run_id
            return SimpleNamespace(
                run_id="run_1",
                session_id="session_1",
                concurrency_mode=None,
                base_session_sequence=0,
            )

    service = SessionMemoryService(
        SqliteBm25SessionMemoryProvider(tmp_path / "session-memory")
    )
    assembler = DefaultContextAssembler(
        budget=ContextBudget(max_input_tokens=1_000),
        reducer=_DroppingReducer(),  # type: ignore[arg-type]
        history_reader=_Reader(),  # type: ignore[arg-type]
        projection_observer=service,
    )
    command = StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=current.content),),
        resolved_spec_hash="sha256:test",
        idempotency_key="start-assembler",
    )

    await assembler.prepare_projection(command, (old, current), run_id="run_1")

    hits = await service.recall(
        run_id="run_1",
        session_id="session_1",
        text="release codename Saturn",
        limit=5,
    )
    assert [hit.record.record_id for hit in hits] == ["item_old"]
