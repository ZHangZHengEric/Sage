"""Public composition root for SAgents v2.

``SAgentBuilder`` is the only place that selects concrete plugins. The Kernel
and Agent loop receive frozen interfaces and never discover global providers.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from sagents.v2.agent.factory import AgentCompositionFactory
from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    AgentRosterContextProvider,
)
from sagents.v2.model import ModelProvider
from sagents.v2.goal import GoalStateService
from sagents.v2.tool import (
    ToolCatalog,
    ToolExecutor,
    ToolSelectionPolicy,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.execution import (
    ExecutionBindingProvider,
    ExecutionBindingRequest,
    RunExecutionBinding,
)
from sagents.v2.package.manifest.resolver import ResolvedSageManifest
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.package.manifest.root import PluginDeclaration
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.memory import MemoryService
from sagents.v2.memory import MemoryProvider
from sagents.v2.model.protocols import resolve_model_protocol
from sagents.v2.package.manifest.loader import SageManifestLoader
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.runtime.credentials import CredentialMaterial
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.extensions import (
    ExtensionRegistration,
    ExtensionScope,
    ExtensionScopeContext,
    load_installed_extension,
)
from sagents.v2.runtime.extensions.defaults import builtin_extension_registry
from sagents.v2.runtime.session import SessionStore
from sagents.v2.session_memory import SessionMemoryProvider, SessionMemoryService
from sagents.v2.context import SessionDerivedConversationSummaryStore
from sagents.v2.sagent import SAgent
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)
from sagents.v2.tool.plugins.official import OfficialToolRuntime


class _ExecutionBoundDriver:
    """Lazily compose a loop after the Runtime has allocated its Run ID."""

    def __init__(
        self,
        *,
        runtime,
        provider: ExecutionBindingProvider,
        run_id: str,
        agent_id: str,
        loop_builder,
    ) -> None:
        self.runtime = runtime
        self.provider = provider
        self.run_id = run_id
        self.agent_id = agent_id
        self.loop_builder = loop_builder
        self.binding: RunExecutionBinding | None = None
        self.loop = None
        self._lock = None

    async def _ensure_loop(self, context):
        if self.loop is not None:
            return self.loop
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        async with self._lock:
            if self.loop is not None:
                return self.loop
            command = await self.runtime.session_store.get_start_command(self.run_id)
            policy = str(
                command.config.metadata.get("workspace_policy") or "shared_parent"
            )
            self.binding = await self.provider.acquire(
                ExecutionBindingRequest(
                    run_id=self.run_id,
                    parent_run_id=command.parent_run_id,
                    agent_id=self.agent_id,
                    workspace_policy=policy,
                    context=context,
                )
            )
            self.loop = self.loop_builder(self.binding)
            return self.loop

    async def execute(self, run_id, context):
        return await (await self._ensure_loop(context)).execute(run_id, context)

    async def resume(self, run_id, context):
        return await (await self._ensure_loop(context)).resume(run_id, context)

    async def close(self) -> None:
        if self.binding is not None:
            await self.binding.close()


class _OwnerValidatedCompatibilityDriver:
    """Fail closed when a pre-bound Tool runtime belongs to another Run."""

    def __init__(self, loop, tool_runtime: OfficialToolRuntime, run_id: str) -> None:
        self.loop = loop
        self.tool_runtime = tool_runtime
        self.run_id = run_id

    def _validate(self) -> None:
        if self.tool_runtime.sandbox.ref.owner_run_id != self.run_id:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="execution.binding_owner_mismatch",
                    category=ErrorCategory.AUTHORIZATION,
                    message=(
                        "with_tool_runtime sandbox owner does not match the actual "
                        "Run; use with_execution_binding_provider"
                    ),
                    safe_to_resume=False,
                )
            )

    async def execute(self, run_id, context):
        self._validate()
        return await self.loop.execute(run_id, context)

    async def resume(self, run_id, context):
        self._validate()
        return await self.loop.resume(run_id, context)


class SAgentBuilder:
    """Select plugins once and build a fully injected in-process SAgent.

    Hosts may supply concrete providers directly or register additional
    factories. Direct injection is useful when a provider owns an existing
    client connection; registered factories remain the source of inventory and
    normal manifest-driven selection.
    """

    def __init__(self) -> None:
        self.extensions = builtin_extension_registry()
        self._session_root: Path | None = None
        self._session_store: SessionStore | None = None
        self._memory_provider: MemoryProvider | None = None
        self._session_memory_provider: SessionMemoryProvider | None = None
        self._model_provider: ModelProvider | None = None
        self._tool_catalog: ToolCatalog | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tool_runtime: OfficialToolRuntime | None = None
        self._tool_selection: ToolSelectionPolicy | None = None
        self._execution_binding_provider: ExecutionBindingProvider | None = None
        self._model_client: Any | None = None

    def with_defaults(self, *, session_root: str | Path) -> "SAgentBuilder":
        self._session_root = Path(session_root).expanduser().resolve()
        return self

    def register(self, registration: ExtensionRegistration) -> "SAgentBuilder":
        self.extensions.register(registration)
        return self

    def with_session_store(self, value: SessionStore) -> "SAgentBuilder":
        self._session_store = value
        return self

    def with_memory_provider(self, value: MemoryProvider) -> "SAgentBuilder":
        self._memory_provider = value
        return self

    def with_session_memory_provider(
        self, value: SessionMemoryProvider
    ) -> "SAgentBuilder":
        self._session_memory_provider = value
        return self

    def with_model_provider(self, value: ModelProvider) -> "SAgentBuilder":
        self._model_provider = value
        return self

    def with_model_client(self, value: Any) -> "SAgentBuilder":
        self._model_client = value
        return self

    def with_tool_provider(
        self, catalog: ToolCatalog, executor: ToolExecutor
    ) -> "SAgentBuilder":
        self._tool_catalog = catalog
        self._tool_executor = executor
        return self

    def with_tool_runtime(self, runtime: OfficialToolRuntime) -> "SAgentBuilder":
        """Inject the V2-native runtime used by the official Tool plugin."""

        self._tool_runtime = runtime
        return self

    def with_execution_binding_provider(
        self, provider: ExecutionBindingProvider
    ) -> "SAgentBuilder":
        """Inject the Host port that allocates resources for actual Run IDs."""

        self._execution_binding_provider = provider
        return self

    def with_tool_selection(self, value: ToolSelectionPolicy) -> "SAgentBuilder":
        """Inject the model-visible Tool projection policy."""

        self._tool_selection = value
        return self

    def inventory(self) -> tuple[dict, ...]:
        return self.extensions.inventory()

    def build(
        self,
        package: SageManifest | ResolvedSageManifest | str | Path,
        *,
        agent_id: str | None = None,
    ) -> SAgent:
        """Build synchronously from providers whose factories are synchronous."""

        manifest, resolved = self._resolve_package(package)
        plugin_declarations = (
            manifest.plugins if manifest is not None else resolved.plugins
        )
        runtime_config = manifest.runtime if manifest is not None else resolved.runtime
        uses_binding_tools = (
            self._execution_binding_provider is not None
            and runtime_config.tool_provider is not None
            and runtime_config.tool_provider.plugin == "sage.tool.official"
        )
        selected_agent = agent_id or resolved.entrypoint_agent
        if selected_agent is None:
            raise ValueError("SAgentBuilder requires an Agent entrypoint")
        if selected_agent not in resolved.agents:
            raise ValueError(f"unknown Agent entrypoint {selected_agent!r}")
        if (
            (self._tool_catalog is None or self._tool_executor is None)
            and runtime_config.tool_provider is not None
            and runtime_config.tool_provider.plugin == "sage.tool.official"
            and runtime_config.tool_provider.config.get("runtime") is None
            and self._tool_runtime is None
            and self._execution_binding_provider is None
        ):
            raise ValueError(
                "sage.tool.official requires with_execution_binding_provider(provider) "
                "or the compatibility with_tool_runtime(runtime)"
            )
        self._load_declared_plugins(plugin_declarations)
        owned_resources: list[object] = []
        session_store = self._session_store
        if session_store is None:
            session_store = self._create_session_store(
                runtime_config, plugin_declarations
            )
            owned_resources.append(session_store)
        memory_provider = self._memory_provider
        if memory_provider is None:
            memory_provider = self._create_memory_provider(
                runtime_config, plugin_declarations
            )
            owned_resources.append(memory_provider)
        memory_behavior = resolved.agents[selected_agent].memory
        memory_enabled = "search_memory" in resolved.agents[selected_agent].tools
        memory_service = MemoryService(
            memory_provider,
            scope_mode=memory_behavior.scope,
        )
        session_memory_provider = self._session_memory_provider
        if session_memory_provider is None:
            session_memory_provider = self._create_session_memory_provider(
                runtime_config, plugin_declarations
            )
            owned_resources.append(session_memory_provider)
        session_memory_service = SessionMemoryService(
            session_memory_provider, session_store
        )
        model = self._model_provider
        if model is None:
            model = self._create_model(
                manifest, resolved, selected_agent, plugin_declarations
            )
            owned_resources.append(model)
        models_by_agent = {selected_agent: model}
        selected_definition = resolved.agents[selected_agent]
        for member_id in selected_definition.subagents:
            if member_id in models_by_agent:
                continue
            member_model = (
                self._model_provider
                if self._model_provider is not None
                else self._create_model(
                    manifest, resolved, member_id, plugin_declarations
                )
            )
            models_by_agent[member_id] = member_model
            if member_model is not self._model_provider:
                owned_resources.append(member_model)
        tool_selection = self._tool_selection or self._create_tool_selection(
            runtime_config, plugin_declarations
        )
        if self._tool_catalog is not None and self._tool_executor is not None:
            tool_catalog, tool_executor = self._tool_catalog, self._tool_executor
        elif (
            self._execution_binding_provider is not None
            and runtime_config.tool_provider is not None
            and runtime_config.tool_provider.plugin == "sage.tool.official"
        ):
            # The real provider pair is composed lazily from the actual Run
            # binding. These placeholders are never exposed to that driver.
            tool_catalog = InMemoryToolCatalog(())
            tool_executor = InMemoryToolExecutor({}, {})
        elif runtime_config.tool_provider is not None:
            tool_catalog, tool_executor = self._create_tools(
                runtime_config, plugin_declarations
            )
            owned_resources.extend((tool_catalog, tool_executor))
        else:
            tool_catalog = InMemoryToolCatalog(())
            tool_executor = InMemoryToolExecutor({}, {})
            owned_resources.extend((tool_catalog, tool_executor))
        goal_state_service = GoalStateService(session_store)
        if self._tool_runtime is not None:
            self._tool_runtime.memory_service = memory_service
            self._tool_runtime.session_memory_service = session_memory_service
            self._tool_runtime.goal_state_service = goal_state_service
            self._tool_runtime.tool_selection_policy = tool_selection
        runtime = HarnessRuntime(session_store)
        components = ContextComponentBundle(
            summary_store=SessionDerivedConversationSummaryStore(session_store)
        )
        factory = AgentRuntimeFactory(runtime, context_components=components)
        root_descriptor = AgentDescriptor(
            agent_id=selected_agent,
            name=selected_definition.name,
            description="",
            instructions=selected_definition.instructions,
            mode=AgentMode(selected_definition.mode),
            tools=selected_definition.tools,
            skills=selected_definition.skills,
        )
        member_descriptors = tuple(
            AgentDescriptor(
                agent_id=member_id,
                name=resolved.agents[member_id].name,
                description="",
                instructions=resolved.agents[member_id].instructions,
                mode=AgentMode(resolved.agents[member_id].mode),
                tools=resolved.agents[member_id].tools,
                skills=resolved.agents[member_id].skills,
                allow_delegation=False,
            )
            for member_id in selected_definition.subagents
        )

        def configure_official_runtime(value: OfficialToolRuntime) -> None:
            value.memory_service = memory_service
            value.session_memory_service = session_memory_service
            value.goal_state_service = goal_state_service
            value.tool_selection_policy = tool_selection

        def make_loop(
            run_id,
            selected_catalog,
            selected_executor,
            continuation_runtime: OfficialToolRuntime | None,
        ):
            # Each root driver receives a private mutable registry. Dynamic Fibre
            # members therefore cannot leak into another Session built here.
            registry = AgentRegistry(member_descriptors)

            def compose_with_runtime(
                descriptor,
                catalog,
                executor,
                active_runtime: OfficialToolRuntime | None,
            ):
                runtime_tools = ()
                if descriptor.allow_delegation and descriptor.mode == AgentMode.FIBRE:
                    runtime_tools = ("sys_spawn_agent", "sys_delegate_task")
                elif descriptor.allow_delegation and descriptor.mode == AgentMode.TEAM:
                    runtime_tools = ("sys_team_delegate_task",)
                effective_resolved = resolved
                definition_id = descriptor.agent_id
                if definition_id not in resolved.agents:
                    base = resolved.agents[selected_agent]
                    dynamic = base.model_copy(
                        update={
                            "name": descriptor.name,
                            "instructions": descriptor.instructions,
                            "mode": "simple",
                            "tools": descriptor.tools,
                            "skills": descriptor.skills,
                            "subagents": (),
                        }
                    )
                    ceiling = resolved.policy_ceilings[selected_agent].model_copy(
                        update={
                            "allowed_tools": frozenset(descriptor.tools),
                            "allowed_skills": frozenset(descriptor.skills),
                        }
                    )
                    effective_resolved = resolved.model_copy(
                        update={
                            "agents": {**resolved.agents, definition_id: dynamic},
                            "policy_ceilings": {
                                **resolved.policy_ceilings,
                                definition_id: ceiling,
                            },
                        }
                    )
                    models_by_agent[definition_id] = models_by_agent[selected_agent]
                definition = effective_resolved.agents[definition_id]
                member_memory_enabled = "search_memory" in definition.tools
                return factory.create_loop(
                    effective_resolved,
                    definition_id,
                    model=models_by_agent[descriptor.agent_id],
                    tool_catalog=catalog,
                    tool_executor=executor,
                    memory_service=(
                        memory_service
                        if member_memory_enabled and definition.memory.recall
                        else None
                    ),
                    session_memory_service=(
                        session_memory_service if member_memory_enabled else None
                    ),
                    continuation_signal_provider=(
                        active_runtime.consume_continuation_signals
                        if active_runtime is not None
                        else None
                    ),
                    goal_state_service=goal_state_service,
                    tool_selection_policy=tool_selection,
                    additional_runtime_tools=runtime_tools,
                    additional_context_providers=(
                        AgentRosterContextProvider(
                            registry,
                            descriptor.mode,
                            allow_delegation=descriptor.allow_delegation,
                        ),
                    ),
                )

            def compose(descriptor, child_run_id, catalog, executor):
                del child_run_id
                return compose_with_runtime(
                    descriptor,
                    catalog,
                    executor,
                    continuation_runtime,
                )

            async def compose_bound_child(descriptor, child_run_id, child_context):
                assert self._execution_binding_provider is not None
                command = await runtime.session_store.get_start_command(child_run_id)
                binding = await self._execution_binding_provider.acquire(
                    ExecutionBindingRequest(
                        run_id=child_run_id,
                        parent_run_id=command.parent_run_id,
                        agent_id=descriptor.agent_id,
                        workspace_policy=str(
                            command.config.metadata.get("workspace_policy")
                            or "shared_parent"
                        ),
                        context=child_context,
                    )
                )
                child_runtime = OfficialToolRuntime(
                    binding.sandbox,
                    binding.grant_issuer,
                )
                configure_official_runtime(child_runtime)
                child_catalog, child_executor = self._create_tools(
                    runtime_config,
                    plugin_declarations,
                    runtime_override=child_runtime,
                )
                return (
                    compose_with_runtime(
                        descriptor,
                        child_catalog,
                        child_executor,
                        child_runtime,
                    ),
                    binding,
                )

            async def reject_prebound_child(descriptor, child_run_id, child_context):
                del descriptor, child_run_id, child_context
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="execution.binding_owner_mismatch",
                        category=ErrorCategory.AUTHORIZATION,
                        message=(
                            "a pre-bound tool runtime cannot be reused by a child Run; "
                            "use with_execution_binding_provider"
                        ),
                    )
                )

            child_factory = None
            if uses_binding_tools:
                child_factory = compose_bound_child
            elif self._tool_runtime is not None:
                child_factory = reject_prebound_child

            mode_factory = ModeAwareAgentLoopFactory(
                runtime=runtime,
                model_factory=lambda descriptor, _: models_by_agent[
                    descriptor.agent_id
                ],
                base_catalog=selected_catalog,
                base_executor=selected_executor,
                registry=registry,
                resolved_spec_hash=resolved.manifest_hash,
                loop_composer=compose,
                child_loop_factory=child_factory,
            )
            return mode_factory.create_loop(root_descriptor, run_id)

        def driver_factory(run_id):
            if not uses_binding_tools:
                loop = make_loop(
                    run_id, tool_catalog, tool_executor, self._tool_runtime
                )
                if self._tool_runtime is not None:
                    return _OwnerValidatedCompatibilityDriver(
                        loop, self._tool_runtime, run_id
                    )
                return loop

            def loop_builder(binding: RunExecutionBinding):
                official_runtime = OfficialToolRuntime(
                    binding.sandbox,
                    binding.grant_issuer,
                )
                configure_official_runtime(official_runtime)
                bound_catalog, bound_executor = self._create_tools(
                    runtime_config,
                    plugin_declarations,
                    runtime_override=official_runtime,
                )
                return make_loop(
                    run_id,
                    bound_catalog,
                    bound_executor,
                    official_runtime,
                )

            return _ExecutionBoundDriver(
                runtime=runtime,
                provider=self._execution_binding_provider,
                run_id=run_id,
                agent_id=selected_agent,
                loop_builder=loop_builder,
            )

        return SAgent(
            runtime=runtime,
            driver_factory=driver_factory,
            memory_service=(
                memory_service
                if memory_enabled and memory_behavior.auto_write
                else None
            ),
            memory_scope={
                **memory_behavior.model_dump(mode="json"),
                "recall": memory_enabled and memory_behavior.recall,
                "auto_write": memory_enabled and memory_behavior.auto_write,
            },
            owned_resources=tuple(owned_resources),
        )

    def _resolve_package(self, package):
        if isinstance(package, ResolvedSageManifest):
            return None, package
        if isinstance(package, (str, Path)):
            package = SageManifestLoader().load(package)
        if not isinstance(package, SageManifest):
            raise TypeError(
                "package must be SageManifest, ResolvedSageManifest, or sage.yaml"
            )
        return package, CompositionResolver().resolve(package)

    def _load_declared_plugins(
        self, declarations: tuple[PluginDeclaration, ...]
    ) -> None:
        for declaration in declarations:
            if self.extensions.contains(declaration.id):
                continue
            self.extensions.register(load_installed_extension(declaration.id))

    @staticmethod
    def _merge_plugin_config(
        declarations: tuple[PluginDeclaration, ...],
        plugin_id: str,
        selection_config: dict[str, Any],
    ) -> dict[str, Any]:
        defaults = next(
            (
                declaration.config
                for declaration in declarations
                if declaration.id == plugin_id
            ),
            {},
        )
        return {**defaults, **selection_config}

    def _create_session_store(
        self,
        runtime: RuntimeConfig,
        declarations: tuple[PluginDeclaration, ...],
    ) -> SessionStore:
        selection = runtime.session_store
        plugin_id = (
            selection.plugin if selection is not None else "sage.session.filesystem"
        )
        config = self._merge_plugin_config(
            declarations,
            plugin_id,
            dict(selection.config if selection is not None else {}),
        )
        if plugin_id == "sage.session.filesystem" and "root" not in config:
            if self._session_root is None:
                raise ValueError("filesystem SessionStore requires session_root")
            config["root"] = str(self._session_root)
        return self._instantiate(plugin_id, config, "session.store")

    def _create_memory_provider(
        self,
        runtime: RuntimeConfig,
        declarations: tuple[PluginDeclaration, ...],
    ) -> MemoryProvider:
        selection = runtime.memory_provider
        plugin_id = selection.plugin if selection is not None else "sage.memory.noop"
        config = self._merge_plugin_config(
            declarations,
            plugin_id,
            dict(selection.config if selection is not None else {}),
        )
        return self._instantiate(plugin_id, config, "memory.provider")

    def _create_session_memory_provider(
        self,
        runtime: RuntimeConfig,
        declarations: tuple[PluginDeclaration, ...],
    ) -> SessionMemoryProvider:
        selection = runtime.session_memory_provider
        plugin_id = (
            selection.plugin if selection is not None else "sage.session-memory.noop"
        )
        config = self._merge_plugin_config(
            declarations,
            plugin_id,
            dict(selection.config if selection is not None else {}),
        )
        if plugin_id == "sage.session-memory.sqlite-bm25" and "root" not in config:
            if self._session_root is None:
                raise ValueError("SQLite Session Memory requires a root")
            config["root"] = str(self._session_root / "session-memory")
        return self._instantiate(plugin_id, config, "session-memory.provider")

    def _create_model(
        self,
        manifest,
        resolved,
        agent_id,
        declarations: tuple[PluginDeclaration, ...],
    ):
        agent = resolved.agents[agent_id]
        route_id = agent.model_bindings.get("primary")
        if route_id is None:
            raise ValueError(f"agent {agent_id!r} has no primary model binding")
        route_data = resolved.model_routes[route_id]
        selected_plugin = route_data.get("plugin")
        if selected_plugin is None:
            protocol = resolve_model_protocol(route_data["provider"])
            plugin_id = f"sage.model.{protocol.value}"
        else:
            plugin_id = str(selected_plugin)
        config = self._merge_plugin_config(
            declarations,
            plugin_id,
            {"route": route_data, "client": self._model_client},
        )
        if manifest is not None:
            route = manifest.models[route_id]
            if route.credential is not None:
                declaration = manifest.credentials[route.credential]
                if declaration.source == "env" and declaration.key:
                    value = os.getenv(declaration.key)
                    if value:
                        config["credential"] = CredentialMaterial(
                            credential_id=route.credential,
                            secret=SecretStr(value),
                            source="env",
                        )
        return self._instantiate(plugin_id, config, "model.provider")

    def _create_tools(
        self,
        runtime: RuntimeConfig,
        declarations: tuple[PluginDeclaration, ...],
        *,
        runtime_override: OfficialToolRuntime | None = None,
    ) -> tuple[ToolCatalog, ToolExecutor]:
        selection = runtime.tool_provider
        if selection is None:
            return InMemoryToolCatalog(()), InMemoryToolExecutor({}, {})
        config = self._merge_plugin_config(
            declarations, selection.plugin, dict(selection.config)
        )
        if selection.plugin == "sage.tool.official":
            runtime = config.get("runtime") or runtime_override or self._tool_runtime
            if runtime is not None:
                config["runtime"] = runtime
            else:
                raise ValueError(
                    "sage.tool.official requires "
                    "SAgentBuilder.with_tool_runtime(runtime)"
                )
        registration = self.extensions.get(selection.plugin)
        value = registration.factory(
            ExtensionScopeContext(
                scope=ExtensionScope.AGENT,
                scope_id="sagent-builder-tools",
                config=config,
            ),
            {},
        )
        if inspect.isawaitable(value):
            raise TypeError("SAgentBuilder requires a synchronous Tool factory")
        provider = getattr(value, "provider", value)
        catalog = getattr(value, "catalog", provider)
        executor = getattr(value, "executor", provider)
        if not hasattr(catalog, "list_tools") or not hasattr(executor, "execute"):
            raise TypeError(
                f"extension {selection.plugin!r} did not create a Tool provider pair"
            )
        return catalog, executor

    def _create_tool_selection(
        self,
        runtime: RuntimeConfig,
        declarations: tuple[PluginDeclaration, ...],
    ) -> ToolSelectionPolicy:
        selection = runtime.tool_selection
        plugin_id = (
            selection.plugin if selection is not None else "sage.tool-selection.llm"
        )
        if plugin_id in {"hybrid", "sage.tool-selection.hybrid"}:
            plugin_id = "sage.tool-selection.llm"
        config = self._merge_plugin_config(
            declarations,
            plugin_id,
            dict(selection.config if selection is not None else {}),
        )
        return self._instantiate(plugin_id, config, "tool.selection-policy")

    def _instantiate(self, plugin_id: str, config: dict[str, Any], capability: str):
        registration = self.extensions.get(plugin_id)
        if capability not in {
            offer.capability for offer in registration.descriptor.provides
        }:
            raise ValueError(f"extension {plugin_id!r} does not provide {capability!r}")
        value = registration.factory(
            ExtensionScopeContext(
                scope=(
                    ExtensionScope.AGENT
                    if capability == "model.provider"
                    else ExtensionScope.PROCESS
                ),
                scope_id="sagent-builder",
                config=config,
            ),
            {},
        )
        if inspect.isawaitable(value):
            raise TypeError(
                f"extension {plugin_id!r} has an async factory; open it with "
                "ExtensionHost before passing the provider to SAgentBuilder"
            )
        return value


# Compatibility for existing embedders; new code should import the explicit
# composition boundary from ``sagents.v2.agent``.
AgentRuntimeFactory = AgentCompositionFactory
