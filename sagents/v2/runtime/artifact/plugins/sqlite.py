"""Immutable artifact snapshots in a host-owned SQLite database."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.artifact.contracts import ArtifactRef


class SqliteArtifactStore:
    plugin_id = "sage.artifact.sqlite"
    name = "SQLite ArtifactStore"
    description = "Immutable artifact bytes with local restart durability."

    def __init__(self, root: str | Path):
        root = Path(root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "artifacts.sqlite3"
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS artifacts "
                "(id TEXT PRIMARY KEY, reference TEXT NOT NULL, payload BLOB NOT NULL)"
            )

    @property
    def capabilities(self):
        return {"durable_across_process_restart": True, "shared_across_processes": True}

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    async def put(self, *, artifact_id, media_type, content, metadata=None):
        payload = b"".join([chunk async for chunk in content])
        reference = ArtifactRef(
            artifact_id=artifact_id,
            media_type=media_type,
            size_bytes=len(payload),
            digest=f"sha256:{hashlib.sha256(payload).hexdigest()}",
            metadata=metadata or {},
        )
        serialized = json.dumps(reference.model_dump(mode="json"), sort_keys=True)

        def save():
            with self._connect() as connection:
                connection.execute(
                    "INSERT OR IGNORE INTO artifacts VALUES (?, ?, ?)",
                    (artifact_id, serialized, payload),
                )
                existing = connection.execute(
                    "SELECT reference, payload FROM artifacts WHERE id = ?",
                    (artifact_id,),
                ).fetchone()
                if existing != (serialized, payload):
                    raise self._error(
                        "artifact.id_conflict", artifact_id, ErrorCategory.CONFLICT
                    )
            return reference

        return await asyncio.to_thread(save)

    async def get(self, artifact_id):
        def load():
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT reference, payload FROM artifacts WHERE id = ?",
                    (artifact_id,),
                ).fetchone()
            if row is None:
                raise self._error("artifact.not_found", artifact_id)
            reference = ArtifactRef.model_validate_json(row[0])
            payload = row[1]
            if (
                reference.artifact_id != artifact_id
                or reference.size_bytes != len(payload)
                or reference.digest != f"sha256:{hashlib.sha256(payload).hexdigest()}"
            ):
                raise self._error("artifact.integrity_failed", artifact_id)
            return reference, payload

        reference, payload = await asyncio.to_thread(load)

        async def stream():
            yield payload

        return reference, stream()

    async def delete(self, artifact_id):
        def remove():
            with self._connect() as connection:
                return (
                    connection.execute(
                        "DELETE FROM artifacts WHERE id = ?", (artifact_id,)
                    ).rowcount
                    > 0
                )

        return await asyncio.to_thread(remove)

    @staticmethod
    def _error(code, artifact_id, category=ErrorCategory.VALIDATION):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=f"{code}: {artifact_id!r}",
                safe_to_resume=True,
            )
        )
