"""Wire run-owned official tools after the execution binding is acquired.

The execution driver owns acquisition, validation and cleanup. This composer
only initializes the bound workspace and injects run/Agent-scoped services;
plugin scopes remain registered by the application-supplied opener.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from typing import Protocol

from sagents.v2.goal import GoalStateService
from sagents.v2.session_memory import SessionMemoryService
from sagents.v2.runtime.artifact.contracts import ArtifactStore
from sagents.v2.runtime.execution.jobs import JobRuntime
from sagents.v2.runtime.extensions.scope import ExtensionScopeHandle
from sagents.v2.workspace.contracts import WorkspaceInitializer
from sagents.v2.memory import MemoryService
from sagents.v2.runtime.execution import RunExecutionBinding
from sagents.v2.tool import ToolCatalog, ToolExecutor, ToolSelectionPolicy
from sagents.v2.tool.official import OfficialToolRuntime


class BoundToolScope(Protocol):
    @property
    def provider_scopes(self) -> tuple[ExtensionScopeHandle, ...]: ...

    async def close(self) -> None: ...


@dataclass(frozen=True)
class BoundTools:
    catalog: ToolCatalog
    executor: ToolExecutor
    runtime: OfficialToolRuntime
    scope: BoundToolScope | None


@dataclass(frozen=True)
class BoundToolComposer:
    open_tools: Callable[
        ..., Awaitable[tuple[ToolCatalog, ToolExecutor, BoundToolScope | None, OfficialToolRuntime]]
    ]
    workspace_initializer: WorkspaceInitializer
    artifact_store: ArtifactStore
    job_runtime: JobRuntime
    memory_services: Mapping[str, MemoryService]
    default_memory_service: MemoryService | None
    session_memory_service: SessionMemoryService | None
    goal_state_service: GoalStateService | None
    tool_selection: ToolSelectionPolicy | None

    async def compose(
        self,
        binding: RunExecutionBinding,
        *,
        tenant_id: str | None,
        agent_id: str,
    ) -> BoundTools:
        await binding.initialize_workspace(self.workspace_initializer)
        from sagents.v2.runtime.execution.environment import _active_environment, _bind_execution_environment
        environment = _active_environment.get()
        if environment is None or environment.run_id != binding.run_id:
            raise RuntimeError("bound tools require their actual SDK Run environment")
        environment = replace(environment,
            memory_service=self.memory_services.get(agent_id, self.default_memory_service),
            session_memory_service=self.session_memory_service,
            goal_state_service=self.goal_state_service)
        with _bind_execution_environment(environment):
            catalog, executor, scope, runtime = await self.open_tools(
                include_runtime=True, tenant_id=tenant_id, agent_id=agent_id, run_id=binding.run_id,
            )
        return BoundTools(catalog, executor, runtime, scope)
