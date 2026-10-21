"""Observability plugins exposed without eager sibling imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.observability.plugins.phoenix import PhoenixTraceSink as PhoenixTraceSink
    from sagents.v2.runtime.observability.plugins.phoenix import phoenix_available as phoenix_available
    from sagents.v2.runtime.observability.plugins.langfuse import LangfuseTraceSink as LangfuseTraceSink
    from sagents.v2.runtime.observability.plugins.langfuse import langfuse_available as langfuse_available
    from sagents.v2.runtime.observability.plugins.filesystem import FilesystemDiagnosticSink as FilesystemDiagnosticSink
    from sagents.v2.runtime.observability.plugins.logging_filesystem import FilesystemLogSink as FilesystemLogSink
    from sagents.v2.runtime.observability.plugins.diagnostic_noop import NoopDiagnosticSink as NoopDiagnosticSink
    from sagents.v2.runtime.observability.plugins.logging_noop import NoopLogSink as NoopLogSink
    from sagents.v2.runtime.observability.plugins.trace_noop import NoopTraceSink as NoopTraceSink
    from sagents.v2.runtime.observability.plugins.otlp import OtlpTraceSink as OtlpTraceSink
    from sagents.v2.runtime.observability.plugins.logging_stdout import StdoutLogSink as StdoutLogSink
    from sagents.v2.runtime.observability.plugins.otlp import otel_available as otel_available


from typing import TYPE_CHECKING

from sagents.v2._lazy import exported_names, resolve_export

if TYPE_CHECKING:
    from .diagnostic_noop import NoopDiagnosticSink as NoopDiagnosticSink
    from .filesystem import FilesystemDiagnosticSink as FilesystemDiagnosticSink
    from .langfuse import (
        LangfuseTraceSink as LangfuseTraceSink,
        langfuse_available as langfuse_available,
    )
    from .logging_filesystem import FilesystemLogSink as FilesystemLogSink
    from .logging_noop import NoopLogSink as NoopLogSink
    from .logging_stdout import StdoutLogSink as StdoutLogSink
    from .otlp import OtlpTraceSink as OtlpTraceSink, otel_available as otel_available
    from .phoenix import (
        PhoenixTraceSink as PhoenixTraceSink,
        phoenix_available as phoenix_available,
    )
    from .trace_noop import NoopTraceSink as NoopTraceSink


_EXPORTS = {
    "PhoenixTraceSink": (
        "sagents.v2.runtime.observability.plugins.phoenix",
        "PhoenixTraceSink",
    ),
    "phoenix_available": (
        "sagents.v2.runtime.observability.plugins.phoenix",
        "phoenix_available",
    ),
    "LangfuseTraceSink": (
        "sagents.v2.runtime.observability.plugins.langfuse",
        "LangfuseTraceSink",
    ),
    "langfuse_available": (
        "sagents.v2.runtime.observability.plugins.langfuse",
        "langfuse_available",
    ),
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
    "PhoenixTraceSink",
    "phoenix_available",
    "LangfuseTraceSink",
    "langfuse_available",
    "FilesystemDiagnosticSink",
    "FilesystemLogSink",
    "NoopDiagnosticSink",
    "NoopLogSink",
    "NoopTraceSink",
    "OtlpTraceSink",
    "StdoutLogSink",
    "otel_available",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
