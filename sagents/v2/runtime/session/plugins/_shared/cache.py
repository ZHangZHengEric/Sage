"""Idle aggregate retention; eviction never deletes durable or derived data."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from contextvars import Context, ContextVar
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
    def __init__(
        self,
        state,
        *,
        max_sessions=256,
        max_bytes=256 * 1024**2,
        idle_seconds: float = 300,
        eligible=None,
        allow_suspended=True,
    ):
        if max_sessions < 1 or max_bytes < 1 or idle_seconds < 0:
            raise ValueError("invalid Session cache limits")
        self.state, self.max_sessions, self.max_bytes = state, max_sessions, max_bytes
        self.idle_seconds = idle_seconds
        self.eligible = eligible
        self.allow_suspended = allow_suspended
        self.entries = OrderedDict()
        self._total_bytes = 0
        self.users = {}
        self.evicted_suspended = set()
        self._timer: asyncio.TimerHandle | None = None
        self._task: asyncio.Task[None] | None = None
        self._closed = False
        self._current: ContextVar[tuple[asyncio.Task[Any] | None, set[str]] | None] = (
            ContextVar("durable_session_cache_operation", default=None)
        )

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
        if (
            scope is not None
            and scope[0] is asyncio.current_task()
            and sid not in scope[1]
        ):
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
        current = size if size is not None else previous + charge
        self.entries[sid] = (time.monotonic(), current)
        self._total_bytes += current - previous
        self._schedule_prune()

    def _schedule_prune(self):
        if self._closed or self._timer is not None or self._task is not None or not self.entries:
            return
        interval = min(30, max(0.05, self.idle_seconds / 2))
        # A timer may outlive the writer that scheduled it. Its context must
        # not retain that operation's undo state or request-scoped resources.
        self._timer = asyncio.get_running_loop().call_later(
            interval, self._start_prune, context=Context()
        )

    def _start_prune(self):
        self._timer = None
        self._task = asyncio.create_task(self._prune_and_reschedule())

    async def _prune_and_reschedule(self):
        try:
            await self.prune()
        finally:
            self._task = None
            self._schedule_prune()

    async def close(self):
        self._closed = True
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._task is not None:
            await self._task

    def forget(self, sid):
        _, size = self.entries.pop(sid, (0, 0))
        self._total_bytes -= size
        if not self.entries and self._timer is not None:
            self._timer.cancel()
            self._timer = None

    async def prune(self):
        state = self.state
        async with state._lock:
            now = time.monotonic()
            if not self.entries:
                return
            # touch() maintains oldest-first order. A fresh oldest entry and
            # sufficient capacity rule out eviction without traversing all Runs.
            oldest, _ = next(iter(self.entries.values()))
            if (len(self.entries) <= self.max_sessions and self._total_bytes <= self.max_bytes
                    and now - oldest < self.idle_seconds):
                return
            entries = tuple(self.entries.items())
            if self.eligible is not None and self.allow_suspended:
                # The filesystem may allow explicit manual pauses, but only
                # after the cheaper-to-reload terminal Sessions.
                entries = sorted(entries, key=lambda entry: any(
                    state._runs[run_id].state == RunState.SUSPENDED
                    for run_id in state._session_run_ids_locked(entry[0])
                ))
            allowed = TERMINAL_RUN_STATES | {RunState.SUSPENDED} if self.allow_suspended else TERMINAL_RUN_STATES
            for sid, (used, _) in entries:
                if sid not in state._sessions:
                    self.forget(sid)
                    continue
                if (
                    len(self.entries) <= self.max_sessions
                    and self._total_bytes <= self.max_bytes
                    and now - used < self.idle_seconds
                ):
                    continue
                lock = state._session_locks.get(sid)
                if self.users.get(sid) or (lock is not None and lock.locked()):
                    continue
                if sid in getattr(state, "_recovery_required", ()):
                    continue
                if self.eligible is not None and not self.eligible(sid):
                    continue
                run_ids = state._session_run_ids_locked(sid)
                if any(
                    state._subscribers.get(rid)
                    or state._runs[rid].state
                    not in allowed
                    for rid in run_ids
                ):
                    continue
                if any(
                    (resource := state._execution_resources.get(rid)) is not None
                    and not resource.compute_released
                    for rid in run_ids
                ):
                    continue
                if any(state._runs[rid].state == RunState.SUSPENDED for rid in run_ids):
                    self.evicted_suspended.add(sid)
                state._evict_session_locked(sid)
