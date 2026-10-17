"""Typed assembly results, independent of the Builder and Application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sagents.v2.agent.policy.continuation import ContinuationPolicy
from sagents.v2.context.contracts import ContextReducer
from sagents.v2.context.summary import ConversationSummarizer
from sagents.v2.memory.query import MemoryRecallQueryGenerator
from sagents.v2.runtime.extensions import ExtensionScopeHandle
from sagents.v2.tool import ToolCatalog, ToolExecutor
from sagents.v2.tool.selection import ToolSelectionPolicy
from sagents.v2.workspace.contracts import WorkspaceInitializer


class ApplicationResource(Protocol):
    """Async lifecycle resource owned exclusively by the application root."""

    async def close(self) -> None: ...


@dataclass(frozen=True, order=True)
class ResolvedProviderBinding:
    """One inspectable capability binding with no secret configuration."""

    capability: str
    name: str
    api_version: str
    plugin_id: str | None
    scope: str
    source: str


@dataclass(frozen=True)
class ResolvedApplicationPlan:
    """Frozen final composition identity exposed by an application root."""

    package_id: str
    manifest_hash: str
    entrypoint_agent_id: str
    providers: tuple[ResolvedProviderBinding, ...]
    dependencies: tuple[tuple[str, str], ...]
    composition_hash: str


@dataclass(frozen=True)
class MaterializedAgentPorts:
    """Agent/Run ports rematerialized on a live process Application."""

    summarizer: ConversationSummarizer
    context_reducer: ContextReducer
    continuation_policy: ContinuationPolicy
    tool_selection_policy: ToolSelectionPolicy
    memory_query_generator: MemoryRecallQueryGenerator | None
    workspace_initializer: WorkspaceInitializer | None
    resolved_plan: ResolvedApplicationPlan
    scope_handles: tuple[ExtensionScopeHandle, ...]
    skill_loading: Any | None = None
    tool_catalog: ToolCatalog | None = None
    tool_executor: ToolExecutor | None = None
