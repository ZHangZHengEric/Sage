"""Compose Simple/Fibre/Team bodies from the shared Agent Loop."""

from __future__ import annotations

from collections.abc import Callable

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.context import DefaultContextAssembler
from sagents.v2.model import ModelProvider
from sagents.v2.tool import (
    CompositeToolCatalog,
    CompositeToolExecutor,
    FilteredToolCatalog,
    ToolCatalog,
    ToolExecutor,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    MultiAgentCoordinator,
)
from sagents.v2.tool.plugins.official.delegation import MultiAgentToolPlugin
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor


ModelProviderFactory = Callable[[AgentDescriptor, str], ModelProvider]


class ModeAwareAgentLoopFactory:
    """Shared composition root for Simple, Fibre, and Team node bodies."""

    def __init__(
        self,
        *,
        runtime: HarnessRuntime,
        model_factory: ModelProviderFactory,
        base_catalog: ToolCatalog,
        base_executor: ToolExecutor,
        registry: AgentRegistry,
        resolved_spec_hash: str,
        max_delegation_concurrency: int = 4,
    ) -> None:
        self.runtime = runtime
        self.model_factory = model_factory
        self.base_catalog = base_catalog
        self.base_executor = base_executor
        self.registry = registry
        self.resolved_spec_hash = resolved_spec_hash
        self.max_delegation_concurrency = max_delegation_concurrency
        self._coordinators: dict[tuple[str, AgentMode], MultiAgentCoordinator] = {}
        self.child_executor = LoopChildRunExecutor(
            runtime=runtime,
            loop_factory=self.create_loop,
            resolved_spec_hash=resolved_spec_hash,
        )

    def create_loop(self, descriptor: AgentDescriptor, run_id: str) -> AgentLoopEngine:
        """Add delegation tools only for multi-agent modes, then build one Loop."""

        catalogs: list[ToolCatalog] = [
            FilteredToolCatalog(self.base_catalog, descriptor.tools)
        ]
        executors: list[ToolExecutor] = [self.base_executor]
        if descriptor.mode in {AgentMode.FIBRE, AgentMode.TEAM}:
            # Multi-agent behavior is exposed to the model as typed tools backed
            # by child Runs. The core Loop itself does not special-case Fibre or
            # Team and therefore keeps one completion/tool protocol.
            key = (descriptor.agent_id, descriptor.mode)
            coordinator = self._coordinators.get(key)
            if coordinator is None:
                coordinator = MultiAgentCoordinator(
                    mode=descriptor.mode,
                    registry=self.registry,
                    executor=self.child_executor,
                    max_concurrency=self.max_delegation_concurrency,
                )
                self._coordinators[key] = coordinator
            suite = MultiAgentToolPlugin(coordinator=coordinator, runtime=self.runtime)
            catalogs.append(suite.catalog)
            executors.append(suite.executor)
        return AgentLoopEngine(
            runtime=self.runtime,
            model=self.model_factory(descriptor, run_id),
            tool_catalog=CompositeToolCatalog(tuple(catalogs)),
            tool_executor=CompositeToolExecutor(tuple(executors)),
            context_assembler=DefaultContextAssembler(
                developer_instructions=descriptor.instructions,
                history_reader=self.runtime.session_store,
            ),
        )
