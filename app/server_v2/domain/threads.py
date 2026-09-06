from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.server_v2.core.errors import ServerV2Error


class ThreadRecord(BaseModel):
    thread_id: str
    user_id: str
    title: str = ""
    agent_id: str = ""
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def require_owned_thread(
    record: ThreadRecord | None, user_id: str
) -> ThreadRecord:
    if record is None or record.user_id != user_id:
        raise ServerV2Error("not_found", "thread not found")
    return record


def resolve_thread_agent_id(existing: ThreadRecord | None, requested: str) -> str:
    """Pinned thread agent wins over the current picker."""

    if existing is not None and existing.agent_id:
        return existing.agent_id
    return str(requested or "").strip()


def apply_thread_upsert(
    existing: ThreadRecord | None,
    *,
    thread_id: str,
    user_id: str,
    title: str = "",
    agent_id: str | None = None,
) -> ThreadRecord:
    if existing is not None:
        require_owned_thread(existing, user_id)
    pinned = existing.agent_id if existing is not None and existing.agent_id else str(
        agent_id or ""
    )
    return ThreadRecord(
        thread_id=thread_id,
        user_id=user_id,
        title=title or (existing.title if existing is not None else title),
        agent_id=pinned,
    )
