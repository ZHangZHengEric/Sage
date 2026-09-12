"""SQLite FTS5 derived index for Session history retrieval."""

from __future__ import annotations

import asyncio
from contextlib import closing
import os
import re
import sqlite3
from pathlib import Path

from sagents.v2._concurrency import bounded_to_thread

from sagents.v2.session_memory.contracts import (
    SessionMemoryCapabilities,
    SessionMemoryHit,
    SessionMemoryQuery,
    SessionMemoryRecord,
)


class SqliteBm25SessionMemoryProvider:
    plugin_id = "sage.session-memory.sqlite-bm25"
    name = "SQLite BM25 Session Memory provider"
    description = "Durable per-session BM25 index over canonical Session history."
    api_version = "2"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database_path = self.root / "session-memory.sqlite3"
        self._lock = asyncio.Lock()
        self._initialize()

    async def capabilities(self) -> SessionMemoryCapabilities:
        return SessionMemoryCapabilities(durable=True, incremental_index=True)

    async def sync(self, records: tuple[SessionMemoryRecord, ...]) -> None:
        if not records:
            return
        await bounded_to_thread(
            "memory-io", lambda: self._sync(records), lock=self._lock
        )

    async def recall(self, query: SessionMemoryQuery) -> tuple[SessionMemoryHit, ...]:
        tokens = self._tokenize(query.text)
        if not tokens:
            return ()
        rows = await bounded_to_thread(
            "memory-io", lambda: self._search(query, tokens), lock=self._lock
        )
        if not rows:
            return ()
        maximum = max(score for _, score in rows) or 1.0
        return tuple(
            SessionMemoryHit(
                record=record,
                score=max(0.0, min(1.0, score / maximum)),
            )
            for record, score in rows[: query.limit]
        )

    async def forget_session(self, session_id: str) -> None:
        await bounded_to_thread(
            "memory-io", lambda: self._forget_session(session_id), lock=self._lock
        )

    async def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "provider": "sqlite-bm25-session-memory",
            "database": str(self.database_path),
            "writable": os.access(self.root, os.W_OK),
        }

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS session_memory_records (
                    session_id TEXT NOT NULL,
                    record_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    search_text TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    PRIMARY KEY(session_id, record_id)
                )
                """
            )
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS session_memory_fts
                USING fts5(
                    session_id UNINDEXED,
                    record_id UNINDEXED,
                    search_text,
                    tokenize='unicode61'
                )
                """
            )

    def _sync(self, records: tuple[SessionMemoryRecord, ...]) -> None:
        with closing(self._connect()) as connection, connection:
            for record in records:
                search_text = " ".join(self._tokenize(record.content))
                payload = record.model_dump_json()
                current = connection.execute(
                    "SELECT payload_json, search_text FROM session_memory_records "
                    "WHERE session_id = ? AND record_id = ?",
                    (record.session_id, record.record_id),
                ).fetchone()
                if (
                    current is not None
                    and current["payload_json"] == payload
                    and current["search_text"] == search_text
                ):
                    continue
                connection.execute(
                    """
                    INSERT INTO session_memory_records(
                        session_id, record_id, payload_json, search_text, position
                    ) VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, record_id) DO UPDATE SET
                        payload_json = excluded.payload_json,
                        search_text = excluded.search_text,
                        position = excluded.position
                    """,
                    (
                        record.session_id,
                        record.record_id,
                        payload,
                        search_text,
                        record.position,
                    ),
                )
                connection.execute(
                    "DELETE FROM session_memory_fts "
                    "WHERE session_id = ? AND record_id = ?",
                    (record.session_id, record.record_id),
                )
                connection.execute(
                    "INSERT INTO session_memory_fts(session_id, record_id, search_text) "
                    "VALUES (?, ?, ?)",
                    (record.session_id, record.record_id, search_text),
                )

    def _search(
        self, query: SessionMemoryQuery, tokens: list[str]
    ) -> list[tuple[SessionMemoryRecord, float]]:
        match_query = " OR ".join(f'"{token}"' for token in tokens)
        with closing(self._connect()) as connection, connection:
            # Temporary tables avoid SQLite's bind-parameter limit for long
            # histories. Filter before LIMIT and before decoding record JSON.
            predicates = []
            for name, values, negate in (
                ("included_records", query.included_record_ids, False),
                ("excluded_records", query.excluded_record_ids, True),
            ):
                if not values:
                    continue
                connection.execute(
                    f"CREATE TEMP TABLE {name}(record_id TEXT PRIMARY KEY)"
                )
                connection.executemany(
                    f"INSERT OR IGNORE INTO {name} VALUES (?)",
                    ((value,) for value in values),
                )
                operator = "NOT IN" if negate else "IN"
                predicates.append(
                    f"AND records.record_id {operator} (SELECT record_id FROM {name})"
                )
            rows = connection.execute(
                """
                SELECT records.payload_json, bm25(session_memory_fts) AS raw_score
                FROM session_memory_fts
                JOIN session_memory_records AS records
                  ON records.session_id = session_memory_fts.session_id
                 AND records.record_id = session_memory_fts.record_id
                WHERE session_memory_fts MATCH ?
                  AND session_memory_fts.session_id = ?
                """
                + " ".join(predicates)
                + """
                ORDER BY raw_score ASC, records.position DESC
                LIMIT ?
                """,
                (match_query, query.session_id, query.limit),
            ).fetchall()
        return [
            (
                SessionMemoryRecord.model_validate_json(row["payload_json"]),
                max(0.0, -float(row["raw_score"])),
            )
            for row in rows
        ]

    def _forget_session(self, session_id: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM session_memory_records WHERE session_id = ?",
                (session_id,),
            )
            connection.execute(
                "DELETE FROM session_memory_fts WHERE session_id = ?",
                (session_id,),
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
