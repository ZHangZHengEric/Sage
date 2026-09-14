import asyncio
import threading

import pytest

from sagents.observability.manager import ObservabilityManager, emit_async
from sagents.observability import opentelemetry_handler as otel


class Span:
    def __init__(self):
        self.attributes = {}
        self.ended = False

    def set_attribute(self, key, value):
        self.attributes[key] = value

    def set_status(self, value):
        pass

    def end(self):
        self.ended = True

    def get_span_context(self):
        return otel.trace.INVALID_SPAN_CONTEXT


class Tracer:
    def start_span(self, *args, **kwargs):
        return Span()


@pytest.mark.asyncio
async def test_async_trace_keeps_task_context_and_serializes_in_worker(monkeypatch):
    handler = otel.OpenTelemetryTraceHandler()
    handler.tracer = Tracer()
    manager = ObservabilityManager([handler])
    caller = threading.get_ident()
    threads = []
    original = handler._prepare_event

    def prepare(*args):
        threads.append(threading.get_ident())
        return original(*args)

    monkeypatch.setattr(handler, "_prepare_event", prepare)

    async def run(session):
        assert not otel._span_token_stack.get()
        await emit_async(manager, "on_llm_start", session_id=session, model_name="m",
                         messages=[{"content": session * 10000}], step_name="test")
        span = handler._get_current_span()
        await asyncio.sleep(0)
        assert handler._get_current_span() is span
        assert span.attributes["session_id"] == session
        assert session * 10000 in span.attributes["llm.messages"]
        await emit_async(manager, "on_llm_end", "complete")
        assert span.ended
        assert not otel._span_token_stack.get()
        return span

    spans = await asyncio.gather(run("first"), run("second"))
    assert spans[0] is not spans[1]
    assert threads and all(t != caller for t in threads)


@pytest.mark.asyncio
async def test_cancel_during_end_preparation_closes_span_in_original_task(monkeypatch):
    handler = otel.OpenTelemetryTraceHandler()
    handler.tracer = Tracer()
    manager = ObservabilityManager([handler])
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = threading.Event()
    original = handler._prepare_event
    spans = []
    cleaned = []

    def prepare(event, *args):
        if event == "on_llm_end":
            loop.call_soon_threadsafe(started.set)
            release.wait(3)
        return original(event, *args)

    monkeypatch.setattr(handler, "_prepare_event", prepare)

    async def run():
        await emit_async(manager, "on_llm_start", "s", "m", [], step_name="test")
        spans.append(handler._get_current_span())
        try:
            await emit_async(manager, "on_llm_end", "result")
        finally:
            cleaned.append(not otel._span_token_stack.get())

    task = asyncio.create_task(run())
    try:
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned == [True]
        assert spans[0].ended
    finally:
        release.set()
