from __future__ import annotations

import asyncio
from contextlib import closing
import sqlite3
from types import SimpleNamespace

import pytest

from sagents.v2.agent.stream_batcher import StreamEventBatcher
from sagents.v2.context import ContextProjection
from sagents.v2.contracts.events import ItemEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.model import ModelMessage
from sagents.v2.runtime.session.contracts import EventDraft
from sagents.v2.session_memory import (
    SessionMemoryQuery,
    SessionMemoryRecord,
    SessionMemoryService,
    SqliteBm25SessionMemoryProvider,
)
from sagents.v2.memory import FilesystemBm25MemoryProvider


def record(index, content="deployment canary release"):
    return SessionMemoryRecord(
        record_id=f"record_{index}",
        session_id="session",
        role="user",
        content=content,
        position=index,
    )


@pytest.mark.asyncio
async def test_batch_commit_failure_is_sticky_for_waiting_producers():
    started = asyncio.Event()
    finish = asyncio.Event()
    calls = 0
    failure = RuntimeError("ambiguous storage failure")

    async def commit(run, drafts):
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        raise failure

    batcher = StreamEventBatcher(
        SimpleNamespace(revision=0), commit, max_delay_seconds=100
    )
    draft = EventDraft(
        type="message.delta", data=ItemEventData(operation="delta", delta="hello")
    )
    await batcher.add(draft)
    flush = asyncio.create_task(batcher.flush())
    await started.wait()
    waiting = asyncio.create_task(batcher.add(draft))
    await asyncio.sleep(0)
    finish.set()
    results = await asyncio.gather(flush, waiting, return_exceptions=True)
    assert results == [failure, failure]
    with pytest.raises(RuntimeError, match="ambiguous storage failure"):
        await batcher.flush()
    assert calls == 1


@pytest.mark.asyncio
async def test_sqlite_incremental_upsert_reads_only_target_keys_and_last_duplicate_wins(
    tmp_path, monkeypatch
):
    provider = SqliteBm25SessionMemoryProvider(tmp_path)
    original = record(0)
    await provider.sync(tuple(record(i) for i in range(200)))
    queries = []
    connect = provider._connect

    def tracked():
        connection = connect()
        connection.set_trace_callback(queries.append)
        return connection

    monkeypatch.setattr(provider, "_connect", tracked)
    await provider.sync((record(0, "different text"), original))
    selects = [query for query in queries if query.startswith("SELECT payload_json")]
    assert len(selects) == 2
    assert all("record_id = 'record_0'" in query for query in selects)
    hits = await provider.recall(
        SessionMemoryQuery(
            session_id="session",
            run_id="run",
            text="canary",
            included_record_ids=("record_0",),
        )
    )
    assert [hit.record for hit in hits] == [original]


@pytest.mark.asyncio
async def test_search_filters_in_database_before_decoding_or_applying_limit(
    tmp_path, monkeypatch
):
    provider = SqliteBm25SessionMemoryProvider(tmp_path)
    await provider.sync(tuple(record(i) for i in range(500)))
    decoded = []
    validate = SessionMemoryRecord.model_validate_json

    def track(payload):
        decoded.append(payload)
        return validate(payload)

    monkeypatch.setattr(SessionMemoryRecord, "model_validate_json", track)
    hits = await provider.recall(
        SessionMemoryQuery(
            session_id="session",
            run_id="run",
            text="canary",
            limit=2,
            included_record_ids=(
                "record_0",
                "record_1",
                "record_2",
                *(f"missing_{i}" for i in range(2000)),
            ),
            excluded_record_ids=("record_2",),
        )
    )
    assert [hit.record.record_id for hit in hits] == ["record_1", "record_0"]
    assert len(decoded) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("session_memory", [True, False])
async def test_memory_connections_close_without_waiting_for_garbage_collection(
    tmp_path, monkeypatch, session_memory
):
    connections = []
    connect = sqlite3.connect

    def tracked(*args, **kwargs):
        connection = connect(*args, **kwargs, check_same_thread=False)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked)
    if session_memory:
        provider = SqliteBm25SessionMemoryProvider(tmp_path)
        await provider.sync((record(0),))
        await provider.recall(
            SessionMemoryQuery(session_id="session", run_id="run", text="canary")
        )
        await provider.forget_session("session")
    else:
        provider = FilesystemBm25MemoryProvider(tmp_path)
        await provider.health()
    assert len(connections) >= 2
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


@pytest.mark.asyncio
async def test_memory_transaction_rolls_back_and_closes_on_failure(
    tmp_path, monkeypatch
):
    provider = SqliteBm25SessionMemoryProvider(tmp_path)
    await provider.sync((record(0),))
    connect = provider._connect
    original_tokenize = provider._tokenize

    def fail(text):
        if text == "fail":
            raise RuntimeError("tokenization failed")
        return original_tokenize(text)

    monkeypatch.setattr(provider, "_tokenize", fail)
    with pytest.raises(RuntimeError):
        await provider.sync((record(0, "changed"), record(1, "fail")))
    with closing(connect()) as connection:
        rows = connection.execute(
            "SELECT payload_json FROM session_memory_records"
        ).fetchall()
    assert [SessionMemoryRecord.model_validate_json(row[0]) for row in rows] == [
        record(0)
    ]


@pytest.mark.asyncio
async def test_recall_cannot_reuse_a_boundary_from_a_different_session():
    queries = []

    class Provider:
        async def sync(self, records):
            pass

        async def recall(self, query):
            queries.append(query)
            return ()

    service = SessionMemoryService(Provider())
    message = ModelMessage(role="user", content=(TextBlock(text="private record"),))
    await service.observe_projection(
        "run",
        ContextProjection(
            messages=(),
            historical_messages=(message,),
            estimated_tokens=0,
            source_message_count=1,
        ),
        session_id="session",
        source_messages=(message,),
    )
    assert (
        await service.recall(run_id="run", session_id="other", text="private", limit=5)
        == ()
    )
    assert queries == []


@pytest.mark.asyncio
async def test_index_digest_cache_is_bounded_and_eviction_does_not_break_recall(
    monkeypatch,
):
    import sagents.v2.session_memory.service as module

    monkeypatch.setattr(module, "_MAX_INDEXED_RECORDS_PER_SESSION", 3)
    queries = []

    class Provider:
        async def sync(self, records):
            pass

        async def recall(self, query):
            queries.append(query)
            return ()

    service = SessionMemoryService(Provider())
    messages = tuple(
        ModelMessage(
            role="user",
            content=(TextBlock(text=str(i)),),
            metadata={"source_item_id": f"item_{i}"},
        )
        for i in range(10)
    )
    await service.observe_projection(
        "run",
        ContextProjection(
            messages=(),
            historical_messages=messages,
            estimated_tokens=0,
            source_message_count=10,
        ),
        session_id="session",
        source_messages=messages,
    )
    assert len(service._indexed["session"]) == 3
    await service.recall(run_id="run", session_id="session", text="history", limit=5)
    assert len(queries[0].included_record_ids) == 10


@pytest.mark.asyncio
async def test_failed_control_lookup_does_not_launch_an_unobserved_tool():
    from sagents.v2.agent.engine import AgentLoopEngine

    calls = []

    class Catalog:
        async def get_tool(self, name, *, run_id):
            return object()

    class Store:
        async def get_start_command(self, run_id):
            raise RuntimeError("control state unavailable")

    class Executor:
        async def execute(self, call, context):
            calls.append(call)

    engine = SimpleNamespace(
        tool_catalog=Catalog(),
        tool_executor=Executor(),
        runtime=SimpleNamespace(session_store=Store()),
    )
    with pytest.raises(RuntimeError, match="control state unavailable"):
        await AgentLoopEngine._execute_tool_with_control(
            engine,
            SimpleNamespace(run_id="run"),
            SimpleNamespace(tool_name="write"),
            None,
        )
    await asyncio.sleep(0)
    assert calls == []


@pytest.mark.asyncio
async def test_memory_sync_tracks_provenance_changes_even_when_text_is_unchanged():
    batches = []

    class Provider:
        async def sync(self, records):
            batches.append(records)

    service = SessionMemoryService(Provider())
    for run in ("old_run", "new_run"):
        message = ModelMessage(
            role="user",
            content=(TextBlock(text="same text"),),
            metadata={"source_item_id": "item", "source_run_id": run},
        )
        await service.observe_projection(
            run,
            ContextProjection(
                messages=(message,), estimated_tokens=10, source_message_count=1
            ),
            session_id="session",
            source_messages=(message,),
        )
    assert len(batches) == 2
    assert batches[-1][0].source["source_run_id"] == "new_run"
