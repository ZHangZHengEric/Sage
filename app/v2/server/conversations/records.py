from __future__ import annotations

from datetime import datetime, timezone
import base64
import json

from pydantic import BaseModel, Field

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class ThreadRecord(BaseModel):
    thread_id: str
    user_id: str
    title: str = ""
    agent_id: str = ""
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def require_owned_thread(record: ThreadRecord | None, user_id: str) -> ThreadRecord:
    if record is None or record.user_id != user_id:
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.conversations.records.not_found",
                category=ErrorCategory.VALIDATION,
                message="thread not found",
            )
        )
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
    pinned = (
        existing.agent_id
        if existing is not None and existing.agent_id
        else str(agent_id or "")
    )
    return ThreadRecord(
        thread_id=thread_id,
        user_id=user_id,
        title=(existing.title if existing is not None else "") or title,
        agent_id=pinned,
    )


class ThreadPage(BaseModel):
    items: list[ThreadRecord]
    next_cursor: str | None = None


def thread_cursor(row: ThreadRecord, *, scan: bool = False) -> str:
    values = [row.thread_id] if scan else [row.updated_at, row.thread_id]
    return base64.urlsafe_b64encode(json.dumps(values).encode()).decode()


def parse_thread_cursor(cursor: str | None, *, scan: bool = False) -> list[str] | None:
    if cursor is None:
        return None
    try:
        if len(cursor) > 2048:
            raise ValueError('cursor too large')
        values = json.loads(base64.b64decode(cursor.encode(), altchars=b'-_', validate=True))
        if not isinstance(values, list) or len(values) != (1 if scan else 2) or not all(isinstance(v, str) for v in values):
            raise ValueError('invalid cursor')
        return values
    except (ValueError, UnicodeError) as exc:
        raise SageV2Error(RuntimeErrorInfo(code='server.threads.invalid_cursor',
            category=ErrorCategory.VALIDATION, message='Invalid thread cursor')) from exc
