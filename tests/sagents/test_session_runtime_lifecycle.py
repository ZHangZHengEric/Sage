import asyncio
import json
import sqlite3

import pytest

import sagents.session_runtime as session_runtime
from sagents.session_runtime import SessionManager


def _write_historical_session(tmp_path, session_id: str):
    workspace = tmp_path / session_id
    workspace.mkdir()
    (workspace / "messages.json").write_text(
        json.dumps(
            [
                {
                    "role": "user",
                    "content": "persisted",
                    "session_id": session_id,
                }
            ]
        ),
        encoding="utf-8",
    )
    (workspace / "session_context.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "user_id": "user-1",
                "status": "completed",
                "agent_config": {"agent_id": "agent-1"},
                "session_root_space": str(tmp_path),
                "session_workspace": str(workspace),
                "tasks_status": {"tasks": [{"id": "done"}]},
            }
        ),
        encoding="utf-8",
    )
    return workspace


def test_historical_reads_never_repopulate_live_sessions(tmp_path):
    manager = SessionManager(str(tmp_path), enable_obs=False)
    session_id = "historical-session"
    workspace = _write_historical_session(tmp_path, session_id)
    manager.cache_session_workspace(session_id, str(workspace))

    restored = manager.get(session_id)
    assert restored is not None
    assert restored.get_status().value == "completed"
    assert manager._sessions == {}

    assert [message.content for message in manager.get_session_messages(session_id)] == [
        "persisted"
    ]
    assert manager.get_session_status(session_id) == {"status": "completed"}
    assert manager.get_tasks_status(session_id) == {"tasks": [{"id": "done"}]}
    assert manager.save_session(session_id) is False
    assert manager._sessions == {}


@pytest.mark.asyncio
async def test_aclose_session_flushes_context_before_release(tmp_path):
    manager = SessionManager(str(tmp_path), enable_obs=False)
    session = manager.get_or_create("closing-session")
    calls = []

    class FakeContext:
        sandbox = None
        _owner_loop = None

        async def flush_pending_log_writes(self):
            calls.append("flush")

    session.set_context(FakeContext())
    await manager.aclose_session("closing-session")

    assert calls == ["flush"]
    assert manager._sessions == {}


@pytest.mark.asyncio
async def test_sync_close_from_worker_runs_cleanup_on_owner_loop(tmp_path):
    manager = SessionManager(str(tmp_path), enable_obs=False)
    session = manager.get_or_create("thread-close-session")
    owner_loop = asyncio.get_running_loop()
    cleaned_on = []

    class FakeContext:
        sandbox = None
        _owner_loop = owner_loop

        async def flush_pending_log_writes(self):
            cleaned_on.append(asyncio.get_running_loop())

    session.set_context(FakeContext())
    await asyncio.to_thread(manager.close_session, "thread-close-session")

    assert cleaned_on == [owner_loop]
    assert manager._sessions == {}


@pytest.mark.asyncio
async def test_sync_close_reserves_session_id_until_cleanup_finishes(tmp_path):
    manager = SessionManager(str(tmp_path), enable_obs=False)
    session = manager.get_or_create("reused-session")
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()

    class FakeContext:
        sandbox = None
        _owner_loop = asyncio.get_running_loop()

        async def flush_pending_log_writes(self):
            cleanup_started.set()
            await allow_cleanup.wait()

    session.set_context(FakeContext())
    manager.close_session("reused-session")
    await cleanup_started.wait()

    with pytest.raises(RuntimeError, match="still closing"):
        manager.get_or_create("reused-session")

    allow_cleanup.set()
    await manager.aclose_session("reused-session")
    replacement = manager.get_or_create("reused-session")
    assert manager.get_live_session("reused-session") is replacement

    await manager.shutdown()


@pytest.mark.asyncio
async def test_aclose_releases_session_when_log_flush_ignores_cancellation(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(session_runtime, "_SESSION_LOG_FLUSH_TIMEOUT_SECONDS", 0.02)
    manager = SessionManager(str(tmp_path), enable_obs=False)
    session = manager.get_or_create("stalled-close")
    flush_started = asyncio.Event()
    allow_flush_exit = asyncio.Event()

    class FakeContext:
        sandbox = None
        _owner_loop = asyncio.get_running_loop()

        async def flush_pending_log_writes(self):
            flush_started.set()
            while not allow_flush_exit.is_set():
                try:
                    await allow_flush_exit.wait()
                except asyncio.CancelledError:
                    # Model a broken adapter that swallows cancellation.
                    continue

    session.set_context(FakeContext())
    await manager.aclose_session("stalled-close")

    assert flush_started.is_set()
    assert manager._sessions == {}
    assert manager._session_close_futures == {}
    replacement = manager.get_or_create("stalled-close")
    assert manager.get_live_session("stalled-close") is replacement

    allow_flush_exit.set()
    await asyncio.sleep(0)
    await manager.shutdown()


@pytest.mark.asyncio
async def test_sync_cross_thread_close_has_bounded_wait(tmp_path, monkeypatch):
    monkeypatch.setattr(session_runtime, "_SESSION_LOG_FLUSH_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(
        session_runtime, "_SYNC_SESSION_CLOSE_WAIT_TIMEOUT_SECONDS", 0.02
    )
    manager = SessionManager(str(tmp_path), enable_obs=False)
    session = manager.get_or_create("sync-stalled-close")
    owner_loop = asyncio.get_running_loop()
    flush_started = asyncio.Event()
    allow_flush_exit = asyncio.Event()

    class FakeContext:
        sandbox = None
        _owner_loop = owner_loop

        async def flush_pending_log_writes(self):
            flush_started.set()
            await allow_flush_exit.wait()

    session.set_context(FakeContext())
    await asyncio.wait_for(
        asyncio.to_thread(manager.close_session, "sync-stalled-close"),
        timeout=0.2,
    )
    assert flush_started.is_set()
    assert "sync-stalled-close" in manager._session_close_futures

    allow_flush_exit.set()
    await manager.aclose_session("sync-stalled-close")
    assert manager._session_close_futures == {}
    await manager.shutdown()


@pytest.mark.asyncio
async def test_shutdown_closes_session_registry_connection(tmp_path):
    manager = SessionManager(str(tmp_path), enable_obs=False)
    assert manager._registry._conn.execute("SELECT 1").fetchone() == (1,)

    await manager.shutdown()

    with pytest.raises(sqlite3.ProgrammingError):
        manager._registry._conn.execute("SELECT 1")
