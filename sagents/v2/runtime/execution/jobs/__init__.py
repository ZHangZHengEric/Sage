"""Job runtime contracts and lazily exported plugin implementations."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.jobs.plugins.ephemeral import InMemoryJobRuntime as InMemoryJobRuntime
    from sagents.v2.runtime.execution.jobs.plugins.redis_distributed import RedisDistributedJobRuntime as RedisDistributedJobRuntime
    from sagents.v2.runtime.execution.jobs.provider import JobEmitter as JobEmitter
    from sagents.v2.runtime.execution.jobs.provider import JobRunner as JobRunner
    from sagents.v2.runtime.execution.jobs.provider import JobRuntime as JobRuntime


from sagents.v2._lazy import exported_names, resolve_export

_EXPORTS = {
    "InMemoryJobRuntime": (
        "sagents.v2.runtime.execution.jobs.plugins.ephemeral",
        "InMemoryJobRuntime",
    ),
    "RedisDistributedJobRuntime": (
        "sagents.v2.runtime.execution.jobs.plugins.redis_distributed",
        "RedisDistributedJobRuntime",
    ),
    "JobEmitter": ("sagents.v2.runtime.execution.jobs.provider", "JobEmitter"),
    "JobRunner": ("sagents.v2.runtime.execution.jobs.provider", "JobRunner"),
    "JobRuntime": ("sagents.v2.runtime.execution.jobs.provider", "JobRuntime"),
}
__all__ = [
    "InMemoryJobRuntime",
    "RedisDistributedJobRuntime",
    "JobEmitter",
    "JobRunner",
    "JobRuntime",
]


def __getattr__(name):
    return resolve_export(name, _EXPORTS, globals())


def __dir__():
    return exported_names(_EXPORTS, globals())
