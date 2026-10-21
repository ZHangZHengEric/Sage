"""One process-owned observation module: outputs, evidence and shutdown.

Signal-specific ports are internal collaborators, never separate selections.
Observation evidence is independent of authoritative Session storage.
"""
from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Literal
from urllib.parse import unquote

from pydantic import Field

from sagents.v2.contracts.common import StrictModel
from .contracts import LogLevel, LogRecord
from .plugins.diagnostic_noop import NoopDiagnosticSink
from .plugins.logging_stdout import StdoutLogSink
from .plugins.logging_filesystem import FilesystemLogSink
from .plugins.trace_noop import NoopTraceSink


class ObservabilityConfig(StrictModel):
    log_stdout: bool = True
    log_stream: Literal["stdout", "stderr"] = "stdout"
    log_root: str | None = None
    log_filename: str = "sage.jsonl"
    log_level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    log_format: Literal["json", "text"] = "json"
    log_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    log_backup_count: int = Field(default=5, ge=1)
    diagnostics_root: str | None = None
    diagnostics_storage: Literal["files", "sqlite", "none"] = "files"
    diagnostic_content_mode: Literal["off", "redacted", "raw"] = "redacted"
    raw_max_bytes: int = Field(default=16 * 1024 * 1024, ge=4096)
    endpoint: str = "http://127.0.0.1:4317"
    base_url: str = ""
    service_name: str = "sage"
    environment: str = "production"
    protocol: Literal["grpc", "http"] = "grpc"
    insecure: bool = True
    project_name: str = "sage"
    api_key_env: str = "PHOENIX_API_KEY"
    public_key_env: str = "LANGFUSE_PUBLIC_KEY"
    secret_key_env: str = "LANGFUSE_SECRET_KEY"
    ingestion_version: Literal[3, 4] = 4
    content_mode: Literal["metadata", "redacted", "raw"] = "redacted"
    max_content_chars: int = Field(default=16384, ge=256, le=65536)
    sample_rate: float = Field(default=1, ge=0, le=1)
    max_queue_size: int = Field(default=2048, ge=1)
    max_active_spans: int = Field(default=4096, ge=1)
    timeout_seconds: float = Field(default=3, gt=0, le=30)
    query_url: str = ""
    query_backend: Literal["", "jaeger"] = ""
    query_headers_env: str = "SAGE_OBSERVABILITY_QUERY_HEADERS"


class UnavailableEvidence(NoopDiagnosticSink):
    available = False
    raw_capture = False
    capture_failures = 0

    def write(self, record):
        pass

    async def list_model_requests(self, **kwargs):
        return ()

    async def get_model_request(self, **kwargs):
        raise KeyError("model evidence is not collected by this provider")

    async def export_evidence(self, session_id, run_ids):
        return {"models": [], "logs": [], "unavailable": True,
                "evidence_source": "not_collected"}


_ROUTINE_TIMINGS = frozenset({
    "agent.state.commit", "session.redis.commit", "agent.preparation.completed",
    "server.admission.phase", "session.mysql.archived",
})


class ObservationLogs:
    """Capture evidence independently of output severity, then fan out safely."""
    format_version = "sage.log/v1"

    def __init__(self, outputs, evidence):
        self.outputs, self.evidence = tuple(outputs), evidence
        self.failures = 0

    @property
    def path(self):
        return next((output.path for output in self.outputs if hasattr(output, "path")), "")

    @property
    def raw_capture(self):
        return getattr(self.evidence, "raw_capture", False)

    def write(self, record: LogRecord):
        routine = (record.level == LogLevel.DEBUG and record.event in _ROUTINE_TIMINGS
                   and record.error is None and record.attributes.get("outcome", "completed") == "completed"
                   and isinstance(record.attributes.get("duration_ms"), (int, float))
                   and 0 <= record.attributes["duration_ms"] < 100)
        if self.raw_capture or not routine:
            writer = getattr(self.evidence, "write", None)
            if writer:
                try:
                    writer(record)
                except Exception:
                    self.failures += 1
        if routine:
            return
        for output in self.outputs:
            try:
                output.write(record)
            except Exception:
                self.failures += 1

    def close(self):
        for output in self.outputs:
            output.close()


class ObservabilityProvider:
    """Own signal routing, backend correlation, evidence queries and lifecycle."""
    def __init__(self, *, plugin_id, outputs=(), traces=None, diagnostics=None, capture_traces=None, config=None):
        self.plugin_id = plugin_id
        self._capture_traces = capture_traces
        self.config = ObservabilityConfig.model_validate(config or {}).model_dump(mode="json")
        self.traces = traces if traces is not None else NoopTraceSink()
        self.diagnostics = diagnostics if diagnostics is not None else UnavailableEvidence()
        bind = getattr(self.diagnostics, "bind_trace_sink", None)
        if bind:
            bind(self.traces)
        self.logs = ObservationLogs(outputs, self.diagnostics)
        self.closed = False

    async def export_evidence(self, session_id: str, run_ids: set[str]):
        export = getattr(self.diagnostics, "export_evidence", None)
        if export:
            return await export(session_id, run_ids)
        # Filesystem evidence is addressed only by the authorized Run allowlist.
        models = []
        for run_id in sorted(run_ids):
            models.extend(await self.diagnostics.list_model_requests(session_id=session_id, run_id=run_id))
        return {"models": models, "logs": [], "logs_complete": False,
                "evidence_source": "filesystem", "capture_failures_since_start": 0}

    async def close(self):
        if self.closed:
            return
        self.closed = True
        errors = []
        # Evidence flush can enrich/export spans; the exporter must still be live.
        for resource in (self.diagnostics, self._capture_traces, self.traces, self.logs):
            close = getattr(resource, "close", None)
            if close:
                try:
                    value = close()
                    if inspect.isawaitable(value):
                        await value
                except BaseException as exc:
                    errors.append(exc)
        if errors:
            raise BaseExceptionGroup("observability shutdown failed", errors)


def create_observability_provider(plugin_id: str, config=None) -> ObservabilityProvider:
    if plugin_id == "sage.observability.noop":
        ObservabilityConfig.model_validate(config or {})
        return ObservabilityProvider(plugin_id=plugin_id)
    options = ObservabilityConfig.model_validate(config or {})
    backend = plugin_id.removeprefix("sage.observability.")
    if backend not in {"local", "otlp", "langfuse", "phoenix"}:
        raise ValueError(f"unknown observability provider: {plugin_id}")
    traces, evidence, capture_traces, outputs = None, None, None, []
    try:
        if options.log_stdout:
            outputs.append(StdoutLogSink(stream=options.log_stream, min_level=options.log_level, format=options.log_format))
        if options.log_root:
            outputs.append(FilesystemLogSink(options.log_root, filename=options.log_filename,
                min_level=options.log_level, format=options.log_format,
                max_bytes=options.log_max_bytes, backup_count=options.log_backup_count))
        if backend != "local":
            traces = _trace_backend(backend, options)
            if options.diagnostic_content_mode == "raw" and (backend == "phoenix" or options.query_backend == "jaeger"):
                capture_traces = _trace_backend(backend, options.model_copy(update={"sample_rate": 1.0, "content_mode": "raw"}))
            evidence = _external_evidence(backend, options)
            if capture_traces is not None:
                evidence.capture_sink = capture_traces
        elif options.diagnostics_root and options.diagnostics_storage != "none" and options.diagnostic_content_mode != "off":
            if options.diagnostic_content_mode == "raw":
                raise ValueError("local diagnostics support redacted capture; use an external raw evidence backend")
            if options.diagnostics_storage == "sqlite":
                from .sqlite_evidence import SessionDiagnostics
                evidence = SessionDiagnostics(Path(options.diagnostics_root))
            else:
                from .plugins.filesystem import FilesystemDiagnosticSink
                evidence = FilesystemDiagnosticSink(options.diagnostics_root)
        return ObservabilityProvider(plugin_id=plugin_id, outputs=outputs, traces=traces,
                                     diagnostics=evidence, capture_traces=capture_traces, config=config)
    except BaseException:
        for resource in (capture_traces, traces, *outputs):
            if resource is not None:
                resource.close()
        raise


def _trace_backend(backend, options):
    common = {name: getattr(options, name) for name in (
        "environment", "content_mode", "max_content_chars", "sample_rate",
        "max_queue_size", "max_active_spans", "timeout_seconds",
    )}
    if backend == "otlp":
        from .plugins.otlp import OtlpTraceSink
        return OtlpTraceSink(endpoint=options.endpoint, service_name=options.service_name,
                             protocol=options.protocol, insecure=options.insecure, **common)
    if backend == "langfuse":
        from .plugins.langfuse import LangfuseTraceSink
        return LangfuseTraceSink(base_url=options.base_url,
            public_key=os.getenv(options.public_key_env, ""), secret_key=os.getenv(options.secret_key_env, ""),
            service_name=options.service_name, ingestion_version=options.ingestion_version, **common)
    from .plugins.phoenix import PhoenixTraceSink
    return PhoenixTraceSink(endpoint=options.endpoint, project_name=options.project_name,
        api_key=os.getenv(options.api_key_env, ""), service_name=options.service_name, **common)


def _external_evidence(backend, options):
    from .performance_evidence import ExternalDiagnostics, UnqueryableDiagnostics
    if backend == "phoenix":
        query_url = options.query_url or options.endpoint.rstrip("/").removesuffix("/v1/traces")
    elif backend == "otlp" and options.query_backend == "jaeger" and options.query_url:
        backend, query_url = "jaeger", options.query_url
    else:
        return UnqueryableDiagnostics(backend)
    headers = {}
    for entry in os.getenv(options.query_headers_env, "").split(","):
        key, sep, value = entry.partition("=")
        if sep:
            headers[unquote(key.strip())] = unquote(value.strip())
    if backend == "phoenix" and (key := os.getenv(options.api_key_env)):
        headers["Authorization"] = f"Bearer {key}"
    evidence = ExternalDiagnostics(backend=backend, query_url=query_url, project=options.project_name,
        service=options.service_name, environment=options.environment, headers=headers,
        raw_max_bytes=options.raw_max_bytes, capture_mode=options.diagnostic_content_mode)
    return evidence
