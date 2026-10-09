"""Optional OTLP export with exact Sage span identities and GenAI attributes."""

from __future__ import annotations

import asyncio
import contextvars
import importlib.util
import json
import logging
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sagents.v2.runtime.observability.contracts import (
    TraceEvent,
    TraceKind,
    TraceSpan,
    TraceStatus,
)
from sagents.v2.runtime.observability.content import safe_trace_value, trace_content

_LOG = logging.getLogger(__name__)
_IDENTITIES = contextvars.ContextVar("sage_otlp_ids", default=None)
_KIND_MAP = {
    TraceKind.INTERNAL: "INTERNAL",
    TraceKind.CLIENT: "CLIENT",
    TraceKind.SERVER: "SERVER",
}


def otel_available() -> bool:
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


class OtlpTraceTransport:
    """Process-owned, bounded, best-effort export; no global OTel provider."""

    format_version = "sage.trace/v1"

    def __init__(
        self,
        *,
        endpoint: str = "http://127.0.0.1:4317",
        service_name: str = "sage",
        protocol: str = "grpc",
        insecure: bool = True,
        exporter: Any | None = None,
        headers: Mapping[str, str] | None = None,
        environment: str = "production",
        content_mode: str = "redacted",
        max_content_chars: int = 16384,
        sample_rate: float = 1.0,
        max_queue_size: int = 2048,
        max_active_spans: int = 4096,
        timeout_seconds: float = 3.0,
    ) -> None:
        protocol = protocol.strip().lower()
        if protocol not in {"grpc", "http"}:
            raise ValueError("protocol must be grpc or http")
        if content_mode not in {"metadata", "redacted"}:
            raise ValueError("content_mode must be metadata or redacted")
        if not 0 <= sample_rate <= 1 or min(max_queue_size, max_active_spans) < 1:
            raise ValueError("invalid trace sampling or queue limits")
        if not 256 <= max_content_chars <= 65536 or not 0 < timeout_seconds <= 30:
            raise ValueError("invalid trace content limit or timeout")
        self.endpoint, self.service_name, self.protocol = (
            endpoint,
            service_name,
            protocol,
        )
        self.insecure, self.environment = bool(insecure), environment
        self.content_mode, self.max_content_chars = content_mode, max_content_chars
        self.max_active_spans, self.timeout_seconds = max_active_spans, timeout_seconds
        self._lock = threading.RLock()
        self._spans: dict[str, Any] = {}
        self._closed = False
        self.failed_exports = 0
        self.dropped_spans = 0
        self._last_warning = float("-inf")
        self._provider, self._tracer = self._build_tracer(
            exporter, headers, sample_rate, max_queue_size
        )

    def _warn(self, operation: str, *, count: int = 0) -> None:
        with self._lock:
            self.dropped_spans += count
            now = time.monotonic()
            if now - self._last_warning < 60:
                return
            self._last_warning = now
        # Do not print exporter exception text: it may contain auth headers.
        _LOG.warning(
            "trace export degraded: operation=%s failed_exports=%s dropped_spans=%s",
            operation,
            self.failed_exports,
            self.dropped_spans,
        )

    def start_span(self, span: TraceSpan) -> None:
        try:
            from opentelemetry import trace
            from opentelemetry.context import Context
            from opentelemetry.trace import (
                NonRecordingSpan,
                SpanContext,
                SpanKind,
                TraceFlags,
            )

            with self._lock:
                if self._closed or len(self._spans) >= self.max_active_spans:
                    self._warn("active_span_limit", count=1)
                    return
                # Explicit empty context produces a real root, independent of
                # other libraries' ambient OTel context. Remote parents need no
                # in-process handle and keep their exact W3C span identity.
                parent_context = Context()
                if span.parent_span_id:
                    parent_context = trace.set_span_in_context(
                        NonRecordingSpan(
                            SpanContext(
                                trace_id=int(span.trace_id, 16),
                                span_id=int(span.parent_span_id, 16),
                                is_remote=True,
                                trace_flags=TraceFlags(TraceFlags.SAMPLED),
                            )
                        ),
                        parent_context,
                    )
                token = _IDENTITIES.set((int(span.trace_id, 16), int(span.span_id, 16)))
                try:
                    otel_span = self._tracer.start_span(
                        span.name,
                        context=parent_context,
                        kind=getattr(SpanKind, _KIND_MAP[span.kind]),
                        start_time=_time_nanos(span.start_time),
                    )
                finally:
                    _IDENTITIES.reset(token)
                if otel_span.is_recording():
                    _set_attributes(otel_span, self._attributes(span))
                    self._spans[span.span_id] = otel_span
        except Exception:
            self._warn("start_span", count=1)

    def add_event(self, span_id: str, event: TraceEvent) -> None:
        try:
            with self._lock:
                otel_span = self._spans.get(span_id)
            if otel_span is not None:
                otel_span.add_event(
                    event.name,
                    attributes=_otel_attributes(safe_trace_value(event.attributes)),
                    timestamp=_time_nanos(event.timestamp),
                )
        except Exception:
            self._warn("add_event")

    def end_span(self, span: TraceSpan) -> None:
        try:
            from opentelemetry.trace import Status, StatusCode

            with self._lock:
                otel_span = self._spans.pop(span.span_id, None)
            if otel_span is None:
                return
            try:
                _set_attributes(otel_span, self._attributes(span))
                if span.status is TraceStatus.ERROR:
                    message = (
                        span.error.message
                        if span.error
                        else span.attributes.get("status_message", span.name)
                    )
                    otel_span.set_status(
                        Status(StatusCode.ERROR, safe_trace_value(message))
                    )
                    if span.error:
                        otel_span.add_event(
                            "exception",
                            attributes=_otel_attributes(
                                safe_trace_value(
                                    {
                                        "exception.type": span.error.type,
                                        "exception.message": span.error.message,
                                        "exception.stacktrace": span.error.stack_trace,
                                    }
                                )
                            ),
                        )
                elif span.status is TraceStatus.OK:
                    otel_span.set_status(Status(StatusCode.OK))
            finally:
                otel_span.end(
                    end_time=_time_nanos(span.end_time) if span.end_time else None
                )
        except Exception:
            self._warn("end_span")

    def _attributes(self, span: TraceSpan) -> dict[str, Any]:
        values = {
            key: getattr(span, key)
            for key in (
                "session_id",
                "run_id",
                "turn_id",
                "step_id",
                "tool_call_id",
                "request_id",
                "correlation_id",
            )
        }
        values.update(
            {
                "sage.trace_id": span.trace_id,
                "sage.span_id": span.span_id,
                "deployment.environment.name": self.environment,
                **span.attributes,
            }
        )
        for key in ("input", "output", "user_input", "arguments", "result"):
            if key in values:
                values[key] = trace_content(self, values[key])
        if span.name == "model.request":
            values.update(
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.request.model": values.get("model"),
                    "gen_ai.response.model": values.get("model"),
                    "gen_ai.provider.name": values.get("provider"),
                    "gen_ai.input.messages": values.get("input"),
                    "gen_ai.output.messages": values.get("output"),
                }
            )
            for key, value in (values.get("usage") or {}).items():
                values[f"gen_ai.usage.{key}"] = value
            for key, value in (values.get("model_parameters") or {}).items():
                values[f"gen_ai.request.{key}"] = value
            if values.get("cost") is not None:
                values["gen_ai.usage.cost"] = values["cost"]
        elif span.name == "tool.call":
            values.update(
                {
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": values.get("tool_name"),
                    "gen_ai.tool.call.id": span.tool_call_id,
                    "gen_ai.tool.call.arguments": values.get("input"),
                    "gen_ai.tool.call.result": values.get("output"),
                }
            )
        return safe_trace_value(values, limit=self.max_content_chars)

    def _build_tracer(self, exporter, headers, sample_rate, max_queue_size):
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider, SpanLimits
        from opentelemetry.sdk.trace.id_generator import RandomIdGenerator
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
            SpanExportResult,
        )

        class SageIdGenerator(RandomIdGenerator):
            def generate_trace_id(self):
                ids = _IDENTITIES.get()
                return ids[0] if ids else super().generate_trace_id()

            def generate_span_id(self):
                ids = _IDENTITIES.get()
                return ids[1] if ids else super().generate_span_id()

        injected = exporter is not None
        if exporter is None:
            if self.protocol == "http":
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                exporter = OTLPSpanExporter(
                    endpoint=self.endpoint,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            else:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

                exporter = OTLPSpanExporter(
                    endpoint=self.endpoint,
                    headers=headers,
                    insecure=self.insecure,
                    timeout=self.timeout_seconds,
                )
        sink = self
        pending = threading.BoundedSemaphore(max_queue_size)

        class MonitoredExporter:
            def export(self, spans):
                try:
                    result = exporter.export(spans)
                except Exception:
                    result = SpanExportResult.FAILURE
                if result != SpanExportResult.SUCCESS:
                    with sink._lock:
                        sink.failed_exports += 1
                    sink._warn("export", count=len(spans))
                if not injected:
                    for _ in spans:
                        pending.release()
                return result

            def shutdown(self):
                exporter.shutdown()

        class BoundedBatchProcessor(BatchSpanProcessor):
            def on_end(self, span):
                if not span.context.trace_flags.sampled:
                    return
                # Bound queued + in-flight spans. Admission is nonblocking;
                # holding permits until export also lets us count every drop
                # without inspecting private SDK queues.
                if not pending.acquire(blocking=False):
                    sink._warn("queue_full", count=1)
                    return
                try:
                    super().on_end(span)
                except Exception:
                    pending.release()
                    sink._warn("enqueue", count=1)

        processor = (
            SimpleSpanProcessor(MonitoredExporter())
            if injected
            else BoundedBatchProcessor(
                MonitoredExporter(),
                max_queue_size=max_queue_size,
                max_export_batch_size=min(512, max_queue_size),
                schedule_delay_millis=1000,
                export_timeout_millis=int(self.timeout_seconds * 1000),
            )
        )
        provider = TracerProvider(
            resource=Resource.create({SERVICE_NAME: self.service_name}),
            sampler=TraceIdRatioBased(sample_rate),
            id_generator=SageIdGenerator(),
            span_limits=SpanLimits(max_attribute_length=self.max_content_chars + 128),
            shutdown_on_exit=False,
        )
        provider.add_span_processor(processor)
        return provider, provider.get_tracer("sagents.v2")

    def statistics(self) -> dict[str, int]:
        with self._lock:
            return {
                "failed_exports": self.failed_exports,
                "dropped_spans": self.dropped_spans,
                "active_spans": len(self._spans),
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            unfinished = tuple(self._spans.values())
            self._spans.clear()
        for span in unfinished:
            span.set_attribute("sage.interrupted", True)
            span.end()

        def shutdown():
            try:
                self._provider.force_flush(
                    timeout_millis=int(self.timeout_seconds * 1000)
                )
                self._provider.shutdown()
            except Exception:
                self._warn("shutdown")

        worker = threading.Thread(
            target=shutdown, daemon=True, name="sage-trace-shutdown"
        )
        worker.start()
        worker.join(self.timeout_seconds)
        if worker.is_alive():
            self._warn("shutdown_timeout")

    async def stop(self, reason=None) -> None:
        await asyncio.to_thread(self.close)


def _set_attributes(span: Any, values: Mapping[str, Any]) -> None:
    for key, value in _otel_attributes(values).items():
        span.set_attribute(key, value)


def _otel_attributes(values: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        str(key): value
        if isinstance(value, (bool, int, float, str))
        else json.dumps(value, ensure_ascii=False, default=str)
        for key, value in dict(values or {}).items()
        if value is not None
    }


def _time_nanos(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)
