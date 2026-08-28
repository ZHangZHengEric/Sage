"""Desktop-owned global Session index.

SAgents deliberately exposes only operations for a known ``session_id``.  The
Desktop application owns listing, ordering, search, and user-facing metadata,
so losing this file cannot damage or change any authoritative Session journal.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from pydantic import TypeAdapter

from sagents.v2.contracts.run_state import SessionSnapshot


class JsonDesktopSessionIndex:
    """Small replaceable reference index for the Desktop application."""

    _adapter = TypeAdapter(tuple[SessionSnapshot, ...])

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._lock = asyncio.Lock()

    async def list(self) -> tuple[SessionSnapshot, ...]:
        async with self._lock:
            values = await asyncio.to_thread(self._read)
        return tuple(sorted(values, key=lambda value: value.updated_at, reverse=True))

    async def upsert(self, value: SessionSnapshot) -> None:
        async with self._lock:
            values = {
                item.session_id: item for item in await asyncio.to_thread(self._read)
            }
            values[value.session_id] = value
            await asyncio.to_thread(self._write, tuple(values.values()))

    async def remove(self, session_id: str) -> None:
        async with self._lock:
            values = tuple(
                value
                for value in await asyncio.to_thread(self._read)
                if value.session_id != session_id
            )
            await asyncio.to_thread(self._write, values)

    def _read(self) -> tuple[SessionSnapshot, ...]:
        if not self.path.exists():
            return ()
        return self._adapter.validate_json(self.path.read_text(encoding="utf-8"))

    def _write(self, values: tuple[SessionSnapshot, ...]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(
                    [value.model_dump(mode="json") for value in values],
                    stream,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
