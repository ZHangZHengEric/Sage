"""Process-local Run drives, model leases, and sandbox handles."""

from __future__ import annotations

import asyncio
import logging

LOGGER = logging.getLogger(__name__)


class ProcessExecution:
    """Owns the drives for this process. Use cases bind models through this."""

    def __init__(self, *, model_missing: str = "") -> None:
        self._drives: dict[str, asyncio.Task[None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._models = None
        self._fallback = None
        self._model_missing = model_missing
        self._logger = None
        self.sandbox_provider = None
        self.sandbox_grant_issuer = None

    def attach_models(self, models) -> None:
        self._models = models

    def attach_logger(self, logger) -> None:
        self._logger = logger

    def driving(self, run_id: str) -> bool:
        return run_id in self._drives

    def adopt(self, run_id: str, task: asyncio.Task[None]) -> None:
        self._drives[run_id] = task
        self._tasks.add(task)

        def _done(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            if self._drives.get(run_id) is completed:
                self._drives.pop(run_id, None)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                LOGGER.error("background task failed", exc_info=error)

        task.add_done_callback(_done)

    def release(self, run_id: str) -> None:
        self._drives.pop(run_id, None)

    async def close(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._tasks.clear()
        self._drives.clear()

    def bind_model(self, session_id: str, user_id: str) -> bool:
        if self._models is None:
            return False
        self._models.bind_session_user(session_id, user_id)
        return True

    def unbind_model(self, session_id: str) -> None:
        if self._models is not None:
            self._models.unbind_session_user(session_id)

    def has_model(self, catalog) -> bool:
        if self._fallback is not None:
            return True
        return bool(catalog.models)

    def model_missing_message(self) -> str:
        return self._model_missing

    def sagents_logger(self):
        if self._logger is None:
            raise RuntimeError("Server v2 runtime is not started")
        return self._logger

    @property
    def fallback_model(self):
        return self._fallback

    @property
    def model_pool(self):
        return self._models

    async def acquire_model(self, user_id: str, record):
        if self._models is None:
            raise RuntimeError("model pool is not started")
        return await self._models.acquire_model(user_id, record)
