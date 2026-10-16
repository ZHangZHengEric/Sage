"""Lazy execution adapter for a catalog Run, independent of Skill loading."""

from __future__ import annotations

from app.v2.server.runtime.loop import CatalogRunDependencies, compose_catalog_loop
from sagents.v2.composition.resources import RunResources
from sagents.v2.contracts.principals import RequestContext


class CatalogRunDriver:
    """Load the catalog Agent, then materialize a sagents/v2 loop for this run."""

    def __init__(self, service: CatalogRunDependencies, run_id: str) -> None:
        self.service = service
        self.run_id = run_id
        self._driver = None
        self._resources: RunResources | None = None

    async def _resolve(self, context: RequestContext):
        if self._driver is not None:
            return self._driver
        runtime = self.service.application.runtime
        command = await runtime.session_store.get_start_command(self.run_id)
        self._driver, self._resources = await compose_catalog_loop(
            self.service,
            command,
            user_id=context.actor.principal_id,
            run_id=self.run_id,
        )
        return self._driver

    async def execute(self, run_id: str, context: RequestContext):
        try:
            return await (await self._resolve(context)).execute(run_id, context)
        finally:
            await self._close_resources()

    async def resume(self, run_id: str, context: RequestContext):
        try:
            return await (await self._resolve(context)).resume(run_id, context)
        finally:
            await self._close_resources()

    async def _close_resources(self) -> None:
        resources = self._resources
        if resources is None:
            return
        await resources.close()
        self._resources = None

    async def close(self) -> None:
        """Retry failed Run cleanup when the owning SAgent settles the driver."""
        await self._close_resources()
