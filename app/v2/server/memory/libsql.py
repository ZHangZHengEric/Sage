"""Server V2 FTS5 memory providers backed by a shared remote libSQL database."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace

from app.v2.server.memory.libsql_client import LibSQLClient, LibSQLError
from app.v2.server.runtime.sdk_plugins import service_registration
from sagents.v2.memory.contracts import (
    MemoryCapabilities, MemoryDeleteResult, MemoryHit, MemoryQuery,
    MemoryRecord, MemoryScope, MemoryWriteResult,
)
from sagents.v2.memory.indexing import scope_key, search_text
from sagents.v2.session_memory.contracts import (
    SessionMemoryCapabilities, SessionMemoryHit, SessionMemoryQuery, SessionMemoryRecord,
)
from sagents.v2.tokenization import tokenize_bm25

LIBSQL_MEMORY_PLUGIN = "com.sage.server.memory-libsql-bm25"
LIBSQL_SESSION_MEMORY_PLUGIN = "com.sage.server.session-memory-libsql-bm25"

_MEMORY_FIELDS = ("scope_key", "memory_id", "payload_json", "search_text", "updated_at")
_SESSION_FIELDS = ("session_id", "record_id", "payload_json", "search_text", "position")
_WRITE_CHUNK_BYTES = 1024 * 1024


def _schema(prefix, fields, last_type):
    owner, identifier, _, _, order = fields
    records, fts = f"{prefix}_records", f"{prefix}_fts"
    return (
        f"""CREATE TABLE IF NOT EXISTS {records} (
            {owner} TEXT NOT NULL, {identifier} TEXT NOT NULL,
            payload_json TEXT NOT NULL, search_text TEXT NOT NULL,
            {order} {last_type} NOT NULL, PRIMARY KEY ({owner}, {identifier})
        )""",
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {fts} USING fts5(search_text, tokenize='unicode61')",
        f"""CREATE TRIGGER IF NOT EXISTS {records}_insert AFTER INSERT ON {records} BEGIN
            INSERT INTO {fts}(rowid, search_text) VALUES (new.rowid, new.search_text);
        END""",
        f"""CREATE TRIGGER IF NOT EXISTS {records}_delete AFTER DELETE ON {records} BEGIN
            DELETE FROM {fts} WHERE rowid = old.rowid;
        END""",
        f"""CREATE TRIGGER IF NOT EXISTS {records}_update AFTER UPDATE OF search_text ON {records}
            WHEN old.search_text IS NOT new.search_text BEGIN
            UPDATE {fts} SET search_text = new.search_text WHERE rowid = new.rowid;
        END""",
    )


async def prepare_memory_schema(database: LibSQLClient) -> None:
    statements = (*_schema("memory", _MEMORY_FIELDS, "TEXT"),
                  *_schema("session_memory", _SESSION_FIELDS, "INTEGER"))
    await database.transaction(*((sql, (), False) for sql in statements))


async def check_memory_schema(database: LibSQLClient) -> None:
    result = await database.execute(
        """SELECT COUNT(*) FROM sqlite_schema WHERE name IN (
            'memory_records', 'memory_fts', 'memory_records_insert', 'memory_records_update',
            'memory_records_delete', 'session_memory_records', 'session_memory_fts',
            'session_memory_records_insert', 'session_memory_records_update',
            'session_memory_records_delete'
        )""", rows=True,
    )
    if result.rows != [[10]]:
        raise RuntimeError("Remote libSQL memory schema is missing. Run the SQLite import command with --init-libsql.")


def _memory_row(record: MemoryRecord):
    return (
        scope_key(record.scope), record.memory_id, record.model_dump_json(),
        " ".join(tokenize_bm25(search_text(record))), record.updated_at.isoformat(),
    )


def _session_row(record: SessionMemoryRecord):
    return (
        record.session_id, record.record_id, record.model_dump_json(),
        " ".join(tokenize_bm25(record.content)), record.position,
    )


def _upsert(prefix, fields, *, import_only=False, preserve_created_at=False):
    records = f"{prefix}_records"
    owner, identifier, payload, search, order = fields
    values = ", ".join(f"json_extract(value, '$[{index}]')" for index in range(len(fields)))
    payload_update = "excluded.payload_json"
    if import_only:
        # An identical row is skipped. A conflicting row fails the entire statement.
        payload_update = "NULL"
    elif preserve_created_at:
        payload_update = (
            f"json_set(excluded.payload_json, '$.created_at', "
            f"json_extract({records}.payload_json, '$.created_at'))"
        )
    return f"""
        INSERT INTO {records} ({", ".join(fields)})
        SELECT {values} FROM json_each(?) WHERE true
        ON CONFLICT ({owner}, {identifier}) DO UPDATE SET
            {payload} = {payload_update}, {search} = excluded.{search}, {order} = excluded.{order}
        WHERE {records}.{payload} IS NOT excluded.{payload}
           OR {records}.{search} IS NOT excluded.{search}
    """


_MEMORY_UPSERT = _upsert("memory", _MEMORY_FIELDS, preserve_created_at=True)
_SESSION_UPSERT = _upsert("session_memory", _SESSION_FIELDS)


def _row_batches(rows: Iterable[tuple]):
    batch: list[str] = []
    size = 0
    for row in rows:
        encoded = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        encoded_size = len(encoded.encode("utf-8")) + 1
        if batch and size + encoded_size > _WRITE_CHUNK_BYTES:
            yield "[" + ",".join(batch) + "]"
            batch = []
            size = 0
        batch.append(encoded)
        size += encoded_size
    if batch:
        yield "[" + ",".join(batch) + "]"


async def _write_rows(database: LibSQLClient, sql: str, rows: Iterable[tuple]) -> None:
    # Each value stays below the remote bind-argument size limit, while one
    # transaction still covers all chunks of a sync or import batch.
    statements = [(sql, (batch,), False) for batch in _row_batches(rows)]
    if len(statements) == 1:
        await database.execute(sql, statements[0][1])
    elif statements:
        await database.transaction(*statements)


async def _import_rows(database, prefix, fields, rows):
    try:
        await _write_rows(database, _upsert(prefix, fields, import_only=True), rows)
    except LibSQLError as exc:
        if exc.code in {"SQLITE_CONSTRAINT", "SQLITE_CONSTRAINT_NOTNULL"}:
            raise ValueError(f"Conflicting record already exists in {prefix}") from exc
        raise


def _match(tokens):
    return " OR ".join(f'"{token}"' for token in tokens)


def _scores(records):
    relevance = [max(0.0, -float(score)) for _, score in records]
    maximum = max(relevance, default=0.0) or 1.0
    return ((row[0], score / maximum) for row, score in zip(records, relevance))


class LibSQLMemoryProvider:
    plugin_id = LIBSQL_MEMORY_PLUGIN

    def __init__(self, database: LibSQLClient) -> None:
        self.database = database

    async def capabilities(self) -> MemoryCapabilities:
        return MemoryCapabilities(durable=True, supports_filtering=True, supports_delete=True)

    async def health(self) -> dict[str, object]:
        await self.database.execute("SELECT rowid FROM memory_fts LIMIT 0")
        return {"status": "ok", "provider": self.plugin_id, "storage": "libsql-fts5"}

    async def remember(self, record: MemoryRecord) -> MemoryWriteResult:
        row = _memory_row(record)
        existing, _ = await self.database.transaction(
            ("SELECT 1 FROM memory_records WHERE scope_key = ? AND memory_id = ?", row[:2], True),
            (_MEMORY_UPSERT, (json.dumps([row], ensure_ascii=False),), False),
        )
        return MemoryWriteResult(memory_id=record.memory_id, created=not existing.rows)

    async def import_records(self, records: tuple[MemoryRecord, ...]) -> None:
        await _import_rows(self.database, "memory", _MEMORY_FIELDS, map(_memory_row, records))

    async def get(self, memory_id: str, *, scope: MemoryScope) -> MemoryRecord | None:
        result = await self.database.execute(
            "SELECT payload_json FROM memory_records WHERE scope_key = ? AND memory_id = ?",
            (scope_key(scope), memory_id), rows=True,
        )
        return MemoryRecord.model_validate_json(result.rows[0][0]) if result.rows else None

    async def forget(self, memory_id: str, *, scope: MemoryScope) -> MemoryDeleteResult:
        result = await self.database.execute(
            "DELETE FROM memory_records WHERE scope_key = ? AND memory_id = ?",
            (scope_key(scope), memory_id),
        )
        return MemoryDeleteResult(memory_id=memory_id, deleted=bool(result.affected))

    async def recall(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        tokens = tokenize_bm25(query.text)
        if not tokens:
            return ()
        sql = """
            SELECT records.payload_json, bm25(memory_fts) AS raw_score
            FROM memory_fts JOIN memory_records AS records ON records.rowid = memory_fts.rowid
            WHERE memory_fts MATCH ? AND records.scope_key = ?
        """
        args = [_match(tokens), scope_key(query.scope)]
        if query.kinds:
            sql += " AND json_extract(records.payload_json, '$.kind') IN (SELECT value FROM json_each(?))"
            args.append(json.dumps(query.kinds))
        sql += " ORDER BY raw_score ASC, records.updated_at DESC, records.rowid ASC LIMIT ? OFFSET ?"
        # Keep Python equality for metadata, including missing keys and nested values.
        matches = []
        page_size = max(query.limit, 128) if query.metadata else query.limit
        offset = 0
        while len(matches) < query.limit:
            result = await self.database.execute(sql, (*args, page_size, offset), rows=True)
            for payload, score in result.rows:
                record = MemoryRecord.model_validate_json(payload)
                if all(record.metadata.get(key) == value for key, value in query.metadata.items()):
                    matches.append((record, score))
                    if len(matches) == query.limit:
                        break
            if len(result.rows) < page_size:
                break
            offset += page_size
        return tuple(MemoryHit(record=record, score=score, reason="bm25") for record, score in _scores(matches))


class LibSQLSessionMemoryProvider:
    plugin_id = LIBSQL_SESSION_MEMORY_PLUGIN

    def __init__(self, database: LibSQLClient) -> None:
        self.database = database

    async def capabilities(self) -> SessionMemoryCapabilities:
        return SessionMemoryCapabilities(durable=True, incremental_index=True)

    async def health(self) -> dict[str, object]:
        await self.database.execute("SELECT rowid FROM session_memory_fts LIMIT 0")
        return {"status": "ok", "provider": self.plugin_id, "storage": "libsql-fts5"}

    async def sync(self, records: tuple[SessionMemoryRecord, ...]) -> None:
        await _write_rows(self.database, _SESSION_UPSERT, map(_session_row, records))

    async def import_records(self, records: tuple[SessionMemoryRecord, ...]) -> None:
        await _import_rows(self.database, "session_memory", _SESSION_FIELDS, map(_session_row, records))

    async def forget_session(self, session_id: str) -> None:
        await self.database.execute("DELETE FROM session_memory_records WHERE session_id = ?", (session_id,))

    async def recall(self, query: SessionMemoryQuery) -> tuple[SessionMemoryHit, ...]:
        tokens = tokenize_bm25(query.text)
        if not tokens:
            return ()
        sql = """
            SELECT records.payload_json, bm25(session_memory_fts) AS raw_score
            FROM session_memory_fts
            JOIN session_memory_records AS records ON records.rowid = session_memory_fts.rowid
            WHERE session_memory_fts MATCH ? AND records.session_id = ?
        """
        args = [_match(tokens), query.session_id]
        for operator, ids in (("IN", query.included_record_ids), ("NOT IN", query.excluded_record_ids)):
            if ids:
                sql += f" AND records.record_id {operator} (SELECT value FROM json_each(?))"
                args.append(json.dumps(ids))
        sql += " ORDER BY raw_score ASC, records.position DESC, records.rowid ASC LIMIT ?"
        result = await self.database.execute(sql, (*args, query.limit), rows=True)
        hits = [(SessionMemoryRecord.model_validate_json(payload), score) for payload, score in result.rows]
        return tuple(SessionMemoryHit(record=record, score=score) for record, score in _scores(hits))


def libsql_memory_registrations(database: LibSQLClient):
    for capability, provider, name in (
        ("memory.provider", LibSQLMemoryProvider(database), "Server libSQL BM25 长期记忆"),
        ("session-memory.provider", LibSQLSessionMemoryProvider(database), "Server libSQL BM25 会话记忆"),
    ):
        registration = service_registration(capability, provider)
        yield replace(registration, descriptor=registration.descriptor.model_copy(update={
            "plugin_id": provider.plugin_id, "name": name,
            "capabilities": {"durable": True, "retrieval": "bm25", "incremental_index": True},
        }))
