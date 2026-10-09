"""SAgents V2 module for model/middleware/recording.py."""

from __future__ import annotations

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
from sagents.v2.runtime.observability.content import trace_content
from sagents.v2.runtime.observability.contracts import (
    DiagnosticSink,
    LogSink,
    TraceKind,
    TraceSink,
    TraceStatus,
)
from sagents.v2.runtime.observability.logs import StructuredLogger
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
        sink: DiagnosticSink,
        session_id_resolver: Callable[[str], Awaitable[str]],
        provider_metadata: Mapping[str, Any] | None = None,
        trace_sink: TraceSink | None = None,
        log_sink: LogSink | None = None,
    ) -> None:
        self.provider = provider
        self.sink = sink
        self.session_id_resolver = session_id_resolver
        self.provider_metadata = dict(provider_metadata or {})
        self.trace_sink = trace_sink
        self.tracer = StructuredTracer(self.trace_sink, "model")
        self.logger = (
            StructuredLogger(log_sink, "sagents.model")
            if log_sink is not None
            else None
        )

    def _log(
        self,
        event: str,
        message: str,
        *,
        session_id: str,
        request: ModelRequest,
        error: BaseException | None = None,
        attributes: Mapping[str, Any] | None = None,
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
        bound.info(event, message, attributes=attributes)

    async def _diagnose(self, method: str, **kwargs: Any) -> None:
        try:
            await getattr(self.sink, method)(**kwargs)
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
        diagnostic_request = getattr(self.provider, "diagnostic_request", None)
        try:
            wire_request = (
                diagnostic_request(request) if diagnostic_request is not None else None
            )
        except Exception as exc:
            try:
                await self._diagnose(
                    "begin_model_request",
                    session_id=session_id,
                    request=request,
                    provider=self.provider_metadata,
                )
                await self._diagnose(
                    "fail_model_request",
                    session_id=session_id,
                    request=request,
                    error=exc,
                )
            finally:
                _end_model_span(span, started_at, None, error=exc)
            self._log(
                "model.request.failed",
                "model request failed",
                session_id=session_id,
                request=request,
                error=exc,
                attributes={"model_binding": request.model_binding, "purpose": purpose},
            )
            raise
        if wire_request:
            span.span.attributes["model"] = wire_request.get("model")
            span.span.attributes["model_parameters"].update(
                {
                    key: wire_request[key]
                    for key in (
                        "temperature",
                        "top_p",
                        "max_tokens",
                        "max_completion_tokens",
                        "max_output_tokens",
                        "seed",
                        "reasoning_effort",
                        "generationConfig",
                    )
                    if key in wire_request
                }
            )
        finalized = False
        first_token_at = None
        first_text_at = None
        first_token_persisted = False

        async def persist_first_token() -> None:
            nonlocal first_token_persisted
            if first_token_at is None or first_token_persisted:
                return
            recorder = getattr(self.sink, "record_model_first_token", None)
            if recorder is not None:
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
            first_token_persisted = True

        provider_stream = None
        try:
            await self._diagnose(
                "begin_model_request",
                session_id=session_id,
                request=request,
                provider=self.provider_metadata,
                wire_request=wire_request,
            )
            provider_stream = self.provider.stream(request)
            async for event in provider_stream:
                if (
                    first_token_at is None
                    and event.kind
                    in {ModelEventKind.TEXT_DELTA, ModelEventKind.REASONING_DELTA}
                    and event.delta
                ):
                    # Capture the observation before yielding, but defer the
                    # diagnostic write so it never delays the first token.
                    first_token_at = utc_now()
                if (
                    first_text_at is None
                    and event.kind == ModelEventKind.TEXT_DELTA
                    and event.delta
                ):
                    first_text_at = utc_now()
                if event.kind == ModelEventKind.COMPLETED:
                    assert event.response is not None
                    await persist_first_token()
                    await self._diagnose(
                        "complete_model_request",
                        session_id=session_id,
                        request=request,
                        response=event.response,
                    )
                    _end_model_span(
                        span, started_at, first_token_at, response=event.response
                    )
                    finished = utc_now()
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
                            "duration_ms": elapsed_ms(started_at, finished),
                            "ttfb_ms": elapsed_ms(started_at, first_token_at),
                        },
                    )
                    finalized = True
                yield event
        except BaseException as exc:
            await persist_first_token()
            await self._diagnose(
                "fail_model_request",
                session_id=session_id,
                request=request,
                error=exc,
            )
            _end_model_span(span, started_at, first_token_at, error=exc)
            self._log(
                "model.request.failed",
                "model request failed",
                session_id=session_id,
                request=request,
                error=exc,
                attributes={"model_binding": request.model_binding, "purpose": purpose},
            )
            finalized = True
            raise
        finally:
            try:
                closer = getattr(provider_stream, "aclose", None)
                if closer is not None:
                    await closer()
            finally:
                if not finalized:
                    closed = RuntimeError("model stream closed before completion")
                    try:
                        await persist_first_token()
                        await self._diagnose(
                            "fail_model_request",
                            session_id=session_id,
                            request=request,
                            error=closed,
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
                        _end_model_span(span, started_at, first_token_at, error=closed)


def _end_model_span(
    span: SpanHandle,
    started_at: datetime,
    first_token_at: datetime | None,
    *,
    error: BaseException | None = None,
    response: ModelResponse | None = None,
) -> None:
    finished = utc_now()
    attributes = {
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
