"""Host-owned concurrency bound shared by otherwise independent Applications."""

from __future__ import annotations

import asyncio
import math
from collections import deque
from contextlib import asynccontextmanager

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error


class ModelConcurrencyBudget:
    """Bound live model calls, without holding a slot while agents await tools."""

    plugin_id = "sage.model.concurrency-budget"
    name = "execution.model-budget"
    description = "Standard execution.model-budget implementation with declared dependencies and lifecycle."

    def __init__(
        self,
        limit: int = 8,
        *,
        max_waiting: int = 128,
        wait_timeout_seconds: float = 60,
    ):
        if type(limit) is not int or limit < 1:
            raise ValueError("model concurrency limit must be a positive integer")
        if type(max_waiting) is not int or max_waiting < 0:
            raise ValueError("model queue limit must be a nonnegative integer")
        if not math.isfinite(wait_timeout_seconds) or wait_timeout_seconds <= 0:
            raise ValueError("model queue timeout must be finite and positive")
        self.limit = limit
        self.max_waiting = max_waiting
        self.wait_timeout_seconds = wait_timeout_seconds
        self.active = 0
        self.waiting = 0
        self.rejected = 0
        self.timed_out = 0
        self._waiters: deque[asyncio.Event] = deque()

    def set_limit(self, limit: int) -> None:
        if type(limit) is not int or limit < 1:
            raise ValueError("model concurrency limit must be a positive integer")
        self.limit = limit
        self._wake_waiter()

    def _wake_waiter(self) -> None:
        if self._waiters and self.active < self.limit:
            self._waiters[0].set()

    def _error(self, code, message):
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.RATE_LIMITED,
                message=message,
                retryable=True,
                safe_to_resume=True,
                metadata={"model_budget": self.snapshot()},
            )
        )

    @asynccontextmanager
    async def lease(self):
        # Queue head rechecks the live limit before using capacity. A limit
        # reduction can race an already signalled waiter.
        if self.active >= self.limit or self._waiters:
            if self.waiting >= self.max_waiting:
                self.rejected += 1
                raise self._error(
                    "model.queue_full", "Model request queue is full; retry later."
                )
            self.waiting += 1
            ready = asyncio.Event()
            self._waiters.append(ready)
            try:
                try:
                    async with asyncio.timeout(self.wait_timeout_seconds):
                        while self._waiters[0] is not ready or self.active >= self.limit:
                            await ready.wait()
                            ready.clear()
                except TimeoutError as exc:
                    self.timed_out += 1
                    raise self._error(
                        "model.queue_timeout",
                        "Model request timed out waiting for capacity; retry later.",
                    ) from exc
                self.active += 1
            finally:
                self._waiters.remove(ready)
                self.waiting -= 1
                self._wake_waiter()
        else:
            self.active += 1
        try:
            yield
        finally:
            self.active -= 1
            self._wake_waiter()

    def snapshot(self):
        return {
            "limit": self.limit,
            "active": self.active,
            "waiting": self.waiting,
            "max_waiting": self.max_waiting,
            "wait_timeout_seconds": self.wait_timeout_seconds,
            "rejected": self.rejected,
            "timed_out": self.timed_out,
        }

    def wrap(self, provider):
        if isinstance(provider, BoundedModelProvider) and provider.budget is self:
            return provider
        return BoundedModelProvider(provider, self)


class BoundedModelProvider:
    def __init__(self, provider, budget: ModelConcurrencyBudget):
        self.provider = provider
        self.budget = budget

    def __getattr__(self, name):
        return getattr(self.provider, name)

    async def capabilities(self, model_binding):
        return await self.provider.capabilities(model_binding)

    async def probe_capabilities(self, request):
        async with self.budget.lease():
            return await self.provider.probe_capabilities(request)

    async def stream(self, request):
        async with self.budget.lease():
            stream = self.provider.stream(request)
            try:
                async for event in stream:
                    yield event
            finally:
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
