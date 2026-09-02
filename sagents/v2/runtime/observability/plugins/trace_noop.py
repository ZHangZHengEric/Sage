"""Official trace-sink plugin: discard every span projection."""

from __future__ import annotations

from sagents.v2.runtime.observability.contracts import TraceEvent, TraceSpan


class NoopTraceSink:
    """Safe default used until a host explicitly selects a trace sink."""

    plugin_id = "sage.trace.noop"
    name = "No-op trace sink"
    description = "Discards trace spans."
    format_version = "sage.trace/v1"

    def start_span(self, span: TraceSpan) -> None:
        del span

    def add_event(self, span_id: str, event: TraceEvent) -> None:
        del span_id, event

    def end_span(self, span: TraceSpan) -> None:
        del span

    def close(self) -> None:
        return None
