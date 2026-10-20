"""Reference-counted application ownership of standard process scope handles."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from .contracts import StopReason


class ScopeLease:
    def __init__(self, pool, key, handle):
        self.pool, self.key, self.handle = pool, key, handle
        self._released = False

    def __getattr__(self, name):
        return getattr(self.handle, name)

    async def close(self, reason=StopReason.SCOPE_CLOSED):
        if self._released:
            return
        await self.pool.release(self.key, reason)
        self._released = True


class ApplicationScopePool:
    """Share handles, never bypass ExtensionHost construction or teardown."""
    def __init__(self):
        self._handles = {}
        self._locks = {}

    @asynccontextmanager
    async def _key_lock(self, key):
        state = self._locks.setdefault(key, [asyncio.Lock(), 0])
        state[1] += 1
        try:
            async with state[0]:
                yield
        finally:
            state[1] -= 1
            if not state[1] and key not in self._handles:
                self._locks.pop(key, None)

    async def acquire(self, key, factory):
        async with self._key_lock(key):
            if key not in self._handles:
                handle = await factory()
                self._handles[key] = [handle, 0]
            item = self._handles[key]
            item[1] += 1
            return ScopeLease(self, key, item[0])

    async def release(self, key, reason=StopReason.SCOPE_CLOSED):
        async with self._key_lock(key):
            item = self._handles[key]
            if item[1] == 1:
                await item[0].close(reason)
                del self._handles[key]
            else:
                item[1] -= 1
