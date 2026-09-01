"""Compose Simple/Fibre/Team bodies from the shared Agent Loop."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.context import DefaultContextAssembler
from sagents.v2.model import ModelProvider
from sagents.v2.tool import (
    CompositeToolCatalog,
    CompositeToolExecutor,
    InvocationGrantToolCatalog,
    ToolCatalog,
    ToolExecutor,
)
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    DelegationConcurrencyLimiter,
    AgentMode,
    AgentRegistry,
    MultiAgentCoordinator,
    WorkspaceSharingPolicy,
)
from sagents.v2.tool.plugins.official.delegation import MultiAgentToolPlugin
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor


ModelProviderFactory = Callable[[AgentDescriptor, str], ModelProvider]
ModeLoopComposer = Callable[
    [AgentDescriptor, str, ToolCatalog, ToolExecutor],
    AgentLoopEngine | Awaitable[AgentLoopEngine],
]


class ModeAwareAgentLoopFactory:
    """Shared composition root for Simple, Fibre, and Team node bodies."""

    def __init__(
        self,
        *,
        runtime: RuntimePort,
        model_factory: ModelProviderFactory,
        base_catalog: ToolCatalog,
        base_executor: ToolExecutor,
        registry: AgentRegistry,
        resolved_spec_hash: str,
        max_delegation_concurrency: int = 4,
        delegation_concurrency_limiter: DelegationConcurrencyLimiter | None = None,
        loop_composer: ModeLoopComposer | None = None,
        workspace_policy: WorkspaceSharingPolicy = WorkspaceSharingPolicy.SHARED_PARENT,
        fallback_invocation_mode: str | None = None,
        child_loop_factory=None,
        trace_sink=None,
    ) -> None:
        self.runtime = runtime
        self.model_factory = model_factory
        self.base_catalog = base_catalog
        self.base_executor = base_executor
        self.registry = registry
        self.resolved_spec_hash = resolved_spec_hash
        self.max_delegation_concurrency = max_delegation_concurrency
        self.delegation_concurrency_limiter = delegation_concurrency_limiter
        self.loop_composer = loop_composer
        self.workspace_policy = workspace_policy
        self.fallback_invocation_mode = fallback_invocation_mode
        self.trace_sink = trace_sink
        self._coordinators: dict[tuple[str, AgentMode], MultiAgentCoordinator] = {}

        async def build_child(descriptor, run_id, context):
            if child_loop_factory is not None:
                value = child_loop_factory(descriptor, run_id, context)
                if hasattr(value, "__await__"):
                    value = await value
                return value
            return self.create_loop(descriptor, run_id)

        self.child_executor = LoopChildRunExecutor(
            runtime=runtime,
            loop_factory=build_child,
            resolved_spec_hash=resolved_spec_hash,
            descriptor_resolver=registry.get,
        )

    def create_loop(self, descriptor: AgentDescriptor, run_id: str) -> AgentLoopEngine:
        """Add delegation tools only for multi-agent modes, then build one Loop."""

        catalogs: list[ToolCatalog] = [
            InvocationGrantToolCatalog(
                self.base_catalog,
                descriptor.tools,
                self.runtime.session_store.get_start_command,
                fallback_invocation_mode=self.fallback_invocation_mode,
            )
        ]
        executors: list[ToolExecutor] = [self.base_executor]
        if descriptor.allow_delegation and descriptor.mode in {
            AgentMode.FIBRE,
            AgentMode.TEAM,
        }:
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
                    concurrency_limiter=self.delegation_concurrency_limiter,
                    workspace_policy=self.workspace_policy,
                )
                self._coordinators[key] = coordinator
            suite = MultiAgentToolPlugin(coordinator=coordinator, runtime=self.runtime)
            catalogs.append(suite.catalog)
            executors.append(suite.executor)
        catalog = CompositeToolCatalog(tuple(catalogs))
        executor = CompositeToolExecutor(tuple(executors))
        if self.loop_composer is not None:
            loop = self.loop_composer(descriptor, run_id, catalog, executor)
            if inspect.isawaitable(loop):
                close = getattr(loop, "close", None)
                if close is not None:
                    close()
                raise RuntimeError("async loop composers require create_loop_async()")
            loop.delegated_run_controller = self.child_executor
            loop.expected_resolved_spec_hash = self.resolved_spec_hash
            if getattr(loop, "trace_sink", None) is None:
                loop.trace_sink = self.trace_sink
            return loop
        return AgentLoopEngine(
            runtime=self.runtime,
            model=self.model_factory(descriptor, run_id),
            tool_catalog=catalog,
            tool_executor=executor,
            context_assembler=DefaultContextAssembler(
                developer_instructions=descriptor.instructions,
                history_reader=self.runtime.session_store,
            ),
            delegated_run_controller=self.child_executor,
            expected_resolved_spec_hash=self.resolved_spec_hash,
            trace_sink=self.trace_sink,
        )

    async def create_loop_async(
        self, descriptor: AgentDescriptor, run_id: str
    ) -> AgentLoopEngine:
        """Compose a loop while allowing an async host composition callback."""

        catalogs: list[ToolCatalog] = [
            InvocationGrantToolCatalog(
                self.base_catalog,
                descriptor.tools,
                self.runtime.session_store.get_start_command,
                fallback_invocation_mode=self.fallback_invocation_mode,
            )
        ]
        executors: list[ToolExecutor] = [self.base_executor]
        if descriptor.allow_delegation and descriptor.mode in {
            AgentMode.FIBRE,
            AgentMode.TEAM,
        }:
            key = (descriptor.agent_id, descriptor.mode)
            coordinator = self._coordinators.get(key)
            if coordinator is None:
                coordinator = MultiAgentCoordinator(
                    mode=descriptor.mode,
                    registry=self.registry,
                    executor=self.child_executor,
                    max_concurrency=self.max_delegation_concurrency,
                    concurrency_limiter=self.delegation_concurrency_limiter,
                    workspace_policy=self.workspace_policy,
                )
                self._coordinators[key] = coordinator
            suite = MultiAgentToolPlugin(coordinator=coordinator, runtime=self.runtime)
            catalogs.append(suite.catalog)
            executors.append(suite.executor)
        catalog = CompositeToolCatalog(tuple(catalogs))
        executor = CompositeToolExecutor(tuple(executors))
        if self.loop_composer is not None:
            loop = self.loop_composer(descriptor, run_id, catalog, executor)
            if inspect.isawaitable(loop):
                loop = await loop
            loop.delegated_run_controller = self.child_executor
            loop.expected_resolved_spec_hash = self.resolved_spec_hash
            if getattr(loop, "trace_sink", None) is None:
                loop.trace_sink = self.trace_sink
            return loop
        return self.create_loop(descriptor, run_id)
