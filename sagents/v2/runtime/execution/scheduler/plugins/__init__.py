"""Scheduler plugins exposed without eager sibling imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.scheduler.plugins.filesystem import FilesystemScheduler as FilesystemScheduler
    from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import InMemoryScheduler as InMemoryScheduler
    from sagents.v2.runtime.execution.scheduler.plugins.filesystem import SchedulerInUseError as SchedulerInUseError


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
    "SchedulerInUseError": (
        "sagents.v2.runtime.execution.scheduler.plugins.filesystem",
        "SchedulerInUseError",
    ),
}

__all__ = [
    "FilesystemScheduler",
    "InMemoryScheduler",
    "SchedulerInUseError",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
