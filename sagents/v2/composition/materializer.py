"""Materialize scoped Agent capabilities on an existing process application."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import asynccontextmanager
from typing import Any
from weakref import WeakValueDictionary

from sagents.v2.agent.policy import (
    CompositeContinuationPolicy,
)
from sagents.v2.application import SAgentApplication
from sagents.v2.composition.contracts import (
    MaterializedAgentPorts,
    ResolvedApplicationPlan,
    ResolvedProviderBinding,
)
from sagents.v2.composition.identity import (
    _config_identity,
    _service_composition_identity,
)
from sagents.v2.composition.providers import open_provider
from sagents.v2.composition.resolution import (
    _merge_plugin_config,
    _selection,
    _supported_locked_config,
    _validate_declared_plugin_trust,
)
from sagents.v2.composition.resolution import _resolve_package as resolve_package
from sagents.v2.context import (
    ExtractiveConversationSummarizer,
    PersistentSummaryContextReducer,
    ReferenceContextUnitCompactor,
)
from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.memory import (
    DirectMemoryRecallQueryGenerator,
)
from sagents.v2.runtime.extensions import (
    ExtensionScope,
    ExtensionScopeContext,
    load_installed_extension,
    validate_extension_version,
)
from sagents.v2.package.manifest.runtime import CapabilitySelection, RuntimeConfig
from sagents.v2.skill.plugins.loading import SkillLoadingPlugin
from sagents.v2.tool.plugins.selection_llm import LLMToolSelectionPolicy
from sagents.v2.workspace import BareWorkspaceInitializer


class AgentMaterializer:
    """Rematerialize Agent/Run ports on a live process Application."""

    def __init__(
        self,
        *,
        host,
        process_root,
        extensions,
        process_plan: ResolvedApplicationPlan,
        summary_store,
        derived_state,
        process_model=None,
        models=None,
        default_tenant_id: str | None = None,
        deployment_profile: str = "controlled_host",
    ) -> None:
        self.host = host
        self.process_root = process_root
        self.extensions = extensions
        self.process_plan = process_plan
        self.summary_store = summary_store
        self.derived_state = derived_state
        self.models = models
        self.process_model = process_model
        self.default_tenant_id = default_tenant_id
        self.deployment_profile = deployment_profile
        self.application: SAgentApplication | None = None
        self._cache: dict[tuple[str, ...], tuple[Any, Any]] = {}
        self._cache_guard = None
        # Holders and waiters keep their lock alive; completed Run identities
        # must not accumulate in the process Application for its entire life.
        self._key_locks: WeakValueDictionary[tuple[str, ...], Any] = (
            WeakValueDictionary()
        )

    async def process_provider(
        self,
        capability: str,
        selection: CapabilitySelection,
        *,
        dependencies=None,
    ):
        if selection.scope not in {None, ExtensionScope.PROCESS}:
            raise ValueError("process_provider requires process scope")
        runtime = RuntimeConfig(
            deployment_profile=self.deployment_profile,
            capabilities={capability: selection},
        )
        return await self._port(
            runtime,
            (),
            capability=capability,
            default_plugin=selection.plugin,
            default_scope=ExtensionScope.PROCESS,
            scope_id=f"host-provider:{capability}",
            locked_config=dependencies,
            identities={},
            run_handles=[],
            selected_handles=[],
        )

    async def materialize_agent(
        self,
        package,
        *,
        runtime: RuntimeConfig | None = None,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        model: Any | None = None,
        tool_catalog: Any | None = None,
        tool_executor: Any | None = None,
        locked_configs: Mapping[str, Mapping[str, Any]] | None = None,
        cache_identities: Mapping[str, Any] | None = None,
    ) -> MaterializedAgentPorts:
        import asyncio

        if self._cache_guard is None:
            self._cache_guard = asyncio.Lock()
        tenant_id = tenant_id or self.default_tenant_id
        manifest, resolved = resolve_package(
            package, runtime=runtime, models=self.models
        )
        declarations = manifest.plugins if manifest is not None else resolved.plugins
        runtime = manifest.runtime if manifest is not None else resolved.runtime
        if runtime.deployment_profile != self.deployment_profile:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="runtime.deployment_profile_mismatch",
                    category=ErrorCategory.VALIDATION,
                    message=(
                        "materialized Agent deployment profile must match its owning "
                        "Application"
                    ),
                    safe_to_resume=False,
                    metadata={
                        "application_profile": self.deployment_profile,
                        "agent_profile": runtime.deployment_profile,
                    },
                )
            )
        built_in_only = (
            self.host.built_in_only or runtime.plugin_trust_policy == "built_in_only"
        )
        _validate_declared_plugin_trust(
            self.extensions,
            declarations,
            built_in_only=built_in_only,
        )
        for declaration in declarations:
            if not self.extensions.contains(declaration.id):
                self.extensions.register(
                    load_installed_extension(
                        declaration.id,
                        version_requirement=declaration.version,
                    )
                )
            validate_extension_version(
                self.extensions.get(declaration.id), declaration.version
            )
        selected_agent = (
            agent_id
            or resolved.entrypoint_agent
            or self.process_plan.entrypoint_agent_id
        )
        locks = {
            capability: dict(config)
            for capability, config in dict(locked_configs or {}).items()
        }
        identities = dict(cache_identities or {})
        effective_model = model if model is not None else self.process_model
        run_handles: list[Any] = []
        selected_handles: list[Any] = []
        async with self._close_run_handles_on_error(run_handles):
            summarizer_lock = dict(locks.get("context.summarizer") or {})
            if effective_model is not None and "model" not in summarizer_lock:
                summarizer_lock["model"] = effective_model
            summarizer = await self._port(
                runtime,
                declarations,
                capability="context.summarizer",
                default_plugin=(
                    ModelConversationSummarizer.plugin_id
                    if effective_model is not None
                    else ExtractiveConversationSummarizer.plugin_id
                ),
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-summarizer:{selected_agent}",
                locked_config=summarizer_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            unit_compactor = await self._port(
                runtime,
                declarations,
                capability="context.unit-compactor",
                default_plugin=ReferenceContextUnitCompactor.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-unit-compactor:{selected_agent}",
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            reducer_lock = {
                "store": self.summary_store,
                "summarizer": summarizer,
                "unit_compactor": unit_compactor,
                **dict(locks.get("context.reducer") or {}),
            }
            context_reducer = await self._port(
                runtime,
                declarations,
                capability="context.reducer",
                default_plugin=PersistentSummaryContextReducer.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-reducer:{selected_agent}",
                locked_config=reducer_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            skill_loading = await self._port(
                runtime,
                declarations,
                capability="skill.loading",
                default_plugin=SkillLoadingPlugin.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-skill-loading:{selected_agent}",
                locked_config=locks.get("skill.loading"),
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            tool_selection = await self._port(
                runtime,
                declarations,
                capability="tool.selection-policy",
                default_plugin=LLMToolSelectionPolicy.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-tool-selection:{selected_agent}",
                locked_config=dict(locks.get("tool.selection-policy") or {}),
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            continuation_lock = {}
            if effective_model is not None:
                continuation_lock["model"] = effective_model
            continuation_lock.update(dict(locks.get("agent.continuation-policy") or {}))
            continuation_scope = (
                ExtensionScope.RUN if run_id is not None else ExtensionScope.AGENT
            )
            continuation = await self._port(
                runtime,
                declarations,
                capability="agent.continuation-policy",
                default_plugin=CompositeContinuationPolicy.plugin_id,
                default_scope=continuation_scope,
                scope_id=(
                    f"materialize-continuation:{selected_agent}:{run_id or 'agent'}"
                ),
                locked_config=continuation_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
                run_id=run_id,
            )
            recall_lock = dict(locks.get("memory.recall-query") or {})
            if effective_model is not None and "model" not in recall_lock:
                recall_lock["model"] = effective_model
            memory_query = await self._port(
                runtime,
                declarations,
                capability="memory.recall-query",
                default_plugin=DirectMemoryRecallQueryGenerator.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-recall-query:{selected_agent}",
                locked_config=recall_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
            workspace_lock = dict(locks.get("workspace.initializer") or {})
            workspace_initializer = await self._port(
                runtime,
                declarations,
                capability="workspace.initializer",
                default_plugin=BareWorkspaceInitializer.plugin_id,
                default_scope=ExtensionScope.AGENT,
                scope_id=f"materialize-workspace:{selected_agent}",
                locked_config=workspace_lock,
                identities=identities,
                run_handles=run_handles,
                selected_handles=selected_handles,
                tenant_id=tenant_id,
                agent_id=selected_agent,
            )
        resolved_plan = self._materialized_plan(
            resolved,
            selected_agent,
            selected_handles,
            model=model,
            tool_catalog=tool_catalog,
            tool_executor=tool_executor,
        )
        return MaterializedAgentPorts(
            summarizer=summarizer,
            context_reducer=context_reducer,
            skill_loading=skill_loading,
            continuation_policy=continuation,
            tool_selection_policy=tool_selection,
            tool_catalog=tool_catalog,
            tool_executor=tool_executor,
            memory_query_generator=memory_query,
            workspace_initializer=workspace_initializer,
            resolved_plan=resolved_plan,
            scope_handles=tuple(run_handles),
        )

    @asynccontextmanager
    async def _close_run_handles_on_error(self, handles):
        try:
            yield
        except BaseException as exc:
            failed_handles = []
            for handle in reversed(handles):
                try:
                    await handle.close()
                except BaseException as close_exc:
                    failed_handles.append(handle)
                    exc.add_note(f"materialization rollback also failed: {close_exc}")
            if self.application is not None:
                for handle in reversed(failed_handles):
                    self.application.retain_scope(handle)
            handles.clear()
            raise

    async def _port(
        self,
        runtime,
        declarations,
        *,
        capability,
        default_plugin,
        default_scope=ExtensionScope.AGENT,
        scope_id: str,
        locked_config=None,
        identities,
        run_handles,
        selected_handles,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
    ):
        selection = _selection(runtime, capability)
        plugin_id = selection.plugin if selection is not None else default_plugin
        if capability == "agent.continuation-policy" and plugin_id in {
            "hybrid",
            "sage.agent.continuation.hybrid",
        }:
            plugin_id = "sage.agent.continuation.llm-judge"
        if capability == "tool.selection-policy" and plugin_id in {
            "hybrid",
            "sage.tool-selection.hybrid",
        }:
            plugin_id = LLMToolSelectionPolicy.plugin_id
        if (
            self.host.built_in_only or runtime.plugin_trust_policy == "built_in_only"
        ) and not self.extensions.is_trusted_builtin(plugin_id):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="extension.plugin_trust_policy_violation",
                    category=ErrorCategory.VALIDATION,
                    message=f"built_in_only policy rejected extension {plugin_id!r}",
                    safe_to_resume=False,
                    metadata={
                        "plugin_id": plugin_id,
                        "plugin_trust_policy": "built_in_only",
                    },
                )
            )
        config = {
            **dict(selection.config if selection is not None else {}),
        }
        config = _merge_plugin_config(declarations, plugin_id, config)
        config.update(
            _supported_locked_config(
                self.extensions, plugin_id, dict(locked_config or {})
            )
        )
        scope = (
            selection.scope
            if selection is not None and selection.scope is not None
            else default_scope
        )
        cacheable = scope != ExtensionScope.RUN
        identity = identities.get(capability)
        cache_tenant_id = (
            tenant_id
            if scope in {ExtensionScope.TENANT, ExtensionScope.AGENT}
            else None
        )
        cache_agent_id = agent_id if scope == ExtensionScope.AGENT else None
        cache_key = (
            capability,
            plugin_id,
            selection.name if selection is not None else "default",
            scope.value,
            scope_id,
            cache_tenant_id or "",
            cache_agent_id or "",
            _config_identity(identity if identity is not None else config),
        )
        async with await self._lock_for(cache_key):
            if cacheable and cache_key in self._cache:
                handle, value = self._cache[cache_key]
                selected_handles.append(handle)
                return value
            parent = self.process_root
            if scope == ExtensionScope.RUN:
                parent = await self._agent_parent(tenant_id, agent_id or "default")
            value, handle = await self._instantiate(
                plugin_id,
                config,
                capability,
                scope=scope,
                scope_id=scope_id,
                parent=parent,
                tenant_id=tenant_id,
                agent_id=agent_id,
                run_id=run_id,
                offer_name=selection.name if selection is not None else None,
            )
            if cacheable:
                self._cache[cache_key] = (handle, value)
                if self.application is not None:
                    self.application.retain_scope(handle)
            else:
                run_handles.append(handle)
            selected_handles.append(handle)
            return value

    async def _lock_for(self, cache_key: tuple[str, ...]):
        import asyncio

        if self._cache_guard is None:
            self._cache_guard = asyncio.Lock()
        async with self._cache_guard:
            lock = self._key_locks.get(cache_key)
            if lock is None:
                lock = asyncio.Lock()
                self._key_locks[cache_key] = lock
        return lock

    async def _agent_parent(self, tenant_id: str | None, agent_id: str):
        cache_key = ("__agent_parent__", tenant_id or "", agent_id)
        async with await self._lock_for(cache_key):
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached[0]
            handle = await self.host.open_scope(
                ExtensionScopeContext(
                    scope=ExtensionScope.AGENT,
                    scope_id=f"materialize-agent:{tenant_id or 'default'}:{agent_id}",
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                ),
                self.host.plan(()),
                parent=self.process_root,
            )
            self._cache[cache_key] = (handle, None)
            if self.application is not None:
                self.application.retain_scope(handle)
            return handle

    async def _instantiate(
        self,
        plugin_id: str,
        config: dict[str, Any],
        capability: str,
        *,
        scope: ExtensionScope,
        scope_id: str,
        parent,
        tenant_id: str | None,
        agent_id: str | None,
        run_id: str | None,
        offer_name: str | None = None,
    ):
        return await open_provider(
            self.host,
            self.extensions,
            parent,
            plugin_id,
            config,
            capability,
            scope=scope,
            scope_id=scope_id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            run_id=run_id,
            offer_name=offer_name,
        )

    def _materialized_plan(
        self,
        resolved,
        selected_agent: str,
        selected_handles,
        *,
        model,
        tool_catalog,
        tool_executor,
    ) -> ResolvedApplicationPlan:
        replaced_capabilities = {
            "agent.continuation-policy",
            "context.reducer",
            "context.summarizer",
            "context.unit-compactor",
            "memory.recall-query",
            "tool.selection-policy",
            "workspace.initializer",
        }
        if model is not None:
            replaced_capabilities.add("model.provider")
        if tool_catalog is not None:
            replaced_capabilities.add("tool.catalog")
        if tool_executor is not None:
            replaced_capabilities.add("tool.executor")
        bindings = {
            (value.capability, value.name, value.scope): value
            for value in self.process_plan.providers
            if value.capability not in replaced_capabilities
        }
        dependencies = set(self.process_plan.dependencies)

        def visit(handle) -> None:
            for ancestor in getattr(handle, "_owned_ancestors", ()):
                visit(ancestor)
            dependencies.update(getattr(handle.graph, "dependencies", ()))
            for started in getattr(handle, "_started", ()):
                descriptor = started.registration.descriptor
                for offer in descriptor.provides:
                    bindings[
                        (offer.capability, offer.name, handle.context.scope.value)
                    ] = ResolvedProviderBinding(
                        capability=offer.capability,
                        name=offer.name,
                        api_version=offer.api_version,
                        plugin_id=descriptor.plugin_id,
                        scope=handle.context.scope.value,
                        source="plugin",
                    )

        for handle in selected_handles:
            visit(handle)
        if model is not None:
            bindings[("model.provider", "default", "agent")] = ResolvedProviderBinding(
                capability="model.provider",
                name="default",
                api_version="2",
                plugin_id=None,
                scope="agent",
                source="host",
            )
        injected_scope = (
            "run"
            if any(
                handle.context.scope == ExtensionScope.RUN
                for handle in selected_handles
            )
            else "agent"
        )
        for capability, provider in (
            ("tool.catalog", tool_catalog),
            ("tool.executor", tool_executor),
        ):
            if provider is not None:
                bindings[(capability, "default", injected_scope)] = (
                    ResolvedProviderBinding(
                        capability=capability,
                        name="default",
                        api_version="2",
                        plugin_id=None,
                        scope=injected_scope,
                        source="host",
                    )
                )
        providers = tuple(sorted(bindings.values()))
        payload = {
            "process": self.process_plan.composition_hash,
            "manifest": resolved.manifest_hash,
            "scope_compositions": sorted(
                {handle.composition_hash for handle in selected_handles}
            ),
            "host_ports": {
                capability: _service_composition_identity(provider)
                for capability, provider in (
                    ("model.provider", model),
                    ("tool.catalog", tool_catalog),
                    ("tool.executor", tool_executor),
                )
                if provider is not None
            },
            "providers": [
                (value.capability, value.plugin_id, value.scope, value.source)
                for value in providers
            ],
        }
        composition_hash = (
            "sha256:"
            + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        )
        return ResolvedApplicationPlan(
            package_id=resolved.package_id,
            manifest_hash=resolved.manifest_hash,
            entrypoint_agent_id=selected_agent,
            providers=providers,
            dependencies=tuple(sorted(dependencies)),
            composition_hash=composition_hash,
        )
