import threading
import types

from sagents.session_runtime import SessionManager
from sagents.tool.impl.execute_command_tool import ExecuteCommandTool
from sagents.tool.impl.memory_tool import MemoryTool, SessionHistoryRetriever


def test_close_session_clears_only_its_history_cache(tmp_path):
    SessionHistoryRetriever.clear_cache()
    SessionHistoryRetriever._history_cache.update(
        {
            "finished-session": object(),
            "running-session": object(),
        }
    )
    manager = SessionManager(str(tmp_path / "sessions"), enable_obs=False)
    manager.get_or_create("finished-session")

    try:
        manager.close_session("finished-session")

        assert "finished-session" not in SessionHistoryRetriever._history_cache
        assert "running-session" in SessionHistoryRetriever._history_cache
    finally:
        SessionHistoryRetriever.clear_cache()


def test_close_missing_session_still_clears_stale_history_cache(tmp_path):
    SessionHistoryRetriever.clear_cache()
    SessionHistoryRetriever._history_cache["stale-session"] = object()
    manager = SessionManager(str(tmp_path / "sessions"), enable_obs=False)

    try:
        manager.close_session("stale-session")

        assert "stale-session" not in SessionHistoryRetriever._history_cache
    finally:
        SessionHistoryRetriever.clear_cache()


def test_clear_session_cache_prevents_inflight_search_from_reinserting(
    monkeypatch,
):
    SessionHistoryRetriever.clear_cache()
    compact_started = threading.Event()
    allow_compact = threading.Event()

    def blocking_compact(_messages):
        compact_started.set()
        assert allow_compact.wait(timeout=2)
        return []

    monkeypatch.setattr(
        SessionHistoryRetriever,
        "_compact_history_messages",
        staticmethod(blocking_compact),
    )
    retriever = SessionHistoryRetriever(MemoryTool())
    session_context = types.SimpleNamespace(
        message_manager=types.SimpleNamespace(
            messages=[], compute_history_anchor_index=lambda: 1
        ),
        agent_config={},
    )
    worker = threading.Thread(
        target=retriever._get_history_messages,
        args=("racing-session", session_context),
    )

    try:
        worker.start()
        assert compact_started.wait(timeout=2)

        SessionHistoryRetriever.clear_session_cache("racing-session")
        allow_compact.set()
        worker.join(timeout=2)

        assert not worker.is_alive()
        assert "racing-session" not in SessionHistoryRetriever._history_cache
        assert "racing-session" not in SessionHistoryRetriever._history_states
    finally:
        allow_compact.set()
        worker.join(timeout=2)
        SessionHistoryRetriever.clear_cache()


def test_closed_context_cannot_cache_when_worker_starts_late():
    SessionHistoryRetriever.clear_cache()
    retriever = SessionHistoryRetriever(MemoryTool())
    session_context = types.SimpleNamespace(
        message_manager=types.SimpleNamespace(
            messages=[], compute_history_anchor_index=lambda: 1
        ),
        agent_config={},
    )

    try:
        SessionHistoryRetriever.clear_session_cache(
            "late-session", session_context
        )
        retriever._get_history_messages("late-session", session_context)

        assert "late-session" not in SessionHistoryRetriever._history_cache
        assert "late-session" not in SessionHistoryRetriever._history_states
    finally:
        SessionHistoryRetriever.clear_cache()


def test_direct_close_session_force_kills_background_shell(tmp_path, monkeypatch):
    class FakeSandbox:
        def __init__(self):
            self.killed = []
            self.cleaned = []

        async def kill_background(self, task_id, force=False):
            self.killed.append((task_id, force))
            return True

        async def cleanup_background(self, task_id):
            self.cleaned.append(task_id)

    monkeypatch.setattr(ExecuteCommandTool, "_BG_TASKS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_COMPLETION_EVENTS", {})
    monkeypatch.setattr(ExecuteCommandTool, "_WATCHER_TASKS", {})
    sandbox = FakeSandbox()
    ExecuteCommandTool._BG_TASKS["closing-task"] = {
        "task_id": "closing-task",
        "session_id": "closing-session",
        "mode": "native",
        "sandbox": sandbox,
    }
    manager = SessionManager(str(tmp_path / "sessions"), enable_obs=False)
    session = manager.get_or_create("closing-session")
    session_context = types.SimpleNamespace(sandbox=sandbox)
    session.session_context = session_context

    manager.close_session("closing-session")

    assert sandbox.killed == [("closing-task", True)]
    assert sandbox.cleaned == ["closing-task"]
    assert ExecuteCommandTool._BG_TASKS == {}
    assert session.session_context is None
    assert session_context._session_history_cache_closed is True
