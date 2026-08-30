"""SQLite FTS5 derived index for Session history retrieval."""

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from pathlib import Path

from sagents.v2.session_memory.contracts import (
    SessionMemoryCapabilities,
    SessionMemoryHit,
    SessionMemoryQuery,
    SessionMemoryRecord,
)


class SqliteBm25SessionMemoryProvider:
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
        async with self._lock:
            await asyncio.to_thread(self._sync, records)

    async def recall(
        self, query: SessionMemoryQuery
    ) -> tuple[SessionMemoryHit, ...]:
        tokens = self._tokenize(query.text)
        if not tokens:
            return ()
        async with self._lock:
            rows = await asyncio.to_thread(self._search, query, tokens)
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
        async with self._lock:
            await asyncio.to_thread(self._forget_session, session_id)

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
        with self._connect() as connection:
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
        with self._connect() as connection:
            existing: dict[tuple[str, str], sqlite3.Row] = {}
            for session_id in {record.session_id for record in records}:
                existing.update(
                    {
                        (session_id, row["record_id"]): row
                        for row in connection.execute(
                            "SELECT record_id, payload_json, search_text "
                            "FROM session_memory_records WHERE session_id = ?",
                            (session_id,),
                        ).fetchall()
                    }
                )
            for record in records:
                search_text = " ".join(self._tokenize(record.content))
                payload = record.model_dump_json()
                current = existing.get((record.session_id, record.record_id))
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
        included = set(query.included_record_ids)
        excluded = set(query.excluded_record_ids)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT records.payload_json, bm25(session_memory_fts) AS raw_score
                FROM session_memory_fts
                JOIN session_memory_records AS records
                  ON records.session_id = session_memory_fts.session_id
                 AND records.record_id = session_memory_fts.record_id
                WHERE session_memory_fts MATCH ?
                  AND session_memory_fts.session_id = ?
                ORDER BY raw_score ASC, records.position DESC
                """,
                (match_query, query.session_id),
            ).fetchall()
        matches = []
        for row in rows:
            record = SessionMemoryRecord.model_validate_json(row["payload_json"])
            if included and record.record_id not in included:
                continue
            if record.record_id in excluded:
                continue
            matches.append((record, max(0.0, -float(row["raw_score"]))))
            if len(matches) >= query.limit:
                break
        return matches

    def _forget_session(self, session_id: str) -> None:
        with self._connect() as connection:
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
