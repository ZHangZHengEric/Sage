"""Bounded batches for observation producers on the event loop or worker threads."""

import asyncio
from collections import deque
from concurrent.futures import Future
from contextvars import Context
from dataclasses import dataclass
from threading import Lock


@dataclass(slots=True)
class _Pending:
    key: tuple | None
    values: list
    size: int
    finished: Future


class ObservationWriter:
    def __init__(self, write, *, batch_size, max_bytes=None, batch_bytes=None):
        self._loop = asyncio.get_running_loop()
        self._write = write
        self._batch_size = batch_size
        self._max_bytes = max_bytes
        self._batch_bytes = batch_bytes
        self._lock = Lock()
        self._pending = deque()
        self._keyed = {}
        self._tail = None
        self._task = None
        self._active = 0
        self._bytes = 0
        self._scheduled = False
        self._closed = False
        self.failures = 0

    def enqueue(self, value, *, limit, key=None, size=0):
        with self._lock:
            existing = self._keyed.get(key)
            if (
                self._closed
                or (self._max_bytes is not None and self._bytes + size > self._max_bytes)
                or (existing is None and len(self._pending) + self._active >= limit)
            ):
                self.failures += 1
                return
            self._bytes += size
            if existing is not None:
                existing.values.append(value)
                existing.size += size
                return
            self._tail = Future()
            pending = _Pending(key, [value], size, self._tail)
            self._pending.append(pending)
            if key is not None:
                self._keyed[key] = pending
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
                batch = []
                size = 0
                while self._pending and len(batch) < self._batch_size:
                    item = self._pending[0]
                    if batch and self._batch_bytes is not None and size + item.size > self._batch_bytes:
                        break
                    batch.append(self._pending.popleft())
                    size += item.size
                    if item.key is not None:
                        del self._keyed[item.key]
                self._active = len(batch)
            values = [value for item in batch for value in item.values]
            try:
                await self._write(values)
            except asyncio.CancelledError:
                with self._lock:
                    self.failures += len(values) + sum(len(item.values) for item in self._pending)
                    while self._pending:
                        pending = self._pending.popleft()
                        self._bytes -= pending.size
                        pending.finished.set_result(None)
                    self._keyed.clear()
                    self._scheduled = False
                raise
            except Exception:
                with self._lock:
                    self.failures += len(values)
            finally:
                with self._lock:
                    self._active = 0
                    self._bytes -= size
                    for item in batch:
                        item.finished.set_result(None)

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
