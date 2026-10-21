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
from .contracts import (
    ModelHistoryQuery,
    PerformanceQuery,
    TraceQuery,
)
from .plugins.diagnostic_noop import UnavailableEvidence, UnqueryableDiagnostics
from .logs import ObservationLogs
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


class ObservabilityProvider:
    """Own signal routing, backend correlation, evidence queries and lifecycle."""

    def __init__(
        self,
        *,
        plugin_id,
        outputs=(),
        traces=None,
        diagnostics=None,
        capture_traces=None,
        config=None,
        performance_query: PerformanceQuery | None = None,
        trace_query: TraceQuery | None = None,
        model_history: ModelHistoryQuery | None = None,
    ):
        self.plugin_id = plugin_id
        self._performance_query = performance_query
        self.trace_query = trace_query
        self._model_history = model_history
        self._capture_traces = capture_traces
        self.config = ObservabilityConfig.model_validate(config or {}).model_dump(
            mode="json"
        )
        self.traces = traces if traces is not None else NoopTraceSink()
        self.diagnostics = (
            diagnostics if diagnostics is not None else UnavailableEvidence()
        )
        bind = getattr(self.diagnostics, "bind_trace_sink", None)
        if bind:
            bind(self.traces)
        self.logs = ObservationLogs(outputs, self.diagnostics)
        self.closed = False

    async def export_evidence(self, session_id: str, run_ids: set[str]):
        return await self.diagnostics.export_evidence(session_id, run_ids)

    @property
    def performance_available(self) -> bool:
        return (
            self._performance_query is not None
            and self._performance_query.available
            and not self.closed
        )

    async def report_performance(
        self,
        *,
        start: float,
        end: float,
        agent_id: str = "",
        bucket: str = "hour",
        timezone_name: str = "Asia/Shanghai",
    ):
        query = self._performance_query
        if not self.performance_available or query is None:
            raise NotImplementedError(
                "this observation provider cannot query performance"
            )
        return await query.report(
            start=start,
            end=end,
            agent_id=agent_id,
            bucket=bucket,
            timezone_name=timezone_name,
        )

    async def list_model_requests(self, *, session_id: str, run_ids: set[str] | None):
        """Query authorized Runs, or local history of a host-authorized Session.

        External backends always require the authoritative Run allowlist.
        Local Session history can remain readable when Run state is corrupt.
        """
        if not getattr(self.diagnostics, "available", True):
            return ()
        if run_ids is None:
            if self._model_history is None:
                raise ValueError("this evidence backend requires a Run allowlist")
            return await self._model_history.list_model_requests(session_id=session_id)
        if not run_ids:
            return ()
        return tuple(
            (await self.export_evidence(session_id, run_ids)).get("models", ())
        )

    async def get_model_request(self, *, session_id: str, run_id: str, request_id: str):
        if self._model_history is not None:
            return await self._model_history.get_model_request(
                session_id=session_id,
                run_id=run_id,
                request_id=request_id,
            )
        for request in await self.list_model_requests(
            session_id=session_id, run_ids={run_id}
        ):
            if request.get("request_id") == request_id:
                return request
        raise KeyError(f"model request {request_id!r} was not observed")

    async def close(self):
        if self.closed:
            return
        self.closed = True
        errors = []
        # Evidence flush can enrich/export spans; the exporter must still be live.
        for resource in (
            self.diagnostics,
            self._capture_traces,
            self.traces,
            self.logs,
        ):
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
    performance_query, trace_query, model_history = None, None, None
    try:
        if options.log_stdout:
            outputs.append(
                StdoutLogSink(
                    stream=options.log_stream,
                    min_level=options.log_level,
                    format=options.log_format,
                )
            )
        if options.log_root:
            outputs.append(
                FilesystemLogSink(
                    options.log_root,
                    filename=options.log_filename,
                    min_level=options.log_level,
                    format=options.log_format,
                    max_bytes=options.log_max_bytes,
                    backup_count=options.log_backup_count,
                )
            )
        if backend != "local":
            traces = _trace_backend(backend, options)
            if options.diagnostic_content_mode == "raw" and (
                backend == "phoenix" or options.query_backend == "jaeger"
            ):
                capture_traces = _trace_backend(
                    backend,
                    options.model_copy(
                        update={"sample_rate": 1.0, "content_mode": "raw"}
                    ),
                )
            evidence = _external_evidence(backend, options)
            if not isinstance(evidence, UnqueryableDiagnostics):
                if evidence.available:
                    performance_query = evidence
                    if backend == "phoenix":
                        from .plugins.external.phoenix import PhoenixTraceQuery

                        trace_query = PhoenixTraceQuery(evidence)
                if capture_traces is not None:
                    evidence.capture_sink = capture_traces
        elif (
            options.diagnostics_root
            and options.diagnostics_storage != "none"
            and options.diagnostic_content_mode != "off"
        ):
            if options.diagnostic_content_mode == "raw":
                raise ValueError(
                    "local diagnostics support redacted capture; use an external raw evidence backend"
                )
            if options.diagnostics_storage == "sqlite":
                from .plugins.sqlite import SessionDiagnostics

                evidence = SessionDiagnostics(Path(options.diagnostics_root))
                if evidence.available:
                    performance_query = evidence
            else:
                from .plugins.filesystem import FilesystemDiagnosticSink

                evidence = FilesystemDiagnosticSink(options.diagnostics_root)
                model_history = evidence
        return ObservabilityProvider(
            plugin_id=plugin_id,
            outputs=outputs,
            traces=traces,
            diagnostics=evidence,
            capture_traces=capture_traces,
            config=config,
            performance_query=performance_query,
            trace_query=trace_query,
            model_history=model_history,
        )
    except BaseException:
        for resource in (capture_traces, traces, *outputs):
            if resource is not None:
                resource.close()
        raise


def _trace_backend(backend, options):
    common = {
        name: getattr(options, name)
        for name in (
            "environment",
            "content_mode",
            "max_content_chars",
            "sample_rate",
            "max_queue_size",
            "max_active_spans",
            "timeout_seconds",
        )
    }
    if backend == "otlp":
        from .plugins.otlp import OtlpTraceSink

        return OtlpTraceSink(
            endpoint=options.endpoint,
            service_name=options.service_name,
            protocol=options.protocol,
            insecure=options.insecure,
            **common,
        )
    if backend == "langfuse":
        from .plugins.langfuse import LangfuseTraceSink

        return LangfuseTraceSink(
            base_url=options.base_url,
            public_key=os.getenv(options.public_key_env, ""),
            secret_key=os.getenv(options.secret_key_env, ""),
            service_name=options.service_name,
            ingestion_version=options.ingestion_version,
            **common,
        )
    from .plugins.phoenix import PhoenixTraceSink

    return PhoenixTraceSink(
        endpoint=options.endpoint,
        project_name=options.project_name,
        api_key=os.getenv(options.api_key_env, ""),
        service_name=options.service_name,
        **common,
    )


def _external_evidence(backend, options):
    from .plugins.external.diagnostics import ExternalDiagnostics

    if backend == "phoenix":
        query_url = options.query_url or options.endpoint.rstrip("/").removesuffix(
            "/v1/traces"
        )
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
    evidence = ExternalDiagnostics(
        backend=backend,
        query_url=query_url,
        project=options.project_name,
        service=options.service_name,
        environment=options.environment,
        headers=headers,
        raw_max_bytes=options.raw_max_bytes,
        capture_mode=options.diagnostic_content_mode,
    )
    return evidence
