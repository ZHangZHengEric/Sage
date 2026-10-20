"""Job runtime contracts and lazily exported plugin implementations."""

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
__all__ = list(_EXPORTS)


def __getattr__(name):
    return resolve_export(name, _EXPORTS, globals())


def __dir__():
    return exported_names(_EXPORTS, globals())
