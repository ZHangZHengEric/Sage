"""Bound physical connections and acquisition waits, retaining write capacity."""

import asyncio
from contextlib import asynccontextmanager
import math
import sys

from anyio import CancelScope

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


async def finish_connection_cleanup(awaitable):
    """A cancelled caller retains its capacity until rollback/release settles."""
    task = asyncio.create_task(awaitable)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError as cancellation:
        with CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if not task.cancelled() and (error := task.exception()) is not None:
            cancellation.add_note(f"MySQL connection cleanup also failed: {error!r}")
        raise cancellation


class MysqlConnectionBudget:
    def __init__(self, *, max_connections=16, max_pending_connections=64,
                 connection_acquire_timeout_seconds=10):
        if type(max_connections) is not int or max_connections < 2:
            raise ValueError("max_connections must be an integer of at least 2")
        if type(max_pending_connections) is not int or max_pending_connections < 1:
            raise ValueError("max_pending_connections must be a positive integer")
        timeout = connection_acquire_timeout_seconds
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("connection_acquire_timeout_seconds must be positive and finite")
        self.max_connections = max_connections
        self.max_pending_connections = max_pending_connections
        self.connection_acquire_timeout_seconds = timeout
        self._slots = asyncio.Semaphore(max_connections)
        self._read_slots = asyncio.Semaphore(max_connections - 1)
        self._waiting = 0

    @staticmethod
    def _busy():
        return SageV2Error(RuntimeErrorInfo(
            code="session_store.mysql_busy", category=ErrorCategory.RATE_LIMITED,
            message="MySQL SessionStore connection capacity is busy; retry later",
            retryable=True, safe_to_resume=True,
        ))

    @asynccontextmanager
    async def connection(self, ready_pool, *, reader):
        queued = self._slots.locked() or (reader and self._read_slots.locked())
        if queued and self._waiting >= self.max_pending_connections:
            raise self._busy()
        if queued:
            self._waiting += 1
        read_acquired = acquired = False
        try:
            try:
                async with asyncio.timeout(self.connection_acquire_timeout_seconds):
                    if reader:
                        await self._read_slots.acquire()
                        read_acquired = True
                    await self._slots.acquire()
                    acquired = True
                    pool = await ready_pool()
                    lease = pool.acquire()
                    connection = await lease.__aenter__()
            except TimeoutError as exc:
                raise self._busy() from exc
            finally:
                if queued:
                    self._waiting -= 1
            try:
                yield connection
            finally:
                exception = sys.exc_info()

                async def release():
                    try:
                        if reader:
                            await connection.rollback()
                    except BaseException:
                        # Never recycle uncertain transaction state.
                        connection.close()
                        raise
                    finally:
                        await lease.__aexit__(*exception)
                await finish_connection_cleanup(release())
        finally:
            if acquired:
                self._slots.release()
            if read_acquired:
                self._read_slots.release()
