"""A dedicated, bounded executor for CPU-intensive password operations."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

T = TypeVar('T')


class PasswordExecutor:
    def __init__(self, *, workers: int = 2, queued: int = 16) -> None:
        if workers < 1 or queued < 0:
            raise ValueError('password executor capacity is invalid')
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='password')
        self._capacity = workers + queued
        self._pending: set[asyncio.Future] = set()
        self._closed = False
        self._close_task: asyncio.Task[None] | None = None

    async def run(self, operation: Callable[..., T], *args) -> T:
        # No await between admission and submission: the event loop serializes
        # admissions. Request cancellation cannot release a running worker slot.
        if self._closed or len(self._pending) >= self._capacity:
            raise SageV2Error(RuntimeErrorInfo(
                code='server.identity.busy', category=ErrorCategory.RATE_LIMITED,
                message='Password service is busy; try again shortly', retryable=True,
            ))
        future = asyncio.get_running_loop().run_in_executor(self._pool, operation, *args)
        self._pending.add(future)
        def completed(done):
            self._pending.discard(done)
            # Observe errors even if the HTTP caller has already disconnected.
            if not done.cancelled():
                done.exception()
        future.add_done_callback(completed)
        return await asyncio.shield(future)

    @property
    def closed(self) -> bool:
        return self._closed

    async def close(self) -> None:
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._drain_and_shutdown(), name="password-executor-close")
        # The cleanup belongs to the executor, independent of the HTTP or Host
        # task waiting for it. Retrying close waits on the same cleanup.
        await asyncio.shield(self._close_task)

    async def _drain_and_shutdown(self) -> None:
        try:
            if self._pending:
                await asyncio.gather(*self._pending, return_exceptions=True)
        finally:
            self._pool.shutdown(wait=False)
