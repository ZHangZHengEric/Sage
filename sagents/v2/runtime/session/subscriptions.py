# pyright: strict
"""Replay/fanout/backpressure isolated from Session state transitions."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from sagents.v2.contracts.events import RuntimeEvent


CommitObserver = Callable[[str, tuple[RuntimeEvent, ...]], None]
_commit_observer: ContextVar[CommitObserver | None] = ContextVar("sage_commit_observer", default=None)


@contextmanager
def observe_commits(observer: CommitObserver | None) -> Iterator[None]:
    """Expose committed events to the caller's execution scope without replay."""
    token = _commit_observer.set(observer)
    try:
        yield
    finally:
        _commit_observer.reset(token)


def notify_committed_events(run_id: str, events: tuple[RuntimeEvent, ...]) -> None:
    observer = _commit_observer.get()
    if observer is not None:
        try:
            observer(run_id, events)
        except Exception:
            # A post-commit projection must not change the committed outcome.
            pass



class SubscriptionHub:
    def __init__(self, *, queue_size: int = 256) -> None:
        self.queue_size = queue_size
        self._history: dict[str, list[object]] = {}
        self._subscribers: dict[str, set[asyncio.Queue[object]]] = {}

    async def publish(self, stream_id: str, sequence: int, value: object) -> None:
        history = self._history.setdefault(stream_id, [])
        if sequence != len(history) + 1:
            raise ValueError("subscription sequence must be contiguous")
        history.append(value)
        for queue in tuple(self._subscribers.get(stream_id, ())):
            try:
                queue.put_nowait(value)
            except asyncio.QueueFull:
                self._subscribers[stream_id].discard(queue)
                queue.get_nowait()
                queue.put_nowait(RuntimeError("subscription backpressure overflow"))

    async def subscribe(self, stream_id: str, after: int = 0) -> AsyncIterator[object]:
        queue: asyncio.Queue[object] = asyncio.Queue(maxsize=self.queue_size)
        replay = tuple(self._history.get(stream_id, ()))[after:]
        self._subscribers.setdefault(stream_id, set()).add(queue)
        try:
            for value in replay:
                yield value
            while True:
                value = await queue.get()
                if isinstance(value, Exception):
                    raise value
                yield value
        finally:
            self._subscribers.get(stream_id, set()).discard(queue)
