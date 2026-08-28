"""SAgents V2 module for runtime/execution/scheduler/provider.py."""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from sagents.v2.runtime.execution.scheduler.contracts import (
    LeaseReleaseReason,
    SchedulerCapabilities,
    WorkItem,
    WorkerLease,
)


class Scheduler(Protocol):
    async def capabilities(self) -> SchedulerCapabilities: ...
    async def submit(self, work: WorkItem) -> bool: ...

    async def claim(
        self,
        worker_id: str,
        *,
        lease_duration: timedelta,
        wait_timeout: float | None = None,
    ) -> WorkerLease | None: ...

    async def renew(
        self, lease: WorkerLease, *, lease_duration: timedelta
    ) -> WorkerLease: ...

    async def release(
        self,
        lease: WorkerLease,
        reason: LeaseReleaseReason,
        *,
        requeue: bool = False,
    ) -> None: ...

    async def assert_fence(self, lease: WorkerLease) -> None: ...
    async def cancel(self, work_id: str) -> bool: ...
    async def close(self) -> None: ...
