"""Non-blocking delivery of voice events to observers."""

import asyncio
import inspect
import logging
from collections.abc import Iterable

from .events import VoiceEvent
from .observer import VoiceObserver

logger = logging.getLogger(__name__)
_OBSERVER_CLOSE_TIMEOUT_SECONDS = 1.0


class _Stop:
    __slots__ = ()


_STOP = _Stop()


class _EventDispatcher:
    """Preserve event order per observer without blocking session work."""

    def __init__(self, observers: Iterable[VoiceObserver]) -> None:
        self._observers = tuple(observers)
        self._queues = tuple(
            asyncio.Queue[VoiceEvent | _Stop]() for _ in self._observers
        )
        self._tasks: tuple[asyncio.Task[None], ...] = ()

    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = tuple(
            asyncio.create_task(
                self._run(observer, queue),
                name=f"lalk-observer-{index}",
            )
            for index, (observer, queue) in enumerate(
                zip(self._observers, self._queues, strict=True)
            )
        )

    def emit(self, event: VoiceEvent) -> None:
        if not self._tasks:
            return
        for queue in self._queues:
            queue.put_nowait(event)

    async def close(self) -> None:
        tasks = self._tasks
        if not tasks:
            return
        self._tasks = ()
        for queue in self._queues:
            queue.put_nowait(_STOP)
        try:
            async with asyncio.timeout(_OBSERVER_CLOSE_TIMEOUT_SECONDS):
                await asyncio.gather(*tasks)
        except TimeoutError:
            logger.warning("Timed out waiting for voice observers to close")
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    async def _run(
        observer: VoiceObserver,
        queue: asyncio.Queue[VoiceEvent | _Stop],
    ) -> None:
        while True:
            event = await queue.get()
            if isinstance(event, _Stop):
                return
            try:
                result = observer.on_event(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception("Voice observer failed")
