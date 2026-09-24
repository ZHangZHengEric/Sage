"""Process-local Run drives, model leases, and sandbox handles."""

from __future__ import annotations

import asyncio

from sagents.v2.model.provider import ModelProvider
from sagents.v2.model.middleware.concurrency import ModelConcurrencyBudget
from app.server_v2.observability.logging import get_logger

LOGGER = get_logger(__name__)


class ProcessExecution:
    """Owns the drives for this process. Use cases bind models through this."""

    def __init__(
        self,
        *,
        fallback_model: ModelProvider | None = None,
    ) -> None:
        self._drives: dict[str, asyncio.Task[None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self.model_pool = None
        self.model_budget: ModelConcurrencyBudget | None = None
        self.fallback_model = fallback_model
        self.sandbox_provider = None
        self.sandbox_grant_issuer = None

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
                LOGGER.exception(
                    "execution.background.failed",
                    "background task failed",
                    error,
                    run_id=run_id,
                )

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
        if self.model_pool is None:
            return False
        self.model_pool.bind_session_user(session_id, user_id)
        return True

    def unbind_model(self, session_id: str) -> None:
        if self.model_pool is not None:
            self.model_pool.unbind_session_user(session_id)

    def has_model(self, catalog) -> bool:
        if self.fallback_model is not None:
            return True
        return bool(catalog.models)
