"""Bounded per-user model clients with Run-scoped leases and idle LRU eviction."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

try:
    from builtins import ExceptionGroup
except ImportError:  # Python 3.10
    from exceptiongroup import ExceptionGroup

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


async def _settle(operation):
    task = asyncio.create_task(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


def _consume(task):
    if not task.cancelled():
        task.exception()


@dataclass(eq=False)
class _Entry:
    building: asyncio.Task
    users: int = 0


class ModelLease:
    def __init__(self, pool, entry, provider):
        self._pool = pool
        self._entry = entry
        self.provider = provider
        self._closed = False

    async def close(self):
        if not self._closed:
            self._closed = True
            await _settle(self._pool._release(self._entry))


class ModelClientPool:
    def __init__(
        self,
        factory: Callable[..., Awaitable],
        closer: Callable[..., Awaitable],
        *,
        max_clients=64,
    ):
        if max_clients < 1:
            raise ValueError("max_model_clients must be positive")
        self._factory = factory
        self._closer = closer
        self._maximum = max_clients
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._retiring: set[asyncio.Task] = set()
        self._condition = asyncio.Condition()
        self._closed = False
        self._close_task = None
        self._close_errors: list[Exception] = []
        self._created = 0

    @staticmethod
    def _key(user_id, record):
        # Include owner and credentials; never retain raw keys as cache keys.
        value = (
            user_id,
            record.id,
            record.protocol,
            record.base_url,
            record.model,
            record.api_key.get_secret_value(),
        )
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()

    async def acquire(self, user_id, record) -> ModelLease:
        key = self._key(user_id, record)
        while True:
            retiring = None
            async with self._condition:
                if self._closed:
                    raise RuntimeError("model client pool is closed")
                if self._close_errors:
                    raise RuntimeError(
                        "model client pool cleanup failed"
                    ) from self._close_errors[0]
                entry = self._entries.get(key)
                if (
                    entry is not None
                    and entry.building.done()
                    and (
                        entry.building.cancelled()
                        or entry.building.exception() is not None
                    )
                    and not entry.users
                ):
                    self._entries.pop(key)
                    entry = None
                if entry is None:
                    if len(self._entries) + len(self._retiring) >= self._maximum:
                        idle = next(
                            ((k, e) for k, e in self._entries.items() if e.users == 0),
                            None,
                        )
                        if idle is None:
                            raise SageV2Error(
                                RuntimeErrorInfo(
                                    code="server.model_pool_full",
                                    category=ErrorCategory.RATE_LIMITED,
                                    message="all model client slots are in use",
                                    retryable=True,
                                    safe_to_resume=True,
                                )
                            )
                        self._entries.pop(idle[0])
                        retiring = self._retire(idle[1])
                    else:
                        building = asyncio.create_task(
                            self._factory(record.model_copy(deep=True))
                        )
                        building.add_done_callback(_consume)
                        entry = _Entry(building)
                        self._entries[key] = entry
                        self._created += 1
                if retiring is None:
                    entry.users += 1
                    self._entries.move_to_end(key)
            if retiring is not None:
                await asyncio.shield(retiring)
                continue
            try:
                provider = await asyncio.shield(entry.building)
                return ModelLease(self, entry, provider)
            except BaseException:
                await _settle(self._release(entry))
                raise

    async def _release(self, entry):
        async with self._condition:
            entry.users -= 1
            self._condition.notify_all()

    def _retire(self, entry):
        task = asyncio.create_task(self._dispose(entry))
        self._retiring.add(task)
        task.add_done_callback(_consume)
        return task

    async def _dispose(self, entry):
        try:
            try:
                provider = await asyncio.shield(entry.building)
            except Exception:
                return  # Initialization failure produced no owned client.
            try:
                await self._closer(provider)
            except Exception as exc:
                self._close_errors.append(exc)
                raise
        finally:
            async with self._condition:
                self._retiring.discard(asyncio.current_task())
                self._condition.notify_all()

    async def snapshot(self):
        async with self._condition:
            return {
                "clients": len(self._entries),
                "closing_clients": len(self._retiring),
                "active_leases": sum(entry.users for entry in self._entries.values()),
                "max_clients": self._maximum,
                "constructions": self._created,
            }

    async def close(self):
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._shutdown())
            self._close_task.add_done_callback(_consume)
        # Shutdown continues if its observer cancels; a later close rejoins it.
        await asyncio.shield(self._close_task)

    async def _shutdown(self):
        async with self._condition:
            await self._condition.wait_for(
                lambda: not any(e.users for e in self._entries.values())
            )
            for entry in self._entries.values():
                self._retire(entry)
            self._entries.clear()
            retiring = tuple(self._retiring)
        await asyncio.gather(*retiring, return_exceptions=True)
        if self._close_errors:
            raise ExceptionGroup("model client cleanup failed", self._close_errors)
