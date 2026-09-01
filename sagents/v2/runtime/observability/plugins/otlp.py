"""Optional OpenTelemetry OTLP export for sage.trace.otlp."""

from __future__ import annotations

import importlib.util
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sagents.v2.runtime.observability.contracts import (
    TraceEvent,
    TraceKind,
    TraceSpan,
    TraceStatus,
)
from sagents.v2.runtime.observability.logs import redact_log_value


def otel_available() -> bool:
    """Return whether the optional OpenTelemetry SDK and an OTLP exporter exist."""

    try:
        return importlib.util.find_spec("opentelemetry.sdk.trace") is not None and (
            importlib.util.find_spec(
                "opentelemetry.exporter.otlp.proto.grpc.trace_exporter"
            )
            is not None
            or importlib.util.find_spec(
                "opentelemetry.exporter.otlp.proto.http.trace_exporter"
            )
            is not None
        )
    except ModuleNotFoundError:
        return False


_KIND_MAP = {
    TraceKind.INTERNAL: "INTERNAL",
    TraceKind.CLIENT: "CLIENT",
    TraceKind.SERVER: "SERVER",
}


class OtlpTraceSink:
    """Export redacted spans to an OTLP collector. Never participates in recovery."""

    format_version = "sage.trace/v1"

    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:4317",
        service_name: str = "sage",
        protocol: str = "grpc",
        insecure: bool = True,
        exporter: Any | None = None,
    ) -> None:
        protocol = str(protocol or "grpc").strip().lower()
        if protocol not in {"grpc", "http"}:
            raise ValueError("protocol must be grpc or http")
        self.endpoint = endpoint
        self.service_name = service_name
        self.protocol = protocol
        self.insecure = bool(insecure)
        self._lock = threading.Lock()
        self._spans: dict[str, Any] = {}
        self._provider, self._tracer = _build_tracer(
            endpoint=self.endpoint,
            service_name=self.service_name,
            protocol=self.protocol,
            insecure=self.insecure,
            exporter=exporter,
        )

    def start_span(self, span: TraceSpan) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.trace import (
                NonRecordingSpan,
                SpanContext,
                SpanKind,
                TraceFlags,
            )

            parent_context = None
            with self._lock:
                parent = self._spans.get(span.parent_span_id or "")
            if parent is not None:
                parent_context = trace.set_span_in_context(parent)
            else:
                parent_context = trace.set_span_in_context(
                    NonRecordingSpan(
                        SpanContext(
                            trace_id=int(span.trace_id, 16),
                            span_id=int(span.span_id, 16) ^ 1 or 1,
                            is_remote=True,
                            trace_flags=TraceFlags(TraceFlags.SAMPLED),
                        )
                    )
                )
            otel_span = self._tracer.start_span(
                span.name,
                context=parent_context,
                kind=getattr(SpanKind, _KIND_MAP[span.kind]),
                start_time=_time_nanos(span.start_time),
            )
            _set_attributes(otel_span, _span_attributes(span))
            with self._lock:
                self._spans[span.span_id] = otel_span
        except Exception:
            return

    def add_event(self, span_id: str, event: TraceEvent) -> None:
        try:
            with self._lock:
                otel_span = self._spans.get(span_id)
            if otel_span is None:
                return
            otel_span.add_event(
                event.name,
                attributes=_otel_attributes(event.attributes),
                timestamp=_time_nanos(event.timestamp),
            )
        except Exception:
            return

    def end_span(self, span: TraceSpan) -> None:
        try:
            from opentelemetry.trace import Status, StatusCode

            with self._lock:
                otel_span = self._spans.pop(span.span_id, None)
            if otel_span is None:
                return
            _set_attributes(otel_span, _span_attributes(span))
            if span.status is TraceStatus.ERROR:
                otel_span.set_status(
                    Status(
                        StatusCode.ERROR,
                        span.error.message if span.error is not None else span.name,
                    )
                )
                if span.error is not None and span.error.stack_trace:
                    otel_span.add_event(
                        "exception",
                        attributes={
                            "exception.type": span.error.type,
                            "exception.message": span.error.message,
                            "exception.stacktrace": span.error.stack_trace[-16_000:],
                        },
                    )
            elif span.status is TraceStatus.OK:
                otel_span.set_status(Status(StatusCode.OK))
            otel_span.end(
                end_time=_time_nanos(span.end_time) if span.end_time is not None else None
            )
        except Exception:
            return

    def close(self) -> None:
        try:
            self._provider.force_flush()
            self._provider.shutdown()
        except Exception:
            return
        with self._lock:
            self._spans.clear()


def _build_tracer(
    *,
    endpoint: str,
    service_name: str,
    protocol: str,
    insecure: bool,
    exporter: Any | None,
) -> tuple[Any, Any]:
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    if exporter is None:
        if protocol == "http":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint)
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=insecure)
        processor = BatchSpanProcessor(exporter)
    else:
        processor = SimpleSpanProcessor(exporter)
    provider = TracerProvider(
        resource=Resource.create({SERVICE_NAME: service_name})
    )
    provider.add_span_processor(processor)
    return provider, provider.get_tracer("sagents.v2")


def _span_attributes(span: TraceSpan) -> dict[str, Any]:
    values: dict[str, Any] = {
        "session_id": span.session_id,
        "run_id": span.run_id,
        "turn_id": span.turn_id,
        "step_id": span.step_id,
        "tool_call_id": span.tool_call_id,
        "request_id": span.request_id,
        "correlation_id": span.correlation_id,
        "sage.trace_id": span.trace_id,
        "sage.span_id": span.span_id,
    }
    values.update(span.attributes)
    return redact_log_value(values)


def _set_attributes(span: Any, values: Mapping[str, Any]) -> None:
    for key, value in _otel_attributes(values).items():
        span.set_attribute(key, value)


def _otel_attributes(values: Mapping[str, Any] | None) -> dict[str, Any]:
    encoded: dict[str, Any] = {}
    for key, value in dict(values or {}).items():
        if value is None:
            continue
        if isinstance(value, (bool, int, float, str)):
            encoded[str(key)] = value
        else:
            encoded[str(key)] = str(value)
    return encoded


def _time_nanos(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)
