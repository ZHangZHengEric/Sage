"""Default Memory plugin that performs no external storage or retrieval."""

from __future__ import annotations

from sagents.v2.memory.contracts import (
    MemoryCapabilities,
    MemoryDeleteResult,
    MemoryQuery,
    MemoryRecord,
    MemoryScope,
    MemoryWriteResult,
)


class NoopMemoryProvider:
    """Safe default used until a host explicitly selects a Memory backend."""

    plugin_id = "sage.memory.noop"
    name = "No-op Memory"
    description = "Disables long-term Memory without changing Agent logic."

    async def capabilities(self) -> MemoryCapabilities:
        return MemoryCapabilities(durable=False, supports_delete=False)

    async def recall(self, query: MemoryQuery):
        return ()

    async def remember(self, record: MemoryRecord) -> MemoryWriteResult:
        return MemoryWriteResult(memory_id=record.memory_id, created=False)

    async def forget(self, memory_id: str, *, scope: MemoryScope) -> MemoryDeleteResult:
        return MemoryDeleteResult(memory_id=memory_id, deleted=False)

    async def get(self, memory_id: str, *, scope: MemoryScope):
        return None

    async def health(self):
        return {"status": "disabled", "plugin": "sage.memory.noop"}
