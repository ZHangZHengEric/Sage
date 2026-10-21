"""Idle aggregate retention; eviction never deletes durable or derived data."""
from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

from sagents.v2.contracts.run_state import RunState, TERMINAL_RUN_STATES


def cached_session_operation(function):
    @wraps(function)
    async def protected(self, *args, **kwargs):
        async with self._session_cache.operation():
            return await function(self, *args, **kwargs)
    return protected


class IdleSessionCache:
    def __init__(self, state, *, max_sessions=256, max_bytes=256 * 1024**2, idle_seconds: float = 300):
        if max_sessions < 1 or max_bytes < 1 or idle_seconds < 0:
            raise ValueError("invalid Session cache limits")
        self.state, self.max_sessions, self.max_bytes = state, max_sessions, max_bytes
        self.idle_seconds = idle_seconds
        self.entries = OrderedDict()
        self.users = {}
        self.evicted_suspended = set()
        self._current: ContextVar[tuple[asyncio.Task[Any] | None, set[str]] | None] = ContextVar("mysql_session_cache_operation", default=None)

    @asynccontextmanager
    async def operation(self):
        task = asyncio.current_task()
        previous = self._current.get()
        if previous is not None and previous[0] is task:
            yield
            return
        pinned = set()
        token = self._current.set((task, pinned))
        try:
            yield
        finally:
            self._current.reset(token)
            for sid in pinned:
                self.release(sid)
            await self.prune()

    def pin(self, sid):
        scope = self._current.get()
        if scope is not None and scope[0] is asyncio.current_task() and sid not in scope[1]:
            scope[1].add(sid)
            self.retain(sid)
        self.touch(sid)

    def retain(self, sid):
        self.users[sid] = self.users.get(sid, 0) + 1

    def release(self, sid):
        count = self.users[sid] - 1
        if count:
            self.users[sid] = count
        else:
            self.users.pop(sid)

    def touch(self, sid, *, charge=0, size=None):
        if sid not in self.state._sessions:
            return
        _, previous = self.entries.pop(sid, (0, 0))
        self.entries[sid] = (time.monotonic(), size if size is not None else previous + charge)

    def forget(self, sid):
        self.entries.pop(sid, None)

    async def prune(self):
        state = self.state
        async with state._lock:
            now = time.monotonic()
            total = sum(size for _, size in self.entries.values())
            for sid, (used, size) in tuple(self.entries.items()):
                if sid not in state._sessions:
                    self.forget(sid)
                    total -= size
                    continue
                if (len(self.entries) <= self.max_sessions and total <= self.max_bytes
                        and now - used < self.idle_seconds):
                    continue
                lock = state._session_locks.get(sid)
                if self.users.get(sid) or (lock is not None and lock.locked()):
                    continue
                run_ids = state._session_run_ids_locked(sid)
                if any(state._subscribers.get(rid) or state._runs[rid].state not in
                       (TERMINAL_RUN_STATES | {RunState.SUSPENDED}) for rid in run_ids):
                    continue
                if any((resource := state._execution_resources.get(rid)) is not None
                       and not resource.compute_released for rid in run_ids):
                    continue
                if any(state._runs[rid].state == RunState.SUSPENDED for rid in run_ids):
                    self.evicted_suspended.add(sid)
                state._evict_session_locked(sid)
                total -= size

