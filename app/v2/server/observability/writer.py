"""Bounded batches for observation producers on the event loop or worker threads."""

import asyncio
from collections import deque
from concurrent.futures import Future
from contextvars import Context
from threading import Lock


class ObservationWriter:
    def __init__(self, write, *, batch_size):
        self._loop = asyncio.get_running_loop()
        self._write = write
        self._batch_size = batch_size
        self._lock = Lock()
        self._pending = deque()
        self._tail = None
        self._task = None
        self._active = 0
        self._scheduled = False
        self._closed = False
        self.failures = 0

    def enqueue(self, value, *, limit):
        with self._lock:
            if self._closed or len(self._pending) + self._active >= limit:
                self.failures += 1
                return
            self._tail = Future()
            self._pending.append((value, self._tail))
            if not self._scheduled:
                self._scheduled = True
                # A log can arrive on a worker thread. The writer has no Run context.
                self._loop.call_soon_threadsafe(self._start, context=Context())

    def record_failure(self):
        with self._lock:
            self.failures += 1

    def _start(self):
        self._task = self._loop.create_task(self._drain())

    async def _drain(self):
        await asyncio.sleep(0.01)
        while True:
            with self._lock:
                if not self._pending:
                    self._scheduled = False
                    return
                batch = [self._pending.popleft() for _ in range(min(
                    self._batch_size, len(self._pending)
                ))]
                self._active = len(batch)
            try:
                await self._write([value for value, _ in batch])
            except asyncio.CancelledError:
                with self._lock:
                    self.failures += len(batch) + len(self._pending)
                    while self._pending:
                        _, pending = self._pending.popleft()
                        pending.set_result(None)
                    self._scheduled = False
                raise
            except Exception:
                with self._lock:
                    self.failures += len(batch)
            finally:
                with self._lock:
                    self._active = 0
                    for _, finished in batch:
                        finished.set_result(None)

    async def flush(self):
        with self._lock:
            pending = self._tail
        if pending is not None and not pending.done():
            try:
                await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(pending)), timeout=3)
            except TimeoutError:
                return False
        return True

    async def close(self):
        with self._lock:
            self._closed = True
        if not await self.flush() and self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
