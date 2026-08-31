# pyright: strict
"""Storage-only repositories for typed Session aggregates."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol

from sagents.v2.runtime.session.aggregate import SessionAggregate


class SessionRepository(Protocol):
    async def load(self, session_id: str) -> SessionAggregate | None: ...
    async def commit(self, aggregate: SessionAggregate) -> None: ...
    async def delete(self, session_id: str) -> bool: ...


class EphemeralSessionRepository:
    def __init__(self) -> None:
        self._values: dict[str, SessionAggregate] = {}

    async def load(self, session_id: str) -> SessionAggregate | None:
        return self._values.get(session_id)

    async def commit(self, aggregate: SessionAggregate) -> None:
        self._values[aggregate.session_id] = aggregate

    async def delete(self, session_id: str) -> bool:
        return self._values.pop(session_id, None) is not None


class FilesystemSessionRepository:
    """One-file typed aggregate repository; transaction policy lives above it."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def load(self, session_id: str) -> SessionAggregate | None:
        path = self._path(session_id)
        if not path.is_file():
            return None
        from sagents.v2.runtime.session.journal import SessionAggregateSnapshotV2

        payload = await asyncio.to_thread(path.read_text, encoding="utf-8")
        return SessionAggregate(SessionAggregateSnapshotV2.model_validate_json(payload))

    async def commit(self, aggregate: SessionAggregate) -> None:
        path = self._path(aggregate.session_id)
        temporary = path.with_suffix(".tmp")
        payload = aggregate.snapshot.model_dump_json()
        await asyncio.to_thread(temporary.write_text, payload, encoding="utf-8")
        await asyncio.to_thread(temporary.replace, path)

    async def delete(self, session_id: str) -> bool:
        path = self._path(session_id)
        if not path.exists():
            return False
        await asyncio.to_thread(path.unlink)
        return True

    def _path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or "\\" in session_id:
            raise ValueError("invalid Session id")
        return self.root / f"{session_id}.json"
