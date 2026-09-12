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
