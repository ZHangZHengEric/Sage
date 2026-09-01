"""SAgents V2 module for runtime/execution/scheduler/provider.py."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Protocol, TypeVar

from sagents.v2.runtime.execution.scheduler.contracts import (
    LeaseReleaseReason,
    SchedulerClaimPolicy,
    SchedulerCapabilities,
    WorkItem,
    WorkerLease,
)


_T = TypeVar("_T")


class Scheduler(Protocol):
    async def capabilities(self) -> SchedulerCapabilities: ...
    async def submit(self, work: WorkItem) -> bool: ...

    async def claim(
        self,
        worker_id: str,
        *,
        lease_duration: timedelta,
        policy: SchedulerClaimPolicy | None = None,
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

    async def execute_fenced(
        self, lease: WorkerLease, operation: Callable[[], Awaitable[_T]]
    ) -> _T:
        """Run one mutation while this lease remains authoritative.

        Implementations must prevent a replacement lease from becoming active
        between validation and completion of ``operation``.  This is a plugin
        semantic contract, not a requirement to use a particular database.
        """

        ...

    async def cancel(self, work_id: str) -> bool: ...
    async def close(self) -> None: ...
