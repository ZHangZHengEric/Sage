from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_context: ContextVar[dict[str, Any] | None] = ContextVar(
    "sage_request_context",
    default=None,
)


def create_request_id() -> str:
    return uuid.uuid4().hex[:12]


@contextmanager
def request_context(request_id: str, **metadata: Any) -> Iterator[str]:
    normalized = str(request_id or "").strip() or create_request_id()
    token = _context.set({"request_id": normalized, **metadata})
    try:
        yield normalized
    finally:
        _context.reset(token)


@contextmanager
def background_request_context(task_name: str) -> Iterator[str]:
    with request_context(create_request_id(), task_name=task_name) as request_id:
        yield request_id


def set_request_context(request_id: str, **metadata: Any) -> None:
    _context.set({"request_id": request_id, **metadata})


def clear_request_context() -> None:
    _context.set(None)


def get_request_id() -> str:
    return str((_context.get() or {}).get("request_id") or "background")
