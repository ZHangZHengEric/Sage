"""Bounded-latency persistence for high-frequency model stream deltas."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from sagents.v2.contracts.run_state import RunSnapshot
from sagents.v2.runtime.session.contracts import EventDraft


BatchCommit = Callable[
    [RunSnapshot, tuple[EventDraft, ...]], Awaitable[RunSnapshot]
]


class StreamEventBatcher:
    """Merge compatible deltas and flush by latency, size, or explicit barrier."""

    def __init__(
        self,
        run: RunSnapshot,
        commit: BatchCommit,
        *,
        max_delay_seconds: float = 0.05,
        max_bytes: int = 4096,
    ) -> None:
        self._run = run
        self._commit = commit
        self._max_delay = max_delay_seconds
        self._max_bytes = max_bytes
        self._drafts: list[EventDraft] = []
        self._bytes = 0
        self._timer: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._error: BaseException | None = None

    async def add(self, draft: EventDraft) -> RunSnapshot:
        async with self._lock:
            self._raise_error()
            if self._drafts and self._can_merge(self._drafts[-1], draft):
                previous = self._drafts[-1]
                previous_delta = previous.data.delta or ""
                next_delta = draft.data.delta or ""
                self._drafts[-1] = replace(
                    previous,
                    data=previous.data.model_copy(
                        update={"delta": previous_delta + next_delta}
                    ),
                )
            else:
                self._drafts.append(draft)
            self._bytes += len((draft.data.delta or "").encode("utf-8"))
            if self._timer is None:
                self._timer = asyncio.create_task(self._flush_after_delay())
            should_flush = self._bytes >= self._max_bytes
        if should_flush:
            return await self.flush()
        return self._run

    async def observe_run(self, run: RunSnapshot) -> None:
        """Advance the CAS base after an out-of-band steer or pause commit."""

        async with self._lock:
            if run.revision > self._run.revision:
                self._run = run

    async def flush(self) -> RunSnapshot:
        async with self._lock:
            self._raise_error()
            timer = self._timer
            self._timer = None
            if timer is not None and timer is not asyncio.current_task():
                timer.cancel()
            if not self._drafts:
                return self._run
            drafts = tuple(self._drafts)
            self._drafts.clear()
            self._bytes = 0
            self._run = await self._commit(self._run, drafts)
            return self._run

    async def _flush_after_delay(self) -> None:
        try:
            await asyncio.sleep(self._max_delay)
            await self.flush()
        except asyncio.CancelledError:
            return
        except BaseException as exc:  # surfaced synchronously at the next barrier
            async with self._lock:
                self._error = exc

    def _raise_error(self) -> None:
        if self._error is not None:
            raise self._error

    @staticmethod
    def _can_merge(previous: EventDraft, current: EventDraft) -> bool:
        return (
            previous.type == current.type
            and previous.type in {"message.delta", "reasoning.delta"}
            and previous.turn_id == current.turn_id
            and previous.step_id == current.step_id
            and previous.item_id == current.item_id
        )


__all__ = ["StreamEventBatcher"]
