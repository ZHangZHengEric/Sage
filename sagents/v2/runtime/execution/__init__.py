"""Execution services exposed without eager implementation imports."""

from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "ExecutionBindingLifecycleCoordinator": (
        "sagents.v2.runtime.execution.lifecycle",
        "ExecutionBindingLifecycleCoordinator",
    ),
    "ExecutionBindingProvider": (
        "sagents.v2.runtime.execution.binding",
        "ExecutionBindingProvider",
    ),
    "ExecutionBindingRequest": (
        "sagents.v2.runtime.execution.binding",
        "ExecutionBindingRequest",
    ),
    "ExecutionLifecycleMetrics": (
        "sagents.v2.runtime.execution.resources",
        "ExecutionLifecycleMetrics",
    ),
    "ExecutionResourceRecord": (
        "sagents.v2.runtime.execution.resources",
        "ExecutionResourceRecord",
    ),
    "ExecutionResourceState": (
        "sagents.v2.runtime.execution.resources",
        "ExecutionResourceState",
    ),
    "LocalWorkerDispatcher": (
        "sagents.v2.runtime.execution.dispatcher",
        "LocalWorkerDispatcher",
    ),
    "RunExecutionBinding": (
        "sagents.v2.runtime.execution.binding",
        "RunExecutionBinding",
    ),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
