"""Context-binding facade for vendor-neutral trace spans."""

from __future__ import annotations

import contextvars
import hashlib
import json
import os
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.contracts import (
    TraceEvent,
    TraceKind,
    TraceSink,
    TraceSpan,
    TraceStatus,
)
from sagents.v2.runtime.observability.logs import _log_error, redact_log_value
from sagents.v2.runtime.observability.timing import elapsed_ms

_TRACE_PREVIEW_LIMIT = 2048


_active_span: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "sage_trace_active_span",
    default=None,
)


def current_trace_context() -> tuple[str, str] | None:
    """Return the active ``(trace_id, span_id)`` pair, if any."""

    return _active_span.get()


def session_trace_id(session_id: str) -> str:
    """Stable 128-bit trace id so one Session is one Jaeger trace."""

    return hashlib.md5(session_id.encode("utf-8")).hexdigest()


async def resolve_root_session_id(get_session, session_id: str) -> str:
    """Walk ``parent_session_id`` so forked child Sessions share one trace."""

    current = session_id
    seen: set[str] = set()
    while current:
        if current in seen:
            return current
        seen.add(current)
        try:
            session = await get_session(current)
        except Exception:
            return current
        parent = getattr(session, "parent_session_id", None)
        if not parent:
            return current
        current = parent
    return session_id


def preview_trace_value(value: Any, *, limit: int = _TRACE_PREVIEW_LIMIT) -> Any:
    """Redact and truncate values before they become span attributes."""

    redacted = redact_log_value(value)
    if isinstance(redacted, str):
        text = redacted
    elif isinstance(redacted, (bool, int, float)) or redacted is None:
        return redacted
    else:
        try:
            text = json.dumps(redacted, ensure_ascii=False, default=str)
        except Exception:
            text = str(redacted)
    if len(text) > limit:
        return text[:limit] + "…"
    return text


class SpanHandle:
    """In-flight span that records events and ends without raising."""

    def __init__(self, sink: TraceSink, span: TraceSpan) -> None:
        self.sink = sink
        self.span = span
        self._ended = False
        self._token = _active_span.set((span.trace_id, span.span_id))

    def add_event(
        self,
        name: str,
        attributes: Mapping[str, Any] | None = None,
        *,
        timestamp: datetime | None = None,
    ) -> None:
        event = TraceEvent(
            name=name,
            timestamp=timestamp or utc_now(),
            attributes=redact_log_value(dict(attributes or {})),
        )
        self.span.events.append(event)
        try:
            self.sink.add_event(self.span.span_id, event)
        except Exception:
            return

    def end(
        self,
        status: TraceStatus | str = TraceStatus.OK,
        *,
        error: BaseException | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> None:
        finished = utc_now()
        duration = elapsed_ms(self.span.start_time, finished)
        merged = dict(self.span.attributes)
        if duration is not None:
            merged.setdefault("duration_ms", duration)
        merged.update(redact_log_value(dict(attributes or {})))
        self.span = self.span.model_copy(
            update={
                "end_time": finished,
                "status": TraceStatus(status),
                "error": _log_error(error),
                "attributes": merged,
            }
        )
        if self._ended:
            return
        self._ended = True
        try:
            self.sink.end_span(self.span)
        except Exception:
            pass
        finally:
            try:
                _active_span.reset(self._token)
            except Exception:
                return


class StructuredTracer:
    """Small facade that keeps span identities and context uniform."""

    def __init__(
        self,
        sink: TraceSink,
        component: str,
        *,
        context: Mapping[str, Any] | None = None,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> None:
        self.sink = sink
        self.component = component
        self.context = dict(context or {})
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id

    def bind(self, **context: Any) -> "StructuredTracer":
        return StructuredTracer(
            self.sink,
            self.component,
            context={**self.context, **context},
            trace_id=self.trace_id,
            parent_span_id=self.parent_span_id,
        )

    def start_span(
        self,
        name: str,
        *,
        kind: TraceKind | str = TraceKind.INTERNAL,
        attributes: Mapping[str, Any] | None = None,
        **context: Any,
    ) -> SpanHandle:
        values = {**self.context, **context}
        known = {
            key: values.pop(key, None)
            for key in (
                "session_id",
                "run_id",
                "turn_id",
                "step_id",
                "tool_call_id",
                "request_id",
                "correlation_id",
            )
        }
        explicit_trace_id = values.pop("trace_id", None)
        explicit_parent = values.pop("parent_span_id", None)
        active = current_trace_context()
        span = TraceSpan(
            trace_id=(active[0] if active else None)
            or explicit_trace_id
            or self.trace_id
            or new_trace_id(),
            span_id=new_span_id(),
            parent_span_id=explicit_parent
            or self.parent_span_id
            or (active[1] if active else None),
            name=name,
            kind=TraceKind(kind),
            attributes=redact_log_value(
                {"component": self.component, **values, **dict(attributes or {})}
            ),
            **known,
        )
        try:
            self.sink.start_span(span)
        except Exception:
            pass
        return SpanHandle(self.sink, span)


def new_trace_id() -> str:
    return os.urandom(16).hex()


def new_span_id() -> str:
    return os.urandom(8).hex()
