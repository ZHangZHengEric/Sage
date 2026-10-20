"""Product observers and resources surrounding SDK-owned Run execution."""

from __future__ import annotations

import asyncio

from sagents.v2.model.provider import ModelProvider
from sagents.v2.model.plugins.concurrency_budget import ModelConcurrencyBudget
from app.v2.server.observability.logging import get_logger

LOGGER = get_logger(__name__)


class ProcessExecution:
    """Tracks product observers; Sage owns Run execution and model identity."""

    def __init__(
        self,
        *,
        fallback_model: ModelProvider | None = None,
    ) -> None:
        self._drives: dict[str, asyncio.Task[None]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._drive_workspaces: dict[str, tuple[str, str]] = {}
        self.model_pool = None
        self.model_budget: ModelConcurrencyBudget | None = None
        self.fallback_model = fallback_model
        self.sandbox_provider = None
        self.sandbox_grant_issuer = None

    def driving(self, run_id: str) -> bool:
        return run_id in self._drives

    def workspace_driving(self, tenant_id: str, agent_id: str) -> bool:
        return any(workspace == (tenant_id, agent_id) and run_id in self._drives
                   for run_id, workspace in self._drive_workspaces.items())

    def adopt(self, run_id: str, task: asyncio.Task[None], *, workspace=None) -> None:
        self._drives[run_id] = task
        if workspace is not None:
            self._drive_workspaces[run_id] = workspace
        self._tasks.add(task)

        def _done(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            if self._drives.get(run_id) is completed:
                self.release(run_id)
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
        self._drive_workspaces.pop(run_id, None)

    async def close(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        self._tasks.clear()
        self._drives.clear()
        self._drive_workspaces.clear()

    def has_model(self, catalog) -> bool:
        if self.fallback_model is not None:
            return True
        return bool(catalog.models)
