"""Public observation contracts, instrumentation and process-owned provider."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.observability.provider import ObservabilityProvider as ObservabilityProvider
    from sagents.v2.runtime.observability.provider import create_observability_provider as create_observability_provider
    from sagents.v2.runtime.observability.provider import ObservabilityConfig as ObservabilityConfig


from typing import TYPE_CHECKING

from sagents.v2._lazy import exported_names, resolve_export
from .evidence.redaction import redact as redact_evidence

if TYPE_CHECKING:
    from .provider import (
        ObservabilityConfig as ObservabilityConfig,
        ObservabilityProvider as ObservabilityProvider,
        create_observability_provider as create_observability_provider,
    )

from sagents.v2.runtime.observability.contracts import (
    DiagnosticEvidenceSource,
    DiagnosticSink,
    ModelHistoryQuery,
    PerformanceQuery,
    TraceQuery,
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
    "ObservabilityProvider": (
        "sagents.v2.runtime.observability.provider",
        "ObservabilityProvider",
    ),
    "create_observability_provider": (
        "sagents.v2.runtime.observability.provider",
        "create_observability_provider",
    ),
    "ObservabilityConfig": (
        "sagents.v2.runtime.observability.provider",
        "ObservabilityConfig",
    ),
}

__all__ = [
    "DiagnosticSink",
    "ModelHistoryQuery",
    "DiagnosticEvidenceSource",
    "PerformanceQuery",
    "TraceQuery",
    "ObservabilityConfig",
    "ObservabilityProvider",
    "create_observability_provider",
    "redact_evidence",
    "LogError",
    "LogLevel",
    "LogRecord",
    "LogSink",
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
    "redact_log_value",
    "structured_log_context",
]


def __getattr__(name: str):
    return resolve_export(name, _LAZY_EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_LAZY_EXPORTS, globals())
