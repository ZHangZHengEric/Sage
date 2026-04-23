import asyncio
import sys
import types
from types import SimpleNamespace

if "rank_bm25" not in sys.modules:
    rank_bm25_stub = types.ModuleType("rank_bm25")

    class _BM25Okapi:
        def __init__(self, *args, **kwargs):
            pass

    rank_bm25_stub.BM25Okapi = _BM25Okapi
    sys.modules["rank_bm25"] = rank_bm25_stub

if "pytz" not in sys.modules:
    sys.modules["pytz"] = types.ModuleType("pytz")

if "opentelemetry" not in sys.modules:
    trace_module = types.ModuleType("opentelemetry.trace")
    context_module = types.ModuleType("opentelemetry.context")

    class _DummySpan:
        def record_exception(self, *args, **kwargs):
            pass

        def set_status(self, *args, **kwargs):
            pass

        def end(self):
            pass

    class _DummyTracer:
        def start_span(self, *args, **kwargs):
            return _DummySpan()

    class _Status:
        def __init__(self, *args, **kwargs):
            pass

    class _StatusCode:
        ERROR = "ERROR"
        OK = "OK"

    trace_module.get_tracer = lambda *args, **kwargs: _DummyTracer()
    trace_module.set_span_in_context = lambda span: span
    trace_module.Span = _DummySpan
    trace_module.Status = _Status
    trace_module.StatusCode = _StatusCode
    context_module.attach = lambda ctx: object()
    context_module.detach = lambda token: None

    opentelemetry_module = types.ModuleType("opentelemetry")
    opentelemetry_module.trace = trace_module
    opentelemetry_module.context = context_module

    sys.modules["opentelemetry"] = opentelemetry_module
    sys.modules["opentelemetry.trace"] = trace_module
    sys.modules["opentelemetry.context"] = context_module

from common.services import chat_service
from common.services.chat_stream_manager import StreamManager


class _FakeStreamService:
    def __init__(self):
        self.request = SimpleNamespace(
            session_id="session-web-stream",
            available_skills=[],
            agent_id="agent-1",
        )
        self.agent_skill_manager = None

    async def process_stream(self):
        yield {
            "type": "assistant_text",
            "role": "assistant",
            "content": "hello",
            "message_id": "m-1",
        }
        await asyncio.sleep(10)


def test_execute_chat_session_persists_token_usage_when_generator_closes_early(monkeypatch):
    calls = []

    async def _fake_persist(stream_service):
        calls.append("persist")
        return True

    async def _fake_finalize(request, original_skills):
        calls.append("finalize")

    monkeypatch.setattr(chat_service, "_persist_token_usage_if_available", _fake_persist)
    monkeypatch.setattr(chat_service, "_finalize_session_end", _fake_finalize)

    async def _run():
        generator = chat_service.execute_chat_session(_FakeStreamService())
        first_chunk = await generator.__anext__()
        assert '"type": "assistant_text"' in first_chunk
        await generator.aclose()

    asyncio.run(_run())

    assert calls == ["persist", "finalize"]


def test_stream_manager_stop_session_closes_background_generator():
    manager = StreamManager.get_instance()
    closed = False

    async def _generator():
        nonlocal closed
        try:
            yield '{"type":"assistant_text"}\n'
            await asyncio.sleep(10)
        finally:
            closed = True

    async def _run():
        session_id = "session-stop-close"
        lock = asyncio.Lock()
        await lock.acquire()
        await manager.start_session(session_id, "query", _generator(), lock)
        await asyncio.sleep(0.05)
        await manager.stop_session(session_id)

    asyncio.run(_run())

    assert closed is True
