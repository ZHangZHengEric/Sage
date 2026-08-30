"""Durable, incrementally indexed BM25 Memory provider.

The public plugin id remains ``filesystem-bm25`` for compatibility, but the
provider stores records and its FTS5 index in SQLite. Each remember/forget
operation updates only the affected record instead of rebuilding a Python
BM25 corpus on every recall.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from sagents.v2.memory.contracts import (
    MemoryCapabilities,
    MemoryDeleteResult,
    MemoryHit,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryWriteResult,
)


class FilesystemBm25MemoryProvider:
    """Store scoped records in SQLite and recall them with FTS5 BM25."""

    api_version = "2"
    _SCHEMA_VERSION = "1"
    _LEGACY_MIGRATION_KEY = "legacy_json_migration_v1"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "memory.sqlite3"
        self._lock = asyncio.Lock()
        self._initialize_database()

    async def capabilities(self) -> MemoryCapabilities:
        return MemoryCapabilities(
            durable=True,
            supports_filtering=True,
            supports_delete=True,
        )

    async def recall(self, query: MemoryQuery) -> tuple[MemoryHit, ...]:
        query_tokens = self._tokenize(query.text)
        if not query_tokens:
            return ()
        async with self._lock:
            rows = await asyncio.to_thread(self._search, query, query_tokens)
        if not rows:
            return ()

        maximum = max((relevance for _, relevance in rows), default=1.0) or 1.0
        return tuple(
            MemoryHit(
                record=record,
                score=max(0.0, min(1.0, relevance / maximum)),
                reason="bm25",
            )
            for record, relevance in rows[: query.limit]
        )

    async def remember(self, record: MemoryRecord) -> MemoryWriteResult:
        async with self._lock:
            created = await asyncio.to_thread(self._upsert, record)
        return MemoryWriteResult(memory_id=record.memory_id, created=created)

    async def forget(self, memory_id: str, *, scope: MemoryScope) -> MemoryDeleteResult:
        async with self._lock:
            deleted = await asyncio.to_thread(self._delete, memory_id, scope)
        return MemoryDeleteResult(memory_id=memory_id, deleted=deleted)

    async def get(self, memory_id: str, *, scope: MemoryScope) -> MemoryRecord | None:
        async with self._lock:
            return await asyncio.to_thread(self._get, memory_id, scope)

    async def health(self) -> dict[str, object]:
        async with self._lock:
            record_count = await asyncio.to_thread(self._record_count)
        return {
            "status": "ok",
            "provider": "filesystem-bm25",
            "storage": "sqlite-fts5",
            "root": str(self.root),
            "database": str(self.database_path),
            "records": record_count,
            "writable": os.access(self.root, os.W_OK),
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize_database(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS memory_meta "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_records (
                    scope_key TEXT NOT NULL,
                    memory_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scope_key, memory_id)
                )
                """
            )
            row = connection.execute(
                "SELECT value FROM memory_meta WHERE key = 'schema_version'"
            ).fetchone()
            if row is None or row["value"] != self._SCHEMA_VERSION:
                connection.execute("DROP TABLE IF EXISTS memory_fts")
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
                USING fts5(
                    scope_key UNINDEXED,
                    memory_id UNINDEXED,
                    search_text,
                    tokenize='unicode61'
                )
                """
            )
            if row is None or row["value"] != self._SCHEMA_VERSION:
                connection.execute(
                    """
                    INSERT INTO memory_fts(scope_key, memory_id, search_text)
                    SELECT scope_key, memory_id, search_text FROM memory_records
                    """
                )
            connection.execute(
                "INSERT OR REPLACE INTO memory_meta(key, value) "
                "VALUES ('schema_version', ?)",
                (self._SCHEMA_VERSION,),
            )
            self._migrate_legacy_json(connection)

    def _migrate_legacy_json(self, connection: sqlite3.Connection) -> None:
        migrated = connection.execute(
            "SELECT value FROM memory_meta WHERE key = ?",
            (self._LEGACY_MIGRATION_KEY,),
        ).fetchone()
        if migrated is not None:
            return

        legacy_root = self.root / "scopes"
        if legacy_root.exists():
            for path in sorted(legacy_root.glob("*/*.json")):
                try:
                    record = MemoryRecord.model_validate_json(path.read_text("utf-8"))
                except (OSError, ValueError):
                    # A damaged legacy record must not make the whole provider
                    # unavailable. It remains on disk for manual recovery.
                    continue
                self._upsert_with_connection(connection, record)
        connection.execute(
            "INSERT INTO memory_meta(key, value) VALUES (?, 'complete')",
            (self._LEGACY_MIGRATION_KEY,),
        )

    def _upsert(self, record: MemoryRecord) -> bool:
        with self._connect() as connection:
            return self._upsert_with_connection(connection, record)

    def _upsert_with_connection(
        self, connection: sqlite3.Connection, record: MemoryRecord
    ) -> bool:
        scope_key = self._scope_key(record.scope)
        exists = connection.execute(
            "SELECT payload_json FROM memory_records "
            "WHERE scope_key = ? AND memory_id = ?",
            (scope_key, record.memory_id),
        ).fetchone()
        if exists is not None:
            previous = MemoryRecord.model_validate_json(exists["payload_json"])
            record = record.model_copy(update={"created_at": previous.created_at})
        payload_json = record.model_dump_json()
        metadata_json = json.dumps(
            record.metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        search_text = " ".join(self._tokenize(self._search_text(record)))
        connection.execute(
            """
            INSERT INTO memory_records(
                scope_key, memory_id, kind, metadata_json, payload_json,
                search_text, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scope_key, memory_id) DO UPDATE SET
                kind = excluded.kind,
                metadata_json = excluded.metadata_json,
                payload_json = excluded.payload_json,
                search_text = excluded.search_text,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                scope_key,
                record.memory_id,
                record.kind,
                metadata_json,
                payload_json,
                search_text,
                record.created_at.isoformat(),
                record.updated_at.isoformat(),
            ),
        )
        connection.execute(
            "DELETE FROM memory_fts WHERE scope_key = ? AND memory_id = ?",
            (scope_key, record.memory_id),
        )
        connection.execute(
            "INSERT INTO memory_fts(scope_key, memory_id, search_text) VALUES (?, ?, ?)",
            (scope_key, record.memory_id, search_text),
        )
        return exists is None

    def _delete(self, memory_id: str, scope: MemoryScope) -> bool:
        scope_key = self._scope_key(scope)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memory_records WHERE scope_key = ? AND memory_id = ?",
                (scope_key, memory_id),
            )
            connection.execute(
                "DELETE FROM memory_fts WHERE scope_key = ? AND memory_id = ?",
                (scope_key, memory_id),
            )
            return cursor.rowcount > 0

    def _get(self, memory_id: str, scope: MemoryScope) -> MemoryRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM memory_records "
                "WHERE scope_key = ? AND memory_id = ?",
                (self._scope_key(scope), memory_id),
            ).fetchone()
        return (
            MemoryRecord.model_validate_json(row["payload_json"])
            if row is not None
            else None
        )

    def _search(
        self, query: MemoryQuery, query_tokens: list[str]
    ) -> list[tuple[MemoryRecord, float]]:
        match_query = " OR ".join(
            f'"{token.replace(chr(34), chr(34) * 2)}"' for token in query_tokens
        )
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT records.payload_json, bm25(memory_fts) AS raw_score
                FROM memory_fts
                JOIN memory_records AS records
                  ON records.scope_key = memory_fts.scope_key
                 AND records.memory_id = memory_fts.memory_id
                WHERE memory_fts MATCH ? AND memory_fts.scope_key = ?
                ORDER BY raw_score ASC, records.updated_at DESC
                """,
                (match_query, self._scope_key(query.scope)),
            ).fetchall()

        matches: list[tuple[MemoryRecord, float]] = []
        allowed_kinds = set(query.kinds)
        for row in rows:
            record = MemoryRecord.model_validate_json(row["payload_json"])
            if allowed_kinds and record.kind not in allowed_kinds:
                continue
            if query.metadata and not all(
                record.metadata.get(key) == value
                for key, value in query.metadata.items()
            ):
                continue
            # SQLite FTS5 returns better BM25 matches as more-negative values.
            matches.append((record, max(0.0, -float(row["raw_score"]))))
            if len(matches) >= query.limit:
                break
        return matches

    def _record_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM memory_records"
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    @staticmethod
    def _scope_key(scope: MemoryScope) -> str:
        encoded = json.dumps(
            scope.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _search_text(record: MemoryRecord) -> str:
        return " ".join(
            (
                record.content,
                record.kind,
                json.dumps(record.metadata, ensure_ascii=False, sort_keys=True),
            )
        )

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        normalized = re.sub(r"[^\w\s\u4e00-\u9fff]", " ", text.lower())
        tokens: list[str] = []
        for word in normalized.split():
            if re.search(r"[\u4e00-\u9fff]", word):
                tokens.extend(re.findall(r"[\u4e00-\u9fff]", word))
                tokens.extend(re.findall(r"[a-z]+", word))
            elif len(word) > 1:
                tokens.append(word)
        return tokens
