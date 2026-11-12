"""SAgents V2 module for model/middleware/recording.py."""

from __future__ import annotations

import json
from dataclasses import replace
from inspect import Parameter, signature

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any

from sagents.v2.contracts.common import utc_now
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.model.wire_diagnostics import WireCapture, wire_capture, wire_request_observer
from sagents.v2.runtime.observability.content import trace_content
from sagents.v2.runtime.observability.contracts import (
    DiagnosticSink,
    LogSink,
    TraceKind,
    TraceSink,
    TraceStatus,
)
from sagents.v2.runtime.observability.logs import StructuredLogger
from sagents.v2.runtime.observability.performance.recording import ModelTiming, PerformanceRecorder
from sagents.v2.runtime.observability.timing import elapsed_ms
from sagents.v2.runtime.observability.traces import (
    SpanHandle,
    StructuredTracer,
    current_trace_context,
    new_trace_id,
)


class RecordingModelProvider:
    """ModelProvider decorator that records every attempted model request."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        sink: DiagnosticSink | Callable[[], DiagnosticSink],
        session_id_resolver: Callable[[str], Awaitable[str]],
        provider_metadata: Mapping[str, Any] | None = None,
        trace_sink: TraceSink | None = None,
        log_sink: LogSink | None = None,
        performance: PerformanceRecorder | None = None,
    ) -> None:
        self.provider = provider
        self._sink = sink
        self.performance = performance
        self._timed_methods: dict[str, bool] = {}
        self.session_id_resolver = session_id_resolver
        self.provider_metadata = dict(provider_metadata or {})
        self.trace_sink = trace_sink
        self.tracer = StructuredTracer(self.trace_sink, "model")
        self.logger = (
            StructuredLogger(log_sink, "sagents.model")
            if log_sink is not None
            else None
        )

    @property
    def sink(self) -> DiagnosticSink:
        return self._sink() if callable(self._sink) else self._sink

    def _log(
        self,
        event: str,
        message: str,
        *,
        session_id: str,
        request: ModelRequest,
        error: BaseException | None = None,
        attributes: Mapping[str, Any] | None = None,
        level: str = "info",
    ) -> None:
        if self.logger is None:
            return
        bound = self.logger.bind(
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
        )
        if error is not None:
            bound.exception(event, message, error, attributes=attributes)
            return
        bound.log(level, event, message, attributes=attributes)

    async def _diagnose(self, method: str, **kwargs: Any) -> None:
        try:
            callback = getattr(self.sink, method)
            if "observed_at" in kwargs and method != "record_model_first_token":
                if method not in self._timed_methods:
                    parameters = signature(callback).parameters
                    self._timed_methods[method] = "observed_at" in parameters or any(
                        parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values()
                    )
                if not self._timed_methods[method]:
                    # Existing SDK sinks may implement the original callback signature.
                    kwargs.pop("observed_at")
            await callback(**kwargs)
        except Exception:
            if self.logger is not None:
                self.logger.warning(
                    "model.diagnostics.failed",
                    "model diagnostic write failed",
                    attributes={"operation": method},
                )

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return await self.provider.capabilities(model_binding)

    async def probe_capabilities(self, request):
        return await self.provider.probe_capabilities(request)

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        return self._stream(request)

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        session_id = await self.session_id_resolver(request.run_id)
        started_at = utc_now()
        purpose = (
            request.metadata.get("purpose")
            or self.provider_metadata.get("purpose")
            or "agent"
        )
        timing = None
        if self.performance is not None and self.performance.enabled:
            timing = ModelTiming(
                session_id, request.run_id, request.request_id, purpose,
                request.metadata.get("turn_id"), started_at,
            )
            self.performance.record_model(timing)

        def finish_timing(ended_at):
            if timing is not None and self.performance is not None:
                self.performance.record_model(replace(
                    timing, ended_at=ended_at, first_token_at=first_token_at, first_text_at=first_text_at,
                ))

        self._log(
            "model.request.started",
            "model request started",
            session_id=session_id,
            request=request,
            attributes={
                "model_binding": request.model_binding,
                "purpose": purpose,
                "agent_id": self.provider_metadata.get("agent_id"),
            },
        )
        active = current_trace_context()
        span = self.tracer.start_span(
            "model.request",
            kind=TraceKind.CLIENT,
            session_id=session_id,
            run_id=request.run_id,
            request_id=request.request_id,
            trace_id=active[0] if active else new_trace_id(),
            attributes={
                "model_binding": request.model_binding,
                "purpose": purpose,
                "input": trace_content(
                    self.trace_sink,
                    {"messages": request.messages, "tools": request.tools},
                ),
                "model_parameters": {
                    key: value
                    for key, value in {
                        "temperature": request.temperature,
                        "max_output_tokens": request.max_output_tokens,
                        "tool_choice": request.tool_choice,
                        "response_format": request.response_format,
                    }.items()
                    if value is not None
                },
            },
        )
        began = False

        async def begin(wire_request=None, *, model=None, provider_id=None):
            nonlocal began
            if began:
                return
            began = True
            metadata = self.provider_metadata
            if wire_request is not None:
                metadata = {**metadata, "provider_id": provider_id}
                if "model" not in wire_request:
                    metadata["model"] = model
            await self._diagnose(
                "begin_model_request",
                session_id=session_id,
                request=request,
                provider=metadata,
                wire_request=wire_request,
                observed_at=started_at,
            )

        async def observe_request(payload, *, model, provider, parameters):
            # An internal provider fallback sends different controls under the
            # same request ID. The span describes the last attempted payload.
            span.span.attributes.update(
                model=model, request_model=model, provider=provider, model_parameters=parameters,
            )
            await begin(payload, model=model, provider_id=provider)

        finalized = False
        first_token_at = None
        first_text_at = None
        first_output_persisted = False

        async def persist_first_output() -> None:
            nonlocal first_output_persisted
            if first_output_persisted:
                return
            if first_token_at is not None:
                if callable(getattr(self.sink, "record_model_first_token", None)):
                    await self._diagnose(
                        "record_model_first_token",
                        session_id=session_id,
                        request=request,
                        observed_at=first_token_at,
                    )
                span.add_event("first_token", timestamp=first_token_at)
            if first_text_at is not None:
                span.add_event("first_text", timestamp=first_text_at)
                span.span.attributes["first_text_ms"] = elapsed_ms(
                    started_at, first_text_at
                )
            first_output_persisted = True

        provider_stream = None
        capture = None
        if (callable(getattr(self.sink, "record_model_stream", None))
                and getattr(self.sink, "raw_capture", True)):
            limit = 8 * 1024 * 1024
            capture = WireCapture(max_bytes=limit)
        normalized_events = []
        normalized_bytes = 0
        normalized_dropped = 0
        try:
            provider_stream = self.provider.stream(request)
            async for event in _observed_events(provider_stream, capture, observe_request):
                completed = event.kind == ModelEventKind.COMPLETED
                first_token = (
                    first_token_at is None
                    and event.kind in {ModelEventKind.TEXT_DELTA, ModelEventKind.REASONING_DELTA}
                    and event.delta
                )
                first_text = first_text_at is None and (
                    (event.kind == ModelEventKind.TEXT_DELTA and event.delta and event.delta.strip())
                    or (completed and event.response and event.response.text.strip())
                )
                observed_at = utc_now() if completed or first_token or first_text else None
                if not began:
                    await begin()
                # Keep partial output even if normalization later rejects Tool JSON.
                if capture is not None and not completed:
                    value = event.model_dump(mode="json")
                    size = len(json.dumps(value, ensure_ascii=False).encode())
                    if normalized_bytes + size <= capture.max_bytes:
                        normalized_events.append(value)
                        normalized_bytes += size
                    else:
                        normalized_dropped += 1
                if first_token:
                    # Defer persistence so it never delays delivery of the first token.
                    first_token_at = observed_at
                if first_text:
                    assert observed_at is not None
                    first_text_at = observed_at
                    if timing is None:
                        self._log(
                            "model.first_text", "收到模型首段正文", level="debug",
                            session_id=session_id, request=request,
                            attributes={"model_binding": request.model_binding, "purpose": purpose,
                                        "first_text_at": first_text_at.isoformat(),
                                        "first_text_ms": elapsed_ms(started_at, first_text_at)},
                        )
                if completed:
                    assert event.response is not None and observed_at is not None
                    await persist_first_output()
                    await self._diagnose(
                        "complete_model_request",
                        session_id=session_id,
                        request=request,
                        response=event.response,
                        observed_at=observed_at,
                    )
                    _end_model_span(
                        span, started_at, first_token_at, finished=observed_at, response=event.response
                    )
                    self._log(
                        "model.request.completed",
                        "model request completed",
                        session_id=session_id,
                        request=request,
                        attributes={
                            "model_binding": request.model_binding,
                            "purpose": purpose,
                            "agent_id": self.provider_metadata.get("agent_id"),
                            "finish_reason": event.response.finish_reason,
                            "duration_ms": elapsed_ms(started_at, observed_at),
                            "ttfb_ms": elapsed_ms(started_at, first_token_at),
                            "first_text_at": first_text_at.isoformat() if first_text_at is not None else None,
                            "first_text_ms": elapsed_ms(started_at, first_text_at),
                        },
                    )
                    finish_timing(observed_at)
                    finalized = True
                yield event
        except BaseException as exc:
            # A consumer may close immediately after COMPLETED (summaries do
            # this). GeneratorExit/cancellation must not overwrite the already
            # authoritative successful diagnostic and span.
            if finalized:
                raise
            observed_at = utc_now()
            await begin()
            await persist_first_output()
            await self._diagnose(
                "fail_model_request",
                session_id=session_id,
                request=request,
                error=exc,
                observed_at=observed_at,
            )
            _end_model_span(span, started_at, first_token_at, finished=observed_at, error=exc)
            self._log(
                "model.request.failed",
                "model request failed",
                session_id=session_id,
                request=request,
                error=exc,
                attributes={"model_binding": request.model_binding, "purpose": purpose},
            )
            finish_timing(observed_at)
            finalized = True
            raise
        finally:
            if capture is not None:
                await self._diagnose(
                    "record_model_stream", session_id=session_id, request=request,
                    evidence={
                              "wire_events": capture.events, "wire_event_count": capture.observed,
                              "dropped_wire_events": capture.dropped,
                              "wire_capture_available": bool(capture.observed),
                              "normalized_events": normalized_events,
                              "dropped_normalized_events": normalized_dropped},
                )
            try:
                closer = getattr(provider_stream, "aclose", None)
                if closer is not None:
                    await closer()
            finally:
                if not finalized:
                    closed = RuntimeError("model stream closed before completion")
                    observed_at = utc_now()
                    try:
                        await begin()
                        await persist_first_output()
                        await self._diagnose(
                            "fail_model_request",
                            session_id=session_id,
                            request=request,
                            error=closed,
                            observed_at=observed_at,
                        )
                        self._log(
                            "model.request.failed",
                            "model request failed",
                            session_id=session_id,
                            request=request,
                            error=closed,
                            attributes={
                                "model_binding": request.model_binding,
                                "purpose": purpose,
                            },
                        )
                    finally:
                        finish_timing(observed_at)
                        _end_model_span(span, started_at, first_token_at, finished=observed_at, error=closed)


def _end_model_span(
    span: SpanHandle,
    started_at: datetime,
    first_token_at: datetime | None,
    *,
    finished: datetime,
    error: BaseException | None = None,
    response: ModelResponse | None = None,
) -> None:
    attributes: dict[str, Any] = {
        "duration_ms": elapsed_ms(started_at, finished),
        "ttfb_ms": elapsed_ms(started_at, first_token_at),
    }
    if first_token_at is not None:
        attributes["completion_start_time"] = first_token_at.isoformat()
    if response is not None:
        attributes.update(
            {
                "output": trace_content(
                    span.sink,
                    {"text": response.text, "tool_calls": response.tool_calls},
                ),
                "finish_reason": response.finish_reason,
                "model": response.provider_metadata.get("model")
                or next(iter(response.usage.models), None)
                or span.span.attributes.get("model"),
                "provider": response.provider_metadata.get("provider_id"),
            }
        )
        usage = response.usage
        if usage.reported or usage.input_tokens or usage.output_tokens:
            attributes["usage"] = {
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cached_input_tokens": usage.cached_input_tokens,
                "reasoning_tokens": usage.reasoning_tokens,
            }
        if usage.cost is not None:
            attributes["cost"] = usage.cost
    span.end(
        TraceStatus.ERROR if error is not None else TraceStatus.OK,
        error=error,
        attributes={
            key: value for key, value in attributes.items() if value is not None
        },
    )


async def _observed_events(stream, capture, observe_request):
    iterator = stream.__aiter__()
    while True:
        wire_token = wire_capture.set(capture)
        request_token = wire_request_observer.set(observe_request)
        try:
            event = await anext(iterator)
        except StopAsyncIteration:
            return
        finally:
            # An iterator can be resumed by a different task after a yield.
            wire_request_observer.reset(request_token)
            wire_capture.reset(wire_token)
        yield event
