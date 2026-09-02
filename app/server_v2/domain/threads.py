from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from app.server_v2.core.errors import ServerV2Error


class ThreadRecord(BaseModel):
    thread_id: str
    user_id: str
    title: str = ""
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def require_owned_thread(
    record: ThreadRecord | None, user_id: str
) -> ThreadRecord:
    if record is None or record.user_id != user_id:
        raise ServerV2Error("not_found", "thread not found")
    return record
