"""Authorized Session reads shared by AG-UI and A2A."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionPage:
    events: tuple
    total: int
    after_sequence: int


async def page_session_events(access, session_id: str, context, *, limit: int, after_sequence: int | None):
    """Read the newest page or continue after a delivered Session sequence."""

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
