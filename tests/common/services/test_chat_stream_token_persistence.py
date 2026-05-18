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
            user_id="user-1",
            available_skills=[],
            agent_id="agent-1",
            request_source="api/web-stream",
            execution_started_at=None,
        )
        self.agent_skill_manager = None
        self.sage_engine = SimpleNamespace(session_context=None)

    async def process_stream(self):
        yield {
            "type": "assistant_text",
            "role": "assistant",
            "content": "hello",
            "message_id": "m-1",
        }
        yield {
            "type": "token_usage",
            "role": "assistant",
            "content": "",
            "message_id": "m-token",
            "metadata": {
                "token_usage": {
                    "total_info": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                    "per_step_info": [
                        {"step_name": "direct_execution", "usage": {"total_tokens": 15}}
                    ],
                }
            },
        }
        await asyncio.sleep(10)


def test_execute_chat_session_persists_token_usage_when_generator_closes_early(monkeypatch):
    calls = []

    async def _fake_persist(stream_service, *, token_usage_payload=None):
        calls.append(token_usage_payload)
        return True

    async def _fake_finalize(request, original_skills):
        calls.append("finalize")

    monkeypatch.setattr(chat_service, "_persist_token_usage_if_available", _fake_persist)
    monkeypatch.setattr(chat_service, "_finalize_session_end", _fake_finalize)

    async def _run():
        generator = chat_service.execute_chat_session(_FakeStreamService())
        first_chunk = await generator.__anext__()
        assert '"type": "assistant_text"' in first_chunk
        second_chunk = await generator.__anext__()
        assert '"type": "token_usage"' in second_chunk
        await generator.aclose()

    asyncio.run(_run())

    assert isinstance(calls[0], dict)
    assert calls[0]["total_info"]["total_tokens"] == 15
    assert calls[1] == "finalize"


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


def test_stream_manager_stop_session_times_out_when_background_task_hangs(monkeypatch):
    """回归 commit 8dfad2fb：stop_session 给 await task 加了 5s 超时封顶。

    构造一个 generator，其 finally 里 await 一个永远不返回的 future，模拟
    aclose / 锁等待卡死场景；原实现的无超时 await task 会在这里挂住整条
    中断链路，新实现应在短时间内放弃等待并继续后续清理。
    """
    manager = StreamManager.get_instance()
    # 把 5s 阈值压到 100ms，便于在 pytest 全局 2s timeout 内验证。
    monkeypatch.setattr(manager, "_STOP_SESSION_TIMEOUT", 0.1)

    async def _hanging_generator():
        try:
            yield '{"type":"assistant_text"}\n'
            await asyncio.sleep(10)
        finally:
            # 模拟 generator 的清理逻辑被某个永远不返回的 await 挡住，
            # 让 task 在被 cancel 之后依然无法终止。
            await asyncio.Future()

    async def _run() -> float:
        session_id = "session-stop-hang"
        lock = asyncio.Lock()
        await lock.acquire()
        await manager.start_session(session_id, "query", _hanging_generator(), lock)
        await asyncio.sleep(0.01)

        start = asyncio.get_event_loop().time()
        await manager.stop_session(session_id)
        elapsed = asyncio.get_event_loop().time() - start
        return elapsed

    elapsed = asyncio.run(_run())

    # 应在 timeout (100ms) 附近返回，给充分余量避免 CI 抖动误报。
    assert elapsed < 1.0, f"stop_session 在背景 task 卡死时未及时返回，elapsed={elapsed:.3f}s"
