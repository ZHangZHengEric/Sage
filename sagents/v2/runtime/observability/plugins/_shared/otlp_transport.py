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
    TraceSpanObserver,
)
from sagents.v2.runtime.observability.raw import (
    retained_size,
    json_working_size,
    raw_trace_value,
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
        max_retained_bytes: int = 32 * 1024 * 1024,
        timeout_seconds: float = 3.0,
        resource_attributes: Mapping[str, str] | None = None,
    ) -> None:
        protocol = protocol.strip().lower()
        if protocol not in {"grpc", "http"}:
            raise ValueError("protocol must be grpc or http")
        if content_mode not in {"metadata", "redacted", "raw"}:
            raise ValueError("content_mode must be metadata, redacted or raw")
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
        self.resource_attributes = dict(resource_attributes or {})
        self.content_mode, self.max_content_chars = content_mode, max_content_chars
        self.max_active_spans, self.timeout_seconds = max_active_spans, timeout_seconds
        if max_retained_bytes < 4096:
            raise ValueError("trace byte limit must be at least 4096")
        self.max_retained_bytes = max_retained_bytes
        self._retained_bytes = 0
        self._span_bytes: dict[str, int] = {}
        self._lock = threading.RLock()
        self._spans: dict[str, Any] = {}
        self._closed = False
        self.failed_exports = 0
        self.dropped_spans = 0
        self._last_warning = float("-inf")
        self._span_observer: TraceSpanObserver | None = None
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

    def set_span_observer(self, observer: TraceSpanObserver) -> None:
        self._span_observer = observer

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
                attributes = self._encode_values(span.span_id, span.attributes, lambda: self._attributes(span))
                if attributes is None:
                    self._warn("active_byte_limit", count=1)
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
                    _set_attributes(otel_span, attributes)
                    self._spans[span.span_id] = otel_span
                else:
                    self._release_bytes(span.span_id)
            # Never call host enrichment while holding the transport lock.
            if self._span_observer is not None:
                self._span_observer.span_started(self, span)
        except Exception:
            self._release_bytes(span.span_id)
            self._warn("start_span", count=1)

    def add_event(self, span_id: str, event: TraceEvent) -> None:
        try:
            # Admission, encoding and attachment form one state transition.
            # End/export cannot release the reservation while an event is
            # still being encoded, or attach it to an already ended span.
            with self._lock:
                otel_span = self._spans.get(span_id)
                if otel_span is None:
                    return
                values = self._encode_values(span_id, event.attributes,
                                             lambda: self._trace_value(event.attributes))
                if values is None:
                    self._mark_incomplete(otel_span, "event_byte_limit")
                    return
                otel_span.add_event(event.name, attributes=_otel_attributes(values),
                                    timestamp=_time_nanos(event.timestamp))
        except Exception:
            self._warn("add_event")

    def end_span(self, span: TraceSpan) -> None:
        try:
            if self._span_observer is not None and self._span_observer.defer_span_end(self, span):
                return
        except Exception:
            self._warn("span_enrichment")
        self.export_span(span)

    def export_span(self, span: TraceSpan) -> None:
        """Finish a span after optional host enrichment, without re-entering it."""
        otel_span = None
        try:
            from opentelemetry.trace import Status, StatusCode

            with self._lock:
                otel_span = self._spans.pop(span.span_id, None)
                if otel_span is None:
                    return
                attributes = self._encode_values(span.span_id, span.attributes, lambda: self._attributes(span))
                if attributes is None:
                    self._mark_incomplete(otel_span, "completion_byte_limit")
                else:
                    _set_attributes(otel_span, attributes)
                if span.status is TraceStatus.ERROR:
                    error = ({"exception.type": span.error.type,
                              "exception.message": span.error.message,
                              "exception.stacktrace": span.error.stack_trace}
                             if span.error else {"exception.message":span.attributes.get("status_message", span.name)})
                    error_values = self._encode_values(span.span_id, error, lambda: self._trace_value(error))
                    if error_values is None:
                        self._mark_incomplete(otel_span, "exception_byte_limit")
                        otel_span.set_status(Status(StatusCode.ERROR))
                    else:
                        otel_span.set_status(Status(StatusCode.ERROR, error_values["exception.message"]))
                        if span.error:
                            otel_span.add_event("exception", attributes=_otel_attributes(error_values))
                elif span.status is TraceStatus.OK:
                    otel_span.set_status(Status(StatusCode.OK))
        except Exception:
            self._warn("end_span")
        finally:
            if otel_span is not None:
                # Exporter callbacks may acquire the transport lock. All active
                # span mutations are complete before ending/exporting it.
                otel_span.end(end_time=_time_nanos(span.end_time) if span.end_time else None)

    def _mark_incomplete(self, span, operation):
        span.set_attribute("sage.content.incomplete", True)
        self._warn(operation)

    def _encode_values(self, span_id, source, encode):
        """Reserve source content before any copies or JSON encoding.

        Called with the transport lock held; an end/export transition cannot
        race the reservation. Adjust to projected size before storing it.
        """
        reserved = self._reserve_bytes(span_id, source)
        if not reserved:
            return None
        try:
            # Flatten nested attributes while the temporary reservation is
            # still held. All subsequent setters receive scalar OTLP values.
            values = _otel_attributes(encode())
            available = self.max_retained_bytes - self._retained_bytes + reserved
            projected = retained_size(values, available // 2) * 2 + 512
            if projected > available:
                self._refund_bytes(span_id, reserved)
                return None
            difference = projected - reserved
            self._retained_bytes += difference
            self._span_bytes[span_id] += difference
            return values
        except BaseException:
            self._refund_bytes(span_id, reserved)
            raise

    def _refund_bytes(self, span_id, size):
        self._retained_bytes -= size
        remaining = self._span_bytes[span_id] - size
        if remaining:
            self._span_bytes[span_id] = remaining
        else:
            self._span_bytes.pop(span_id)

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
                "sage.content.mode": self.content_mode,
                **span.attributes,
            }
        )
        for key in ("input", "output", "user_input", "arguments", "result"):
            if key in values:
                values[key] = (raw_trace_value(values[key]) if self.content_mode == "raw"
                               else trace_content(self, values[key]))
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
        projected = self._trace_value(values)
        # Content-free timing rows are control data. Truncating their JSON makes
        # the performance projection unreadable, independently of content mode.
        if span.name == "agent.run" and "sage.performance.data" in values:
            payload = values["sage.performance.data"]
            # Each string element respects the SDK's attribute length limit;
            # an OTLP string array preserves the complete control payload.
            projected["sage.performance.data"] = tuple(
                payload[offset:offset + self.max_content_chars]
                for offset in range(0, len(payload), self.max_content_chars)
            )
        return projected

    def _trace_value(self, value: Any) -> Any:
        if self.content_mode == "raw":
            return raw_trace_value(value)
        return safe_trace_value(value, limit=self.max_content_chars)

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
                for span in spans:
                    sink._release_bytes(format(span.context.span_id, "016x"))
                    if not injected:
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
                    sink._release_bytes(format(span.context.span_id, "016x"))
                    sink._warn("queue_full", count=1)
                    return
                try:
                    super().on_end(span)
                except Exception:
                    pending.release()
                    sink._release_bytes(format(span.context.span_id, "016x"))
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
            resource=Resource.create({**self.resource_attributes, SERVICE_NAME: self.service_name}),
            sampler=TraceIdRatioBased(sample_rate),
            id_generator=SageIdGenerator(),
            span_limits=SpanLimits(
                max_attributes=-1 if self.content_mode == "raw" else None,
                max_span_attributes=-1 if self.content_mode == "raw" else None,
                max_events=-1 if self.content_mode == "raw" else None,
                max_event_attributes=-1 if self.content_mode == "raw" else None,
                max_attribute_length=-1 if self.content_mode == "raw" else self.max_content_chars + 128,
                max_span_attribute_length=-1 if self.content_mode == "raw" else self.max_content_chars + 128,
            ),
            shutdown_on_exit=False,
        )
        provider.add_span_processor(processor)
        return provider, provider.get_tracer("sagents.v2")

    def _reserve_bytes(self, span_id, values):
        with self._lock:
            available = self.max_retained_bytes - self._retained_bytes
            # Reserve both Python object and its encoded OTLP representation.
            # Holds through active, queued and in-flight phases until export.
            size = retained_size(values, available // 2) * 2 + 512
            if size > available:
                return 0
            if self.content_mode == "raw":
                # JSON strings may grow sixfold for control characters. The
                # projections can keep three independent encoded aliases plus
                # encoder temporaries; reserve their worst case before calling
                # any raw normalizer, backend projection or JSON serializer.
                temporary = json_working_size(values, (available - size) // 6)
                size += temporary * 6
                if size > available:
                    return 0
            self._retained_bytes += size
            self._span_bytes[span_id] = self._span_bytes.get(span_id, 0) + size
            return size

    def _release_bytes(self, span_id):
        with self._lock:
            self._retained_bytes -= self._span_bytes.pop(span_id, 0)

    def statistics(self) -> dict[str, int]:
        with self._lock:
            return {
                "failed_exports": self.failed_exports,
                "dropped_spans": self.dropped_spans,
                "active_spans": len(self._spans),
                "retained_bytes": self._retained_bytes,
                "max_retained_bytes": self.max_retained_bytes,
            }

    def close(self) -> None:
        try:
            if self._span_observer is not None:
                self._span_observer.flush_trace_sink(self)
        except Exception:
            self._warn("span_enrichment_shutdown")
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
        if isinstance(value, (bool, int, float, str)) or (
            key == "sage.performance.data" and isinstance(value, (list, tuple))
        )
        else json.dumps(value, ensure_ascii=False, default=str)
        for key, value in dict(values or {}).items()
        if value is not None
    }


def _time_nanos(value: datetime) -> int:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1_000_000_000)
