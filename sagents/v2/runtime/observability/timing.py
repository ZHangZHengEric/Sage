"""Best-effort elapsed-time helpers for diagnostics and traces."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_iso_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def elapsed_ms(start: Any, end: Any) -> float | None:
    started = parse_iso_datetime(start)
    finished = parse_iso_datetime(end)
    if started is None or finished is None:
        return None
    seconds = (finished - started).total_seconds()
    if seconds < 0:
        return None
    return round(seconds * 1000, 3)
