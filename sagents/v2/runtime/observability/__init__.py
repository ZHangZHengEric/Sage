"""Optional diagnostics and tracing sinks."""

from sagents.v2._lazy import exported_names, resolve_export

from sagents.v2.runtime.observability.contracts import (
    DiagnosticSink,
    LogError,
    LogLevel,
    LogRecord,
    LogSink,
    TraceEvent,
    TraceKind,
    TraceSink,
    TraceSpan,
    TraceStatus,
)
from sagents.v2.runtime.observability.logs import (
    StructuredLogger,
    StructuredLoggingHandler,
    encode_log_record,
    format_log_record,
    install_standard_logging,
    redact_log_value,
    structured_log_context,
)
from sagents.v2.runtime.observability.traces import (
    SpanHandle,
    StructuredTracer,
    current_trace_context,
    preview_trace_value,
    resolve_root_session_id,
    session_trace_id,
)

_LAZY_EXPORTS = {
    "FilesystemDiagnosticSink": (
        "sagents.v2.runtime.observability.plugins.filesystem",
        "FilesystemDiagnosticSink",
    ),
    "FilesystemLogSink": (
        "sagents.v2.runtime.observability.plugins.logging_filesystem",
        "FilesystemLogSink",
    ),
    "NoopDiagnosticSink": (
        "sagents.v2.runtime.observability.plugins.diagnostic_noop",
        "NoopDiagnosticSink",
    ),
    "NoopLogSink": (
        "sagents.v2.runtime.observability.plugins.logging_noop",
        "NoopLogSink",
    ),
    "NoopTraceSink": (
        "sagents.v2.runtime.observability.plugins.trace_noop",
        "NoopTraceSink",
    ),
    "OtlpTraceSink": ("sagents.v2.runtime.observability.plugins.otlp", "OtlpTraceSink"),
    "StdoutLogSink": (
        "sagents.v2.runtime.observability.plugins.logging_stdout",
        "StdoutLogSink",
    ),
    "otel_available": (
        "sagents.v2.runtime.observability.plugins.otlp",
        "otel_available",
    ),
}

__all__ = [
    "DiagnosticSink",
    "FilesystemDiagnosticSink",
    "FilesystemLogSink",
    "StdoutLogSink",
    "LogError",
    "LogLevel",
    "LogRecord",
    "LogSink",
    "NoopDiagnosticSink",
    "NoopLogSink",
    "NoopTraceSink",
    "OtlpTraceSink",
    "SpanHandle",
    "StructuredLogger",
    "StructuredLoggingHandler",
    "StructuredTracer",
    "current_trace_context",
    "preview_trace_value",
    "resolve_root_session_id",
    "session_trace_id",
    "TraceEvent",
    "TraceKind",
    "TraceSink",
    "TraceSpan",
    "TraceStatus",
    "encode_log_record",
    "format_log_record",
    "install_standard_logging",
    "otel_available",
    "redact_log_value",
    "structured_log_context",
]


def __getattr__(name: str):
    return resolve_export(name, _LAZY_EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_LAZY_EXPORTS, globals())
