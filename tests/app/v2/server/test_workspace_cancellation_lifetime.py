"""Filesystem work keeps its admission lock under repeated cancellation."""
import asyncio
from threading import Event

import anyio
import pytest

from app.v2.server.conversations.cleanup import finish_file_operation
from app.v2.server.conversations.runs import RunService


@pytest.mark.parametrize('cancellation', ['asyncio-repeated', 'anyio-scope'])
async def test_cancelled_file_worker_keeps_workspace_locked_until_it_finishes(cancellation):
    entered, release, finished = Event(), Event(), Event()
    cancelled, attempting, admitted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    runs = RunService(application=None, session_access=None, execution=None)

    def worker():
        entered.set()
        try:
            assert release.wait(3)
        finally:
            finished.set()

    async def deletion():
        async with runs.workspace_guard('tenant', 'agent'):
            await finish_file_operation(worker)

    async def cancelled_scope():
        async with anyio.create_task_group() as group:
            group.start_soon(deletion)
            await getattr(anyio.to_thread, 'run_sync')(entered.wait)
            cancelled.set()
            group.cancel_scope.cancel()

    async def admission():
        attempting.set()
        async with runs.workspace_guard('tenant', 'agent'):
            admitted.set()
            assert finished.is_set(), 'admitted while filesystem worker was still running'

    task = asyncio.create_task(cancelled_scope() if cancellation == 'anyio-scope' else deletion())
    competing = None
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        if cancellation == 'asyncio-repeated':
            task.cancel()
            asyncio.get_running_loop().call_soon(task.cancel)
        else:
            await asyncio.wait_for(cancelled.wait(), 2)
        competing = asyncio.create_task(admission())
        await asyncio.wait_for(attempting.wait(), 2)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(admitted.wait(), .03)
        release.set()
        if cancellation == 'asyncio-repeated':
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        await competing
        assert finished.is_set() and admitted.is_set()
    finally:
        release.set()
        await asyncio.gather(task, *([competing] if competing else []), return_exceptions=True)
        assert await asyncio.to_thread(finished.wait, 2)
