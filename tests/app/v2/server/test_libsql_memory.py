import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.v2.server.config.manifest import server_v2_manifest
from app.v2.server.database.import_sqlite import import_memory, import_session_memory
from app.v2.server.memory.libsql import (
    LibSQLMemoryProvider,
    LibSQLSessionMemoryProvider,
    prepare_memory_schema,
)
from app.v2.server.memory.libsql_client import LibSQLClient, LibSQLError
from sagents.v2.memory.contracts import MemoryQuery, MemoryRecord, MemoryScope
from sagents.v2.memory.plugins.filesystem_bm25 import FilesystemBm25MemoryProvider
from sagents.v2.session_memory import SessionMemoryQuery, SessionMemoryRecord, SqliteBm25SessionMemoryProvider
from tests.app.v2.server.conftest import make_settings


def test_server_memory_uses_libsql_and_model_generated_recall(tmp_path):
    runtime = server_v2_manifest(make_settings(tmp_path, libsql_url="http://127.0.0.1:8080")).runtime
    assert runtime.selections("memory.provider")[0].plugin == "com.sage.server.memory-libsql-bm25"
    assert runtime.selections("session-memory.provider")[0].plugin == "com.sage.server.session-memory-libsql-bm25"
    assert runtime.selections("memory.recall-query")[0].plugin == "sage.memory.recall-query.llm"


async def test_remote_libsql_preserves_fts5_and_sqlite_import(libsql_url, tmp_path):
    old_memory = FilesystemBm25MemoryProvider(tmp_path / "memory")
    old_sessions = SqliteBm25SessionMemoryProvider(tmp_path / "sessions")
    scope = MemoryScope(tenant_id=uuid4().hex, principal_id="reader", workspace_id="project")
    other = scope.model_copy(update={"workspace_id": "other-project"})
    session_id, other_session = uuid4().hex, uuid4().hex
    now = datetime.now(timezone.utc)
    texts = ("上线窗口 foo_bar café", "上线窗口 bar foo", "上线窗口 foo bar")
    memories = tuple(
        MemoryRecord(memory_id=str(i), scope=owner, content=text, metadata={"active": i == 0},
                     created_at=now, updated_at=now)
        for i, (owner, text) in enumerate(zip((scope, scope, other), texts))
    )
    sessions = tuple(
        SessionMemoryRecord(session_id=owner, record_id=str(i), role="user", content=text, position=i)
        for i, (owner, text) in enumerate(zip((session_id, session_id, other_session), texts))
    )
    for record in memories:
        await old_memory.remember(record)
    await old_sessions.sync(sessions)

    async with LibSQLClient(libsql_url) as database:
        await prepare_memory_schema(database)
        memory = LibSQLMemoryProvider(database)
        session = LibSQLSessionMemoryProvider(database)
        try:
            for _ in range(2):
                assert await import_memory(database, old_memory.database_path) == len(memories)
                assert await import_session_memory(database, old_sessions.database_path) == len(sessions)
            for memory_query in (
                MemoryQuery(scope=scope, text="上线窗口"),
                MemoryQuery(scope=scope, text="foo_bar", metadata={"active": True}),
            ):
                actual = await memory.recall(memory_query)
                expected = await old_memory.recall(memory_query)
                assert [hit.record for hit in actual] == [hit.record for hit in expected]
                assert [hit.score for hit in actual] == pytest.approx([hit.score for hit in expected])
            session_query = SessionMemoryQuery(
                session_id=session_id, run_id="run", text="上线窗口",
                included_record_ids=tuple(str(i) for i in range(1200)), excluded_record_ids=("1",),
            )
            for query in (session_query, session_query.model_copy(update={"excluded_record_ids": ()})):
                actual = await session.recall(query)
                expected = await old_sessions.recall(query)
                assert [hit.record for hit in actual] == [hit.record for hit in expected]
                assert [hit.score for hit in actual] == pytest.approx([hit.score for hit in expected])
            new = memories[0].model_copy(update={"memory_id": "never-imported"})
            edited_session = sessions[0].model_copy(update={"content": "reindexed history"})
            await session.sync((edited_session,))
            assert not await session.recall(session_query)
            assert [hit.record for hit in await session.recall(
                session_query.model_copy(update={"text": "reindexed"})
            )] == [edited_session]
            with pytest.raises(ValueError, match="Conflicting"):
                await import_session_memory(database, old_sessions.database_path)
            edited = memories[0].model_copy(update={
                "content": "new deployment date", "updated_at": now + timedelta(seconds=1),
            })
            assert not (await memory.remember(edited.model_copy(
                update={"created_at": edited.updated_at}
            ))).created
            assert await memory.get(edited.memory_id, scope=scope) == edited
            with pytest.raises(ValueError, match="Conflicting"):
                await import_memory(database, old_memory.database_path)
            with pytest.raises(ValueError, match="Conflicting"):
                await memory.import_records((new, memories[0]))
            assert await memory.get(new.memory_id, scope=scope) is None
            assert not await memory.recall(MemoryQuery(scope=scope, text="café"))
            assert await memory.get(edited.memory_id, scope=scope) == edited
            assert (await memory.forget(edited.memory_id, scope=scope)).deleted
            assert await memory.get(edited.memory_id, scope=other) is None
            await session.forget_session(session_id)
            assert not await session.recall(session_query)
        finally:
            for record in memories:
                await memory.forget(record.memory_id, scope=record.scope)
            await session.forget_session(session_id)
            await session.forget_session(other_session)


async def test_remote_libsql_indexes_large_batches_and_serializes_writes(libsql_url):
    session_id = uuid4().hex
    scope = MemoryScope(principal_id=session_id)
    now = datetime.now(timezone.utc)
    record = MemoryRecord(
        memory_id=session_id, scope=scope, content="concurrent memory",
        created_at=now, updated_at=now,
    )
    records = tuple(
        SessionMemoryRecord(
            session_id=session_id, record_id=str(i), role="user",
            content="history " * 400, position=i,
        )
        for i in range(1000)
    )
    async with LibSQLClient(libsql_url) as first, LibSQLClient(libsql_url) as second:
        await prepare_memory_schema(first)
        memory = LibSQLMemoryProvider(first)
        sessions = LibSQLSessionMemoryProvider(first)
        try:
            writes = await asyncio.gather(memory.remember(record), LibSQLMemoryProvider(second).remember(record))
            assert sum(write.created for write in writes) == 1
            with pytest.raises(LibSQLError):
                await first.transaction(
                    ("DELETE FROM memory_records WHERE memory_id = ?", (record.memory_id,), False),
                    ("SELECT * FROM missing_table", (), True),
                )
            assert await memory.get(record.memory_id, scope=scope) == record
            assert await memory.recall(MemoryQuery(scope=scope, text="concurrent"))
            await sessions.sync(records)
            for position in (0, 999):
                hits = await sessions.recall(SessionMemoryQuery(
                    session_id=session_id, run_id="test", text="history",
                    included_record_ids=(str(position),),
                ))
                assert [hit.record for hit in hits] == [records[position]]
        finally:
            await memory.forget(record.memory_id, scope=scope)
            await sessions.forget_session(session_id)
