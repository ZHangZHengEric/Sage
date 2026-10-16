"""Run-owned resources, independent of plugins and transport adapters.

Services close before their execution dependencies (for example a sandbox).
A failed service close leaves dependencies alive; only failed resources retry.
Composition rollback attempts all acquired resources, matching admission cleanup.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


class AsyncResource(Protocol):
    async def close(self) -> None: ...


T = TypeVar("T")


class RunResources:
    def __init__(self) -> None:
        self.services: list[AsyncResource] = []
        self.dependencies: list[AsyncResource] = []
        self._lock = asyncio.Lock()

    def own(self, resource: AsyncResource, *, dependency: bool = False) -> None:
        """Register ownership once; borrowed resources must never be registered."""
        if any(resource is item for item in (*self.services, *self.dependencies)):
            return
        (self.dependencies if dependency else self.services).append(resource)

    @property
    def pending(self) -> bool:
        return bool(self.services or self.dependencies)

    @staticmethod
    async def _close_group(resources: list[AsyncResource]) -> list[BaseException]:
        errors: list[BaseException] = []
        failed: list[AsyncResource] = []
        for resource in reversed(resources):
            try:
                await resource.close()
            except BaseException as exc:
                errors.append(exc)
                failed.append(resource)
        resources[:] = reversed(failed)
        return errors

    async def close(self) -> None:
        async with self._lock:
            errors = await self._close_group(self.services)
            if not self.services:
                errors.extend(await self._close_group(self.dependencies))
            if errors:
                raise errors[0]

    async def rollback(self, cause: BaseException) -> None:
        """Keep the composition error primary and retain failed cleanup for retry."""
        async with self._lock:
            errors = await self._close_group(self.services)
            errors.extend(await self._close_group(self.dependencies))
            for error in errors:
                cause.add_note(f"Run composition rollback also failed: {error}")


@dataclass(frozen=True)
class ComposedRun(Generic[T]):
    """A composed driver/value and the resources its host must eventually close."""

    value: T
    resources: RunResources

    async def close(self) -> None:
        await self.resources.close()
