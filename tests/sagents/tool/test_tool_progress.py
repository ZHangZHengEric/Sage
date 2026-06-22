import asyncio

import pytest

from sagents.tool.tool_progress import (
    bind_tool_progress_context,
    emit_tool_progress,
    emit_tool_progress_closed,
    register_progress_queue,
    unregister_progress_queue,
)


@pytest.mark.asyncio
async def test_tool_progress_events_include_session_id(monkeypatch):
    monkeypatch.setenv("SAGE_TOOL_PROGRESS_FLUSH_INTERVAL_MS", "0")
    queue = asyncio.Queue()
    register_progress_queue("child-session", queue)

    try:
        with bind_tool_progress_context("child-session", "call_memory"):
            await emit_tool_progress("searching", stream="stdout")
            event = queue.get_nowait()

            assert event["type"] == "tool_progress"
            assert event["session_id"] == "child-session"
            assert event["tool_call_id"] == "call_memory"
            assert event["text"] == "searching"

            await emit_tool_progress_closed()
            closed = queue.get_nowait()
            assert closed["session_id"] == "child-session"
            assert closed["tool_call_id"] == "call_memory"
            assert closed["closed"] is True
    finally:
        unregister_progress_queue("child-session")
