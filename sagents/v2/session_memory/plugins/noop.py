"""Disabled Session Memory provider."""

from sagents.v2.session_memory.contracts import (
    SessionMemoryCapabilities,
    SessionMemoryQuery,
    SessionMemoryRecord,
)


class NoopSessionMemoryProvider:
    plugin_id = "sage.session-memory.noop"
    name = "No-op Session Memory provider"
    description = "Disables searchable Session history without changing Agent logic."
    api_version = "2"

    async def capabilities(self) -> SessionMemoryCapabilities:
        return SessionMemoryCapabilities(durable=False, incremental_index=False)

    async def sync(self, records: tuple[SessionMemoryRecord, ...]) -> None:
        del records

    async def recall(self, query: SessionMemoryQuery):
        del query
        return ()

    async def forget_session(self, session_id: str) -> None:
        del session_id

    async def health(self) -> dict[str, object]:
        return {"status": "ok", "provider": "noop-session-memory"}
