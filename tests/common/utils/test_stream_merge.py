import asyncio

import pytest

import common.utils.stream_merge as stream_merge
from common.utils.stream_merge import interleave_message_and_progress


@pytest.mark.asyncio
async def test_closing_merge_waits_for_worker_cleanup():
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()

    async def messages():
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await allow_cleanup.wait()

    merged = interleave_message_and_progress(messages(), asyncio.Queue())
    assert await anext(merged) == ("message", "first")

    close_task = asyncio.create_task(merged.aclose())
    await cleanup_started.wait()
    assert not close_task.done()

    allow_cleanup.set()
    await close_task


@pytest.mark.asyncio
async def test_closing_merge_is_bounded_when_worker_ignores_cancellation(monkeypatch):
    monkeypatch.setattr(stream_merge, "_WORKER_SHUTDOWN_TIMEOUT_SECONDS", 0.02)
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()

    async def messages():
        try:
            yield "first"
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            while not allow_cleanup.is_set():
                try:
                    await allow_cleanup.wait()
                except asyncio.CancelledError:
                    continue

    merged = interleave_message_and_progress(messages(), asyncio.Queue())
    assert await anext(merged) == ("message", "first")

    close_task = asyncio.create_task(merged.aclose())
    await cleanup_started.wait()
    await asyncio.wait_for(close_task, timeout=0.2)

    allow_cleanup.set()
    await asyncio.sleep(0)
