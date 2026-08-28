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

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.context import (
    ContextBudget,
    DefaultContextAssembler,
    RunMetadataContextProvider,
)
from sagents.v2.context.contracts import ContextSegmentProvider
from sagents.v2.model import ModelProvider
from sagents.v2.agent.policy.continuation import ContinuationPolicy
from sagents.v2.agent.policy.tool_policy import DefaultToolPolicy
from sagents.v2.skill import (
    ActiveSkillsContextProvider,
    AvailableSkillsContextProvider,
    FilteredSkillCatalog,
    SkillActivationRepository,
    SkillCatalog,
    SkillLoader,
    SkillSource,
    SkillWorkspace,
)
from sagents.v2.tool import FilteredToolCatalog, ToolCatalog, ToolExecutor
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.package.manifest.resolver import ResolvedSageManifest
from sagents.v2.package.manifest.resolver import CompositionResolver
from sagents.v2.context.components import ContextComponentBundle
from sagents.v2.memory import MemoryContextSource, MemoryService
from sagents.v2.memory import MemoryProvider
from sagents.v2.model.protocols import resolve_model_protocol
from sagents.v2.package.manifest.loader import SageManifestLoader
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.runtime.credentials import CredentialMaterial
from sagents.v2.runtime.extensions import (
    ExtensionRegistration,
    ExtensionScope,
    ExtensionScopeContext,
)
from sagents.v2.runtime.extensions.defaults import builtin_extension_registry
from sagents.v2.runtime.session import SessionStore
from sagents.v2.context import SessionDerivedConversationSummaryStore
from sagents.v2.sagent import SAgent
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)
from sagents.v2.tool.plugins.official import OfficialToolRuntime


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
        self._model_provider: ModelProvider | None = None
        self._tool_catalog: ToolCatalog | None = None
        self._tool_executor: ToolExecutor | None = None
        self._tool_runtime: OfficialToolRuntime | None = None
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
        selected_agent = agent_id or resolved.entrypoint_agent
        if selected_agent is None:
            raise ValueError("SAgentBuilder requires an Agent entrypoint")
        session_store = self._session_store or self._create_session_store(manifest)
        memory_provider = self._memory_provider or self._create_memory_provider(
            manifest
        )
        memory_behavior = resolved.agents[selected_agent].memory
        memory_service = MemoryService(
            memory_provider,
            scope_mode=memory_behavior.scope,
        )
        model = self._model_provider or self._create_model(
            manifest, resolved, selected_agent
        )
        if self._tool_catalog is not None and self._tool_executor is not None:
            tool_catalog, tool_executor = self._tool_catalog, self._tool_executor
        elif manifest is not None and manifest.runtime.tool_provider is not None:
            tool_catalog, tool_executor = self._create_tools(manifest)
        else:
            tool_catalog = InMemoryToolCatalog(())
            tool_executor = InMemoryToolExecutor({}, {})
        runtime = HarnessRuntime(session_store)
        components = ContextComponentBundle(
            summary_store=SessionDerivedConversationSummaryStore(session_store)
        )
        factory = AgentRuntimeFactory(runtime, context_components=components)
        loop = factory.create_loop(
            resolved,
            selected_agent,
            model=model,
            tool_catalog=tool_catalog,
            tool_executor=tool_executor,
            memory_service=(memory_service if memory_behavior.recall else None),
        )
        return SAgent(
            runtime=runtime,
            driver_factory=lambda run_id: loop,
            memory_service=(memory_service if memory_behavior.auto_write else None),
            memory_scope=memory_behavior.model_dump(mode="json"),
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

    def _create_session_store(self, manifest: SageManifest | None) -> SessionStore:
        selection = manifest.runtime.session_store if manifest is not None else None
        plugin_id = (
            selection.plugin if selection is not None else "sage.session.filesystem"
        )
        config = dict(selection.config if selection is not None else {})
        if plugin_id == "sage.session.filesystem" and "root" not in config:
            if self._session_root is None:
                raise ValueError("filesystem SessionStore requires session_root")
            config["root"] = str(self._session_root)
        return self._instantiate(plugin_id, config, "session.store")

    def _create_memory_provider(self, manifest: SageManifest | None) -> MemoryProvider:
        selection = manifest.runtime.memory_provider if manifest is not None else None
        plugin_id = selection.plugin if selection is not None else "sage.memory.noop"
        config = dict(selection.config if selection is not None else {})
        return self._instantiate(plugin_id, config, "memory.provider")

    def _create_model(self, manifest, resolved, agent_id):
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
        config: dict[str, Any] = {"route": route_data, "client": self._model_client}
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
        self, manifest: SageManifest
    ) -> tuple[ToolCatalog, ToolExecutor]:
        selection = manifest.runtime.tool_provider
        if selection is None:
            return InMemoryToolCatalog(()), InMemoryToolExecutor({}, {})
        config = dict(selection.config)
        if selection.plugin == "sage.tool.official":
            runtime = config.get("runtime") or self._tool_runtime
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


class AgentRuntimeFactory:
    """Composition root: resolved manifest in, runnable capability graph out.

    Kernel and Agent Loop code never discover global Providers. The host calls
    this factory after manifest resolution and supplies the concrete Model,
    Tool, Skill, Policy, and storage implementations for its environment.
    """

    def __init__(
        self,
        runtime: HarnessRuntime,
        *,
        context_components: ContextComponentBundle | None = None,
    ) -> None:
        self.runtime = runtime
        self.context_components = context_components or ContextComponentBundle()

    def create_skill_loader(
        self,
        resolved: ResolvedSageManifest,
        agent_id: str,
        *,
        catalog: SkillCatalog,
        source: SkillSource,
        workspace: SkillWorkspace,
        activations: SkillActivationRepository,
        enabled_skills: tuple[str, ...] | None = None,
        workspace_root: str = "/workspace",
    ) -> SkillLoader:
        """Create a lazy loader restricted to the Agent's resolved Skill ceiling."""

        agent = resolved.agents[agent_id]
        ceiling = resolved.policy_ceilings[agent_id]
        selected = tuple(enabled_skills) if enabled_skills is not None else agent.skills
        outside_ceiling = sorted(set(selected) - ceiling.allowed_skills)
        if outside_ceiling:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="manifest.skill_override_denied",
                    category=ErrorCategory.POLICY_DENIED,
                    message=f"skills exceed agent policy ceiling: {outside_ceiling}",
                )
            )
        return SkillLoader(
            catalog=FilteredSkillCatalog(catalog, selected),
            source=source,
            workspace=workspace,
            activations=activations,
            workspace_root=workspace_root,
        )

    def create_loop(
        self,
        resolved: ResolvedSageManifest,
        agent_id: str,
        *,
        model: ModelProvider,
        tool_catalog: ToolCatalog,
        tool_executor: ToolExecutor,
        tool_policy: DefaultToolPolicy | None = None,
        continuation_policy: ContinuationPolicy | None = None,
        enabled_tools: tuple[str, ...] | None = None,
        skill_loader: SkillLoader | None = None,
        memory_service: MemoryService | None = None,
    ) -> AgentLoopEngine:
        """Create the standard single-Agent Loop from resolved capabilities."""

        agent = resolved.agents[agent_id]
        ceiling = resolved.policy_ceilings[agent_id]
        selected_tools = (
            tuple(enabled_tools) if enabled_tools is not None else agent.tools
        )
        outside_ceiling = sorted(set(selected_tools) - ceiling.allowed_tools)
        if outside_ceiling:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="manifest.tool_override_denied",
                    category=ErrorCategory.POLICY_DENIED,
                    message=f"tools exceed agent policy ceiling: {outside_ceiling}",
                )
            )
        route_id = agent.model_bindings.get("primary")
        route = resolved.model_routes.get(route_id, {})
        limits = route.get("limits", {})
        request_defaults = route.get("request", {})
        candidates = [
            value
            for value in (
                limits.get("context_window"),
                ceiling.max_input_tokens,
            )
            if value is not None
        ]
        context_budget = None
        if candidates:
            context_budget = ContextBudget(
                max_input_tokens=min(int(value) for value in candidates),
                reserve_output_tokens=int(
                    request_defaults.get("max_output_tokens")
                    or limits.get("max_output_tokens")
                    or ceiling.max_output_tokens
                    or 0
                ),
            )
        context_providers: tuple[ContextSegmentProvider, ...] = (
            RunMetadataContextProvider(),
        )
        if skill_loader is not None:
            context_providers = (
                *context_providers,
                AvailableSkillsContextProvider(skill_loader.catalog),
                ActiveSkillsContextProvider(skill_loader),
            )
        if memory_service is not None:
            context_providers = (
                *context_providers,
                MemoryContextSource(memory_service),
            )
        return AgentLoopEngine(
            runtime=self.runtime,
            model=model,
            tool_catalog=FilteredToolCatalog(tool_catalog, selected_tools),
            tool_executor=tool_executor,
            tool_policy=tool_policy,
            continuation_policy=continuation_policy,
            context_assembler=DefaultContextAssembler(
                developer_instructions=agent.instructions,
                providers=context_providers,
                budget=context_budget,
                reducer=(
                    self.context_components.create_reducer()
                    if context_budget is not None
                    else None
                ),
                estimator=self.context_components.token_estimator,
                history_reader=self.runtime.session_store,
            ),
        )
