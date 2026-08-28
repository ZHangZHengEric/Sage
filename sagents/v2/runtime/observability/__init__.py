"""Optional diagnostics and tracing sinks."""

from sagents.v2.runtime.observability.contracts import (
    DiagnosticSink,
    NoopDiagnosticSink,
)
from sagents.v2.runtime.observability.filesystem import FilesystemDiagnosticSink

__all__ = ["DiagnosticSink", "FilesystemDiagnosticSink", "NoopDiagnosticSink"]
