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
from common.services import chat_stream_manager
from common.services.chat_stream_manager import StreamManager
from common.schemas.goal import GoalStatus, SessionGoal


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


class _FakeGoalToolStreamService(_FakeStreamService):
    async def process_stream(self):
        yield {
            "type": "tool_result",
            "role": "tool",
            "tool_call_id": "call-turn-status",
            "session_id": "session-web-stream",
            "metadata": {"tool_name": "turn_status"},
            "content": {
                "success": True,
                "status": "success",
                "should_end": True,
                "goal": {
                    "objective": "Ship the runtime goal contract",
                    "status": "completed",
                    "created_at": 1.0,
                    "updated_at": 2.0,
                    "completed_at": 3.0,
                    "paused_reason": None,
                },
                "goal_outcome": {
                    "action": "completed",
                    "objective": "Ship the runtime goal contract",
                    "status": "completed",
                    "reason": "task_done",
                },
            },
        }
        return


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


def test_execute_chat_session_emits_stream_end_with_goal_payload(monkeypatch):
    notifications = []

    class _FakeGoalManager:
        def get_goal(self, session_id):
            assert session_id == "session-web-stream"
            return SessionGoal(
                objective="Ship the runtime goal contract",
                status=GoalStatus.ACTIVE,
                created_at=1.0,
                updated_at=2.0,
            )

        def get_goal_transition(self, session_id):
            assert session_id == "session-web-stream"
            return {
                "type": "resumed",
                "objective": "Ship the runtime goal contract",
                "status": "active",
            }

    class _FakeStreamManager:
        async def notify_session_list_changed(self):
            notifications.append("notified")

    async def _fake_persist(stream_service, *, token_usage_payload=None):
        del stream_service, token_usage_payload
        return True

    async def _fake_finalize(request, original_skills):
        del request, original_skills

    monkeypatch.setattr(chat_service, "_persist_token_usage_if_available", _fake_persist)
    monkeypatch.setattr(chat_service, "_finalize_session_end", _fake_finalize)
    monkeypatch.setattr(chat_service, "get_global_session_manager", lambda: _FakeGoalManager())
    monkeypatch.setattr(
        chat_stream_manager.StreamManager,
        "get_instance",
        classmethod(lambda cls: _FakeStreamManager()),
    )

    async def _run():
        chunks = []
        async for chunk in chat_service.execute_chat_session(_FakeStreamService()):
            chunks.append(chunk)
            if '"type": "stream_end"' in chunk:
                break
        return chunks

    chunks = asyncio.run(_run())

    assert notifications == ["notified"]
    stream_end = chunks[-1]
    assert '"type": "stream_end"' in stream_end
    assert '"objective": "Ship the runtime goal contract"' in stream_end
    assert '"status": "active"' in stream_end
    assert '"goal_transition"' in stream_end
    assert '"type": "resumed"' in stream_end


def test_execute_chat_session_promotes_turn_status_goal_to_top_level_stream_event(monkeypatch):
    async def _fake_persist(stream_service, *, token_usage_payload=None):
        del stream_service, token_usage_payload
        return True

    async def _fake_finalize(request, original_skills):
        del request, original_skills

    class _FakeStreamManager:
        async def notify_session_list_changed(self):
            return None

    class _FakeGoalManager:
        def get_goal_transition(self, session_id):
            assert session_id == "session-web-stream"
            return {
                "type": "completed",
                "objective": "Ship the runtime goal contract",
                "status": "completed",
            }

    monkeypatch.setattr(chat_service, "_persist_token_usage_if_available", _fake_persist)
    monkeypatch.setattr(chat_service, "_finalize_session_end", _fake_finalize)
    monkeypatch.setattr(chat_service, "get_global_session_manager", lambda: _FakeGoalManager())
    monkeypatch.setattr(
        chat_stream_manager.StreamManager,
        "get_instance",
        classmethod(lambda cls: _FakeStreamManager()),
    )

    async def _run():
        generator = chat_service.execute_chat_session(_FakeGoalToolStreamService())
        chunk = await generator.__anext__()
        await generator.aclose()
        return chunk

    chunk = asyncio.run(_run())

    assert '"type": "tool_result"' in chunk
    assert '"goal": {' in chunk
    assert '"objective": "Ship the runtime goal contract"' in chunk
    assert '"status": "completed"' in chunk
    assert '"goal_transition"' in chunk
    assert '"goal_outcome"' in chunk
