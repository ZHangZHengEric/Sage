"""Authorized Session reads shared by AG-UI and A2A."""

from __future__ import annotations

from dataclasses import dataclass

from sagents.v2.contracts.run_state import EventCursor


@dataclass(frozen=True, slots=True)
class SessionPage:
    events: tuple
    total: int
    after_sequence: int


class SessionLog:
    """One view of session.access. Callers do not look up the service name."""

    def __init__(self, access) -> None:
        self._access = access

    def open(self):
        return self._access()

    async def get_run(self, run_id: str, context):
        return await self.open().get_run(run_id, context)

    async def list_runs(self, session_id: str, context):
        return await self.open().list_session_runs(session_id, context)

    async def read_run_events(self, run_id: str, context):
        return await self.open().read_events(run_id, context)

    async def get_suspension(self, suspension_id: str, context):
        return await self.open().get_suspension(suspension_id, context)

    async def get_interaction(self, interaction_id: str, context):
        return await self.open().get_interaction(interaction_id, context)

    def subscribe(self, cursor: EventCursor, context):
        return self.open().subscribe_events(cursor, context)

    async def delete(self, session_id: str, context) -> None:
        await self.open().delete_session(session_id, context)

    async def page(self, session_id: str, context, *, limit: int, after_sequence: int | None):
        """Return one window of session events.

        ``after_sequence`` is the cursor already delivered. Omitting it asks for
        the newest ``limit`` events, which is what a thread page shows on open.
        The store filters ``session_sequence > after_sequence``, so the caller
        never materializes the whole log to slice it.
        """

        access = self.open()
        session = await access.get_session(session_id, context)
        total = int(session.last_sequence)
        start = (
            max(0, total - limit)
            if after_sequence is None
            else max(0, int(after_sequence))
        )
        events = await access.read_session_events(
            session_id, context, after_sequence=start, limit=limit
        )
        return SessionPage(events=tuple(events), total=total, after_sequence=start)
