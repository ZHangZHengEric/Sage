"""Official log-sink plugin: discard every structured operational record."""

from __future__ import annotations

from sagents.v2.runtime.observability.contracts import LogRecord


class NoopLogSink:
    """Safe default used until a host explicitly selects a log sink."""

    plugin_id = "sage.logging.noop"
    name = "No-op structured log sink"
    description = "Discards structured operational logs."
    format_version = "sage.log/v1"

    def write(self, record: LogRecord) -> None:
        del record

    def close(self) -> None:
        return None
