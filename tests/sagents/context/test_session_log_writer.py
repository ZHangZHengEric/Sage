import asyncio
import threading

import pytest

from sagents.context.session_context import SessionContext


def _context(tmp_path):
    context = SessionContext(
        session_id="log-session",
        user_id="user-1",
        agent_id="agent-1",
        session_root_space=str(tmp_path),
    )
    context.session_workspace = str(tmp_path)
    return context


@pytest.mark.asyncio
async def test_diagnostic_logs_share_one_writer_and_flush_all(tmp_path, monkeypatch):
    context = _context(tmp_path)
    llm_writes = []
    mcp_writes = []
    monkeypatch.setattr(
        context,
        "_save_llm_request_sync",
        lambda item: llm_writes.append(item),
    )
    monkeypatch.setattr(
        context,
        "_save_mcp_calls_sync",
        lambda request_id: mcp_writes.append(request_id),
    )

    context._current_request = {
        "request_id": "request-1",
        "started_at": 1.0,
        "per_call": [],
        "total_usage": {},
    }
    for index in range(20):
        context.add_llm_request({"index": index}, {"ok": True})
        context.add_mcp_call({"tool": f"tool-{index}"})

    writer = context._log_writer_task
    assert writer is not None
    await context.flush_pending_log_writes()

    assert len(llm_writes) == 20
    assert mcp_writes == ["request-1"]
    assert context._log_writer_task is None
    assert context._log_writer_closed is True


@pytest.mark.asyncio
async def test_flush_waits_for_inflight_writer(tmp_path, monkeypatch):
    context = _context(tmp_path)
    started = threading.Event()
    release = threading.Event()
    writes = []

    def blocking_save(item):
        started.set()
        release.wait()
        writes.append(item)

    monkeypatch.setattr(context, "_save_llm_request_sync", blocking_save)
    context.add_llm_request({"index": 1}, {"ok": True})

    assert await asyncio.to_thread(started.wait, 1)
    flush_task = asyncio.create_task(context.flush_pending_log_writes())
    await asyncio.sleep(0)
    assert not flush_task.done()
    release.set()
    await flush_task
    assert len(writes) == 1


@pytest.mark.asyncio
async def test_concurrent_flushes_share_the_same_writer(tmp_path, monkeypatch):
    context = _context(tmp_path)
    started = threading.Event()
    release = threading.Event()
    writes = []

    def blocking_save(item):
        started.set()
        release.wait()
        writes.append(item)

    monkeypatch.setattr(context, "_save_llm_request_sync", blocking_save)
    context.add_llm_request({"index": 1}, {"ok": True})

    assert await asyncio.to_thread(started.wait, 1)
    first = asyncio.create_task(context.flush_pending_log_writes())
    second = asyncio.create_task(context.flush_pending_log_writes())
    release.set()

    assert await asyncio.gather(first, second) == [True, True]
    assert len(writes) == 1


@pytest.mark.asyncio
async def test_flush_timeout_releases_writer_and_payloads(tmp_path, monkeypatch):
    context = _context(tmp_path)
    context.LOG_FLUSH_TIMEOUT_SECONDS = 0.02
    context.LOG_WRITER_CANCEL_TIMEOUT_SECONDS = 0.02
    started = threading.Event()
    release = threading.Event()

    def blocking_save(_item):
        started.set()
        release.wait()

    monkeypatch.setattr(context, "_save_llm_request_sync", blocking_save)
    context.add_llm_request({"index": 1}, {"ok": True})

    try:
        assert await asyncio.to_thread(started.wait, 1)
        assert await context.flush_pending_log_writes() is False
        assert context._log_writer_task is None
        assert context.llm_requests_logs == []
        assert context.mcp_calls_logs == []
        assert context._dirty_mcp_request_ids == set()
    finally:
        release.set()


@pytest.mark.asyncio
async def test_writer_failure_does_not_block_later_items(tmp_path, monkeypatch):
    context = _context(tmp_path)
    attempted = []

    def sometimes_failing_save(item):
        attempted.append(item["request"]["index"])
        if len(attempted) == 1:
            raise OSError("first diagnostic write failed")

    monkeypatch.setattr(context, "_save_llm_request_sync", sometimes_failing_save)
    context.add_llm_request({"index": 1}, {"ok": True})
    context.add_llm_request({"index": 2}, {"ok": True})

    assert await context.flush_pending_log_writes() is True
    assert attempted == [1, 2]


@pytest.mark.asyncio
async def test_mcp_call_added_during_write_is_saved_by_next_pass(
    tmp_path, monkeypatch
):
    context = _context(tmp_path)
    context._current_request = {
        "request_id": "request-race",
        "started_at": 1.0,
        "per_call": [],
        "total_usage": {},
    }
    first_write_started = threading.Event()
    allow_first_write = threading.Event()
    writes = []

    def blocking_first_save(request_id):
        writes.append(request_id)
        if len(writes) == 1:
            first_write_started.set()
            allow_first_write.wait()

    monkeypatch.setattr(context, "_save_mcp_calls_sync", blocking_first_save)
    context.add_mcp_call({"tool": "first"})

    try:
        assert await asyncio.to_thread(first_write_started.wait, 1)
        context.add_mcp_call({"tool": "second"})
        allow_first_write.set()
        assert await context.flush_pending_log_writes() is True
    finally:
        allow_first_write.set()

    assert writes == ["request-race", "request-race"]
