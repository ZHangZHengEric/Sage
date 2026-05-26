import asyncio
import sys
import types
from types import SimpleNamespace

if "rank_bm25" not in sys.modules:
    rank_bm25_stub = types.ModuleType("rank_bm25")

    class _BM25Okapi:
        def __init__(self, *args, **kwargs):
            pass

    rank_bm25_stub.BM25Okapi = _BM25Okapi  # pyright: ignore[reportAttributeAccessIssue]
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

    trace_module.get_tracer = lambda *args, **kwargs: _DummyTracer()  # pyright: ignore[reportAttributeAccessIssue]
    trace_module.set_span_in_context = lambda span: span  # pyright: ignore[reportAttributeAccessIssue]
    trace_module.Span = _DummySpan  # pyright: ignore[reportAttributeAccessIssue]
    trace_module.Status = _Status  # pyright: ignore[reportAttributeAccessIssue]
    trace_module.StatusCode = _StatusCode  # pyright: ignore[reportAttributeAccessIssue]
    context_module.attach = lambda ctx: object()  # pyright: ignore[reportAttributeAccessIssue]
    context_module.detach = lambda token: None  # pyright: ignore[reportAttributeAccessIssue]

    opentelemetry_module = types.ModuleType("opentelemetry")
    opentelemetry_module.trace = trace_module  # pyright: ignore[reportAttributeAccessIssue]
    opentelemetry_module.context = context_module  # pyright: ignore[reportAttributeAccessIssue]

    sys.modules["opentelemetry"] = opentelemetry_module
    sys.modules["opentelemetry.trace"] = trace_module
    sys.modules["opentelemetry.context"] = context_module

from common.services import chat_service
from common.services import conversation_service
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
        return


def test_execute_chat_session_persists_token_usage_when_generator_closes_early(
    monkeypatch,
):
    calls = []

    async def _fake_persist(stream_service, *, token_usage_payload=None):
        calls.append(token_usage_payload)
        return True

    async def _fake_finalize(request, original_skills):
        calls.append("finalize")

    monkeypatch.setattr(
        chat_service, "_persist_token_usage_if_available", _fake_persist
    )
    monkeypatch.setattr(chat_service, "_finalize_session_end", _fake_finalize)

    async def _run():
        generator = chat_service.execute_chat_session(_FakeStreamService())  # pyright: ignore[reportArgumentType]
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
    assert elapsed < 1.0, (
        f"stop_session 在背景 task 卡死时未及时返回，elapsed={elapsed:.3f}s"
    )


def test_stream_manager_background_worker_aclose_has_own_timeout(monkeypatch):
    """background worker 自己的 generator.aclose 也要有封顶，避免 task 留在 finally 里。"""
    manager = StreamManager.get_instance()
    monkeypatch.setattr(manager, "_GENERATOR_ACLOSE_TIMEOUT", 0.1)

    class _GeneratorWithHangingAclose:
        def __init__(self):
            self._sent = False

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self._sent:
                raise StopAsyncIteration
            self._sent = True
            return '{"type":"assistant_text"}\n'

        async def aclose(self):
            await asyncio.Future()

    async def _run() -> tuple[float, bool, bool]:
        session_id = "session-worker-aclose-hang"
        lock = asyncio.Lock()
        await lock.acquire()
        await manager.start_session(
            session_id, "query", _GeneratorWithHangingAclose(), lock
        )
        session = manager._sessions[session_id]
        start = asyncio.get_event_loop().time()
        await asyncio.wait_for(session.task, timeout=1.0)  # pyright: ignore[reportArgumentType]
        elapsed = asyncio.get_event_loop().time() - start
        return elapsed, bool(session.task and session.task.done()), lock.locked()

    elapsed, task_done, lock_locked = asyncio.run(_run())

    assert elapsed < 1.0, (
        f"background worker aclose 卡死时未及时返回，elapsed={elapsed:.3f}s"
    )
    assert task_done is True
    assert lock_locked is False


def test_persist_cancel_protection_waits_for_normal_completion(monkeypatch):
    """正常路径必须等持久化完成后返回，保护 interrupt_session 的接口语义。"""
    events = []
    conversation_service._SESSION_PERSISTENCE_TASKS.clear()

    async def _fake_persist(session_id: str):
        events.append(("start", session_id))
        await asyncio.sleep(0.01)
        events.append(("done", session_id))

    monkeypatch.setattr(conversation_service, "persist_session_state", _fake_persist)

    async def _run():
        await conversation_service.persist_session_state_with_cancel_protection(
            "persist-normal"
        )
        events.append(("returned", "persist-normal"))

    asyncio.run(_run())

    assert events == [
        ("start", "persist-normal"),
        ("done", "persist-normal"),
        ("returned", "persist-normal"),
    ]


def test_persist_cancel_protection_backgrounds_on_caller_cancellation(monkeypatch):
    """调用方取消时，持久化继续完成，但取消能立即传播给调用方。"""
    started = None
    finish = None
    events = []
    conversation_service._SESSION_PERSISTENCE_TASKS.clear()

    async def _fake_persist(session_id: str):
        events.append(("start", session_id))
        started.set()  # pyright: ignore[reportOptionalMemberAccess]
        await finish.wait()  # pyright: ignore[reportOptionalMemberAccess]
        events.append(("done", session_id))

    monkeypatch.setattr(conversation_service, "persist_session_state", _fake_persist)

    async def _run():
        nonlocal started, finish
        started = asyncio.Event()
        finish = asyncio.Event()
        task = asyncio.create_task(
            conversation_service.persist_session_state_with_cancel_protection(
                "persist-cancel"
            )
        )
        await started.wait()
        task.cancel()

        cancel_start = asyncio.get_event_loop().time()
        try:
            await task
        except asyncio.CancelledError:
            pass
        cancel_elapsed = asyncio.get_event_loop().time() - cancel_start

        finish.set()
        await asyncio.sleep(0)
        return cancel_elapsed

    cancel_elapsed = asyncio.run(_run())

    assert cancel_elapsed < 0.5
    assert events == [
        ("start", "persist-cancel"),
        ("done", "persist-cancel"),
    ]


def test_persist_cancel_protection_coalesces_same_session(monkeypatch):
    """同一 session 并发持久化只启动一个底层保存任务，避免线程池重复 CPU 序列化。"""
    started = None
    finish = None
    events = []
    conversation_service._SESSION_PERSISTENCE_TASKS.clear()

    async def _fake_persist(session_id: str):
        events.append(("start", session_id))
        started.set()  # pyright: ignore[reportOptionalMemberAccess]
        await finish.wait()  # pyright: ignore[reportOptionalMemberAccess]
        events.append(("done", session_id))

    monkeypatch.setattr(conversation_service, "persist_session_state", _fake_persist)

    async def _run():
        nonlocal started, finish
        started = asyncio.Event()
        finish = asyncio.Event()
        first = asyncio.create_task(
            conversation_service.persist_session_state_with_cancel_protection(
                "persist-singleflight"
            )
        )
        await started.wait()
        second = asyncio.create_task(
            conversation_service.persist_session_state_with_cancel_protection(
                "persist-singleflight"
            )
        )
        await asyncio.sleep(0)
        finish.set()
        await asyncio.gather(first, second)

    asyncio.run(_run())

    assert events == [
        ("start", "persist-singleflight"),
        ("done", "persist-singleflight"),
    ]
    assert conversation_service._SESSION_PERSISTENCE_TASKS == {}
