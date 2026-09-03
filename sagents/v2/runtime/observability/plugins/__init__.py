"""Observability plugins exposed without eager sibling imports."""

from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
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

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
