"""Per-event-loop admission for shared auxiliary work, without global loop ownership."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import threading
from weakref import WeakKeyDictionary, ref

_SLOTS = WeakKeyDictionary()
_GUARD = threading.Lock()
_LIMITS = {
    "context-cpu": 2,
    "skill-io": 8,
    "context-summary": 4,
    "memory-io": 8,
    "model-init": 4,
}


def _semaphore(kind):
    loop = asyncio.get_running_loop()
    with _GUARD:
        groups = _SLOTS.setdefault(loop, {})
        entry = groups.get(kind)
        slots = entry() if entry is not None else None
        if slots is None:
            slots = asyncio.Semaphore(_LIMITS[kind])
            groups[kind] = ref(slots)
        return slots


@asynccontextmanager
async def auxiliary_capacity(kind):
    async with _semaphore(kind):
        yield


async def bounded_to_thread(kind, operation, *, prepare=None, lock=None):
    """Cancelled observers do not release a still-running worker's capacity."""
    slots = _semaphore(kind)
    if lock is not None:
        await lock.acquire()
    try:
        await slots.acquire()
    except BaseException:
        if lock is not None:
            lock.release()
        raise
    try:
        callback = prepare() if prepare is not None else operation
        task = asyncio.create_task(asyncio.to_thread(callback))
    except BaseException:
        slots.release()
        if lock is not None:
            lock.release()
        raise

    def finished(task):
        slots.release()
        if lock is not None:
            lock.release()
        if not task.cancelled():
            task.exception()

    task.add_done_callback(finished)
    return await asyncio.shield(task)
