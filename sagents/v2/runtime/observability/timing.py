"""Best-effort elapsed-time helpers for diagnostics and traces."""

from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
from time import perf_counter
from typing import Any


@contextmanager
def log_duration(logger, event: str, message: str, *, attributes=None, **context):
    """Measure a boundary without capturing inputs or changing its outcome."""
    started = perf_counter()
    outcome = "completed"
    try:
        yield
    except BaseException:
        outcome = "failed"
        raise
    finally:
        if logger is not None:
            logger.debug(event, message, **context, attributes={
                **(attributes or {}),
                "outcome": outcome,
                "duration_ms": round((perf_counter() - started) * 1000, 3),
            })


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
