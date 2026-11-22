"""Best-effort elapsed-time helpers for diagnostics and traces."""

from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any


_framework_phases: ContextVar[dict[str, tuple[int, float]] | None] = ContextVar(
    "framework_phases", default=None
)


@contextmanager
def collect_framework_phases(*, enabled: bool):
    totals: dict[str, tuple[int, float]] = {}
    token = _framework_phases.set(totals if enabled else None)
    try:
        yield totals
    finally:
        _framework_phases.reset(token)


def record_framework_phase(name: str, seconds: float) -> None:
    totals = _framework_phases.get()
    if totals is not None:
        count, elapsed = totals.get(name, (0, 0.0))
        totals[name] = count + 1, elapsed + seconds


def framework_phase_attributes(totals: dict[str, tuple[int, float]]) -> dict[str, Any]:
    return {
        "framework_phases": {
            name: {"count": count, "duration_ms": round(seconds * 1000, 3)}
            for name, (count, seconds) in totals.items()
        }
    } if totals else {}


@contextmanager
def log_duration(logger, event: str, message: str, *, attributes=None, aggregate_phase=None, **context):
    """Measure a boundary without capturing inputs or changing its outcome."""
    started = perf_counter()
    outcome = "completed"
    try:
        yield
    except BaseException:
        outcome = "failed"
        raise
    finally:
        elapsed = perf_counter() - started
        if aggregate_phase is not None:
            record_framework_phase(aggregate_phase, elapsed)
        if logger is not None:
            logger.debug(
                event,
                message,
                **context,
                attributes={
                    **(attributes or {}),
                    "outcome": outcome,
                    "duration_ms": round(elapsed * 1000, 3),
                },
            )


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
