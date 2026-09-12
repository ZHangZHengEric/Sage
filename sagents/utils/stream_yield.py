"""Keep buffered model streams cooperative without rescheduling every token."""
from __future__ import annotations

import asyncio
import time
from sagents.utils.request_latency import current_stream_budget


class StreamYieldBudget:
    def __init__(self, max_block_seconds=0.005, *, clock=None):
        if max_block_seconds <= 0:
            raise ValueError('Stream yield interval must be positive')
        self.interval = max_block_seconds
        self.clock = clock or time.perf_counter
        self.deadline = self.clock() + self.interval

    async def iterate(self, stream):
        iterator = stream.__aiter__()
        while True:
            try:
                chunk = await _ResumeTrackedAwaitable(iterator.__anext__(), self)
            except StopAsyncIteration:
                return
            yield chunk

    def resumed(self):
        # Called only when the SDK awaitable actually yielded to its caller.
        # Reset BEFORE running SDK continuation code, so decoding buffered data
        # after resumption still consumes the cooperative processing budget.
        self.deadline = self.clock() + self.interval

    async def checkpoint(self):
        # SDK network reads already yield when waiting for data. For buffered
        # data, cap uninterrupted processing at 5 ms instead of scheduling a
        # separate loop round trip for each tiny delta. Message order/content
        # and SDK chunk boundaries are unchanged.
        if self.clock() >= self.deadline:
            budget = current_stream_budget()
            started = time.perf_counter() if budget is not None else None
            try:
                await asyncio.sleep(0)
            finally:
                if budget is not None:
                    budget.add_stream_timing("stream.scheduler_yield", time.perf_counter() - started)
            self.deadline = self.clock() + self.interval


class _ResumeTrackedAwaitable:
    """Delegate the await protocol without tasks, callbacks, or busy polling.

    An immediately available chunk never yields and does not reset the budget.
    A real suspension (including sleep(0)) resets it just before continuation.
    Future objects and values are forwarded unchanged to asyncio's Task driver.
    """
    def __init__(self, awaitable, budget):
        self.awaitable = awaitable
        self.budget = budget

    def __await__(self):
        iterator = self.awaitable.__await__()
        try:
            pending = next(iterator)
            while True:
                try:
                    value = yield pending
                except GeneratorExit:
                    close = getattr(iterator, "close", None)
                    if close is not None:
                        close()
                    raise
                except BaseException as exc:
                    self.budget.resumed()
                    throw = getattr(iterator, "throw", None)
                    if throw is None:
                        raise
                    pending = throw(exc)
                else:
                    self.budget.resumed()
                    pending = next(iterator) if value is None else iterator.send(value)
        except StopIteration as done:
            return done.value
