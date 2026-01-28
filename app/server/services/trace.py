import asyncio
import datetime
import typing
from typing import Any, Dict, List

from loguru import logger
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.trace import format_span_id, format_trace_id

from ..models.trace import TraceDao, TraceSpan


class SageSpanExporter(SpanExporter):
    def export(self, spans: typing.Sequence[ReadableSpan]) -> SpanExportResult:
        service = TraceService.get_instance()

        span_dicts = []
        for span in spans:
            ctx = span.get_span_context()
            parent = span.parent

            start_dt = datetime.datetime.fromtimestamp(span.start_time / 1e9)
            end_dt = datetime.datetime.fromtimestamp(span.end_time / 1e9)

            span_dict = {
                "name": span.name,
                "context": {
                    "trace_id": format_trace_id(ctx.trace_id),
                    "span_id": format_span_id(ctx.span_id),
                },
                "kind": str(span.kind),
                "parent_id": format_span_id(parent.span_id) if parent else None,
                "start_time": start_dt,
                "end_time": end_dt,
                "status": {
                    "status_code": span.status.status_code.name,
                    "description": span.status.description,
                },
                "attributes": dict(span.attributes) if span.attributes else {},
                "events": [
                    {
                        "name": event.name,
                        "timestamp": datetime.datetime.fromtimestamp(event.timestamp / 1e9).isoformat(),
                        "attributes": dict(event.attributes) if event.attributes else {},
                    }
                    for event in span.events
                ],
                "resource": dict(span.resource.attributes) if span.resource else {},
            }
            span_dicts.append(span_dict)

        service.enqueue_spans(span_dicts)
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


class TraceService:
    _instance = None
    _queue: asyncio.Queue = None
    _worker_task: asyncio.Task = None
    _running = False

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = TraceService()
        return cls._instance

    def __init__(self):
        self._queue = asyncio.Queue()
        self.dao = TraceDao()

    async def start(self):
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self):
        self._running = False
        if self._worker_task:
            await self._queue.join()
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    def enqueue_spans(self, spans: List[Dict[str, Any]]):
        if not self._running:
            return
        try:
            self._queue.put_nowait(spans)
        except asyncio.QueueFull:
            logger.warning("TraceService queue is full, dropping spans")

    async def _worker(self):
        while True:
            try:
                spans_data = await self._queue.get()
                try:
                    await self._save_spans(spans_data)
                except Exception as e:
                    logger.error(f"Error saving spans: {e}")
                finally:
                    self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in TraceService worker: {e}")

    async def _save_spans(self, spans_data: List[Dict[str, Any]]):
        trace_spans = []
        for data in spans_data:
            try:
                # Handle attributes - ensure it's a dict
                attributes = data.get("attributes", {})

                # Extract session_id from attributes
                session_id = (
                    attributes.get("session_id")
                )

                trace_span = TraceSpan(
                    span_id=str(data.get("context", {}).get("span_id")),
                    trace_id=str(data.get("context", {}).get("trace_id")),
                    session_id=session_id,
                    name=data.get("name"),
                    kind=str(data.get("kind")),
                    start_time=data.get("start_time"),
                    end_time=data.get("end_time"),
                    duration_ms=(data.get("end_time") - data.get("start_time")).total_seconds() * 1000,
                    parent_span_id=str(data.get("parent_id")) if data.get("parent_id") else None,
                    status_code=str(data.get("status", {}).get("status_code")),
                    status_message=data.get("status", {}).get("description"),
                    attributes=attributes,
                    events=data.get("events"),
                    resource=data.get("resource")
                )
                trace_spans.append(trace_span)
            except Exception as e:
                logger.error(f"Error processing span data: {e}")

        if trace_spans:
            await self.dao.save_spans(trace_spans)
