"""Scheduler contracts and lazily loaded implementations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.scheduler.plugins.redis_distributed import RedisDistributedScheduler as RedisDistributedScheduler
    from sagents.v2.runtime.execution.scheduler.plugins.filesystem import FilesystemScheduler as FilesystemScheduler
    from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import InMemoryScheduler as InMemoryScheduler
    from sagents.v2.runtime.execution.scheduler.contracts import LeaseReleaseReason as LeaseReleaseReason
    from sagents.v2.runtime.execution.scheduler.provider import Scheduler as Scheduler
    from sagents.v2.runtime.execution.scheduler.contracts import SchedulerCapabilities as SchedulerCapabilities
    from sagents.v2.runtime.execution.scheduler.contracts import SchedulerClaimPolicy as SchedulerClaimPolicy
    from sagents.v2.runtime.execution.scheduler.plugins.filesystem import SchedulerInUseError as SchedulerInUseError
    from sagents.v2.runtime.execution.scheduler.contracts import WorkItem as WorkItem
    from sagents.v2.runtime.execution.scheduler.contracts import WorkerLease as WorkerLease


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "RedisDistributedScheduler": (
        "sagents.v2.runtime.execution.scheduler.plugins.redis_distributed", "RedisDistributedScheduler",
    ),
    "FilesystemScheduler": (
        "sagents.v2.runtime.execution.scheduler.plugins.filesystem",
        "FilesystemScheduler",
    ),
    "InMemoryScheduler": (
        "sagents.v2.runtime.execution.scheduler.plugins.ephemeral",
        "InMemoryScheduler",
    ),
    "LeaseReleaseReason": (
        "sagents.v2.runtime.execution.scheduler.contracts",
        "LeaseReleaseReason",
    ),
    "Scheduler": ("sagents.v2.runtime.execution.scheduler.provider", "Scheduler"),
    "SchedulerCapabilities": (
        "sagents.v2.runtime.execution.scheduler.contracts",
        "SchedulerCapabilities",
    ),
    "SchedulerClaimPolicy": (
        "sagents.v2.runtime.execution.scheduler.contracts",
        "SchedulerClaimPolicy",
    ),
    "SchedulerInUseError": (
        "sagents.v2.runtime.execution.scheduler.plugins.filesystem",
        "SchedulerInUseError",
    ),
    "WorkItem": ("sagents.v2.runtime.execution.scheduler.contracts", "WorkItem"),
    "WorkerLease": ("sagents.v2.runtime.execution.scheduler.contracts", "WorkerLease"),
}

__all__ = [
    "RedisDistributedScheduler",
    "FilesystemScheduler",
    "InMemoryScheduler",
    "LeaseReleaseReason",
    "Scheduler",
    "SchedulerCapabilities",
    "SchedulerClaimPolicy",
    "SchedulerInUseError",
    "WorkItem",
    "WorkerLease",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
