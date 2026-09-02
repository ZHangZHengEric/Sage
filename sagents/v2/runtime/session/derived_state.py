"""Small in-process store for rebuildable per-Session projections."""

from __future__ import annotations

import asyncio
from typing import Any


class InMemoryDerivedStateStore:
    """Default derived storage for hosts that inject an authoritative store only."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str, str], Any] = {}
        self._lock = asyncio.Lock()

    async def get_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> Any | None:
        async with self._lock:
            return self._values.get((session_id, namespace, key))

    async def put_derived_state(
        self, session_id: str, namespace: str, key: str, value: Any
    ) -> None:
        async with self._lock:
            self._values[(session_id, namespace, key)] = value

    async def delete_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> None:
        async with self._lock:
            self._values.pop((session_id, namespace, key), None)

    async def forget_session(self, session_id: str) -> None:
        async with self._lock:
            self._values = {
                key: value
                for key, value in self._values.items()
                if key[0] != session_id
            }

    def composition_identity(self) -> dict[str, str]:
        return {"provider": "in-memory-derived-state", "durability": "process"}
