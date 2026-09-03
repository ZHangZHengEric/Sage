"""Scheduler contracts and lazily loaded implementations."""

from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
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

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
