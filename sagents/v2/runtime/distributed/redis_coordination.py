"""Bounded Redis guards checked in the transaction that publishes a mutation."""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass
import time
import uuid

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


def coordination_error(message, *, code="scheduler.fence_rejected", retryable=False):
    return SageV2Error(RuntimeErrorInfo(code=code,
        category=ErrorCategory.CONFLICT, message=message, safe_to_resume=True, retryable=retryable))


@dataclass(frozen=True)
class RedisMutationFence:
    redis_url: str
    key: str
    token: str


active_worker_fence: ContextVar[RedisMutationFence | None] = ContextVar(
    "distributed_redis_worker_fence", default=None)


async def watch_fence(pipe, fence):
    await pipe.watch(fence.key)
    if await pipe.get(fence.key) != fence.token:
        raise coordination_error("Distributed mutation ownership expired or was replaced")


class RedisGuard:
    """One short operation, with renewal and compare-and-delete cleanup.

    A guard does not authorize a write by itself: callers must WATCH its key
    and compare its token inside every authoritative Redis transaction.
    """

    def __init__(self, redis, key, *, ttl_seconds=30, wait_seconds=10):
        self.redis, self.key = redis, key
        self.ttl_seconds, self.wait_seconds = ttl_seconds, wait_seconds
        self.token = uuid.uuid4().hex
        self._renewal = None

    async def __aenter__(self):
        deadline = time.monotonic() + self.wait_seconds
        while not await self.redis.set(self.key, self.token, nx=True,
                                       px=max(1, int(self.ttl_seconds * 1000))):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise coordination_error("Timed out waiting for a distributed mutation",
                    code="runtime.coordination_busy", retryable=True)
            await asyncio.sleep(min(0.05, remaining))
        self._renewal = asyncio.create_task(self._renew())
        return self

    async def _renew(self):
        from redis.exceptions import WatchError
        try:
            while True:
                await asyncio.sleep(self.ttl_seconds / 3)
                try:
                    async with self.redis.pipeline() as pipe:
                        await watch_fence(pipe, self)
                        pipe.multi()
                        pipe.pexpire(self.key, max(1, int(self.ttl_seconds * 1000)))
                        await pipe.execute()
                except WatchError:
                    continue
        except Exception:
            # Never recreate an expired guard. Every actual write checks it.
            return

    async def __aexit__(self, *exc):
        from redis.exceptions import RedisError
        if self._renewal is not None:
            self._renewal.cancel()
            await asyncio.gather(self._renewal, return_exceptions=True)
        try:
            async with self.redis.pipeline() as pipe:
                await pipe.watch(self.key)
                if await pipe.get(self.key) == self.token:
                    pipe.multi()
                    pipe.delete(self.key)
                    await pipe.execute()
        except (RedisError, OSError, TimeoutError):
            pass  # TTL remains the cleanup fallback; never delete a successor.
