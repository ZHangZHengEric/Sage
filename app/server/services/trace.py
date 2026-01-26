import asyncio
from typing import Any, Dict, List

from loguru import logger
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ..core import config
from ..models.trace import TraceDao, TraceSpan


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
        logger.info("TraceService worker stopped")

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


async def initialize_trace_system():
    """初始化Trace系统"""
    cfg = config.get_startup_config()
    
    # Check if Trace Provider is already initialized to prevent overwriting
    if isinstance(trace.get_tracer_provider(), TracerProvider):
        logger.info("Trace 系统已初始化")
    else:
        try:
            from .trace_exporter import SageSpanExporter
            
            resource = Resource(attributes={
                SERVICE_NAME: "sage-server"
            })
            provider = TracerProvider(resource=resource)

            # 1. Internal Exporter (for Workflow Panel) - Optional
            processor = BatchSpanProcessor(SageSpanExporter())
            provider.add_span_processor(processor)

            # 2. OTLP Exporter (for Jaeger/external)
            if cfg and cfg.trace_jaeger_endpoint:
                otlp_exporter = OTLPSpanExporter(endpoint=cfg.trace_jaeger_endpoint, insecure=True)
                otlp_processor = BatchSpanProcessor(otlp_exporter)
                provider.add_span_processor(otlp_processor)

            # Set global provider
            trace.set_tracer_provider(provider)

            # Start TraceService worker
            await TraceService.get_instance().start()
            logger.info("Trace 系统已初始化")
        except Exception as e:
            logger.error(f"Trace 系统初始化失败: {e}")


async def close_trace_system():
    """关闭Trace系统"""
    # 1. Shutdown Trace Provider (Flush spans)
    provider = trace.get_tracer_provider()
    if isinstance(provider, TracerProvider):
        try:
            provider.shutdown()
            logger.info("Trace Provider 已关闭")
        except Exception as e:
            logger.error(f"Trace Provider 关闭失败: {e}")

    # 2. Stop Trace Service (Drain queue to DB)
    try:
        await TraceService.get_instance().stop()
    finally:
        logger.info("Trace Service 已关闭")
