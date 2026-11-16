"""Bound the wait for provider output regardless of SSE heartbeat traffic."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from typing import TypeVar

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error

_Event = TypeVar("_Event")


class StreamIdleTimeout:
    def __init__(self, seconds: float | None, *, provider: str) -> None:
        self.seconds = seconds
        self.provider = provider
        self.response_started = False
        self._finished = False
        self._remaining = seconds
        self._clock = asyncio.get_running_loop().time

    def progress(self) -> None:
        self.response_started = True
        self._remaining = self.seconds

    def finish(self) -> None:
        if not self._finished:
            self._finished = True
            self._remaining = self.seconds

    async def iterate(self, events: AsyncIterable[_Event]) -> AsyncIterator[_Event]:
        if self.seconds is None:
            async for event in events:
                yield event
            return

        self._remaining = self.seconds
        iterator = aiter(events)
        while True:
            remaining = self._remaining
            assert remaining is not None
            if remaining <= 0:
                break
            started_at = self._clock()
            timer = asyncio.timeout_at(started_at + remaining)
            try:
                async with timer:
                    event = await anext(iterator)
            except StopAsyncIteration:
                return
            except TimeoutError:
                if not timer.expired():
                    raise
                break
            # Charge only the upstream read. Parsing and downstream backpressure
            # can suspend this generator at yield without using the idle budget.
            self._remaining = remaining - (self._clock() - started_at)
            if self._remaining <= 0:
                break
            yield event

        if self._finished:
            # Preserve a complete response even if a trailing usage frame stalls.
            return
        raise SageV2Error(
            RuntimeErrorInfo(
                code="model.stream_idle_timeout",
                category=ErrorCategory.PROVIDER_TRANSIENT,
                message=(
                    "The model stream stopped making progress."
                    if self.response_started
                    else "The model stream did not send an initial content fragment."
                ),
                retryable=True,
                safe_to_resume=True,
                metadata={
                    "provider": self.provider,
                    "stream_idle_phase": "mid_stream"
                    if self.response_started
                    else "first_chunk",
                    "stream_idle_timeout_seconds": self.seconds,
                    "response_started": self.response_started,
                },
            )
        )
