"""Execution services exposed without eager implementation imports."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.environment import RunExecutionEnvironment as RunExecutionEnvironment
    from sagents.v2.runtime.execution.configuration import LocalExecutionPolicy as LocalExecutionPolicy
    from sagents.v2.contracts.execution import ExecutionConfigurationSnapshot as ExecutionConfigurationSnapshot
    from sagents.v2.runtime.execution.plugins.local_binding import LocalWorkspaceExecutionBindingProvider as LocalWorkspaceExecutionBindingProvider
    from sagents.v2.runtime.execution.lifecycle import ExecutionBindingLifecycleCoordinator as ExecutionBindingLifecycleCoordinator
    from sagents.v2.runtime.execution.binding import ExecutionBindingProvider as ExecutionBindingProvider
    from sagents.v2.runtime.execution.binding import ExecutionBindingRequest as ExecutionBindingRequest
    from sagents.v2.runtime.execution.resources import ExecutionLifecycleMetrics as ExecutionLifecycleMetrics
    from sagents.v2.runtime.execution.resources import ExecutionResourceRecord as ExecutionResourceRecord
    from sagents.v2.runtime.execution.resources import ExecutionResourceState as ExecutionResourceState
    from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher as LocalWorkerDispatcher
    from sagents.v2.runtime.execution.binding import RunExecutionBinding as RunExecutionBinding


from sagents.v2._lazy import exported_names, resolve_export


_EXPORTS = {
    "RunExecutionEnvironment": ("sagents.v2.runtime.execution.environment", "RunExecutionEnvironment"),
    "LocalExecutionPolicy": ("sagents.v2.runtime.execution.configuration", "LocalExecutionPolicy"),
    "ExecutionConfigurationSnapshot": ("sagents.v2.contracts.execution", "ExecutionConfigurationSnapshot"),
    "LocalWorkspaceExecutionBindingProvider": (
        "sagents.v2.runtime.execution.plugins.local_binding",
        "LocalWorkspaceExecutionBindingProvider",
    ),
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

__all__ = [
    "RunExecutionEnvironment",
    "LocalExecutionPolicy",
    "ExecutionConfigurationSnapshot",
    "LocalWorkspaceExecutionBindingProvider",
    "ExecutionBindingLifecycleCoordinator",
    "ExecutionBindingProvider",
    "ExecutionBindingRequest",
    "ExecutionLifecycleMetrics",
    "ExecutionResourceRecord",
    "ExecutionResourceState",
    "LocalWorkerDispatcher",
    "RunExecutionBinding",
]


def __getattr__(name: str):
    return resolve_export(name, _EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_EXPORTS, globals())
