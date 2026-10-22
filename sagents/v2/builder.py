"""Register implementations, select them through runtime, and build SAgents v2 Apps.
"""

from __future__ import annotations

from pathlib import Path
from sagents.v2.runtime.extensions.pool import ApplicationScopePool
from sagents.v2.runtime.extensions.scope import ExtensionScopeHandle
from sagents.v2.package.manifest.resolver import CompositionResolver

from sagents.v2.application import (
    SAgentApplication,
)
from sagents.v2.composition.assembler import ApplicationAssembler
from sagents.v2.composition.state import AssemblyState
from sagents.v2.composition.revision_store import AgentRevisionStore
from sagents.v2.composition.inputs import RuntimeInput
from sagents.v2.package.manifest.resolver import ResolvedSageManifest
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.package.manifest.runtime import RuntimeConfig
from sagents.v2.runtime.extensions import (
    ExtensionRegistration,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry


class SAgentBuilder:
    """Register implementations; runtime selects providers and their parameters.

    A host may supply a revision store to upgrade its own persisted snapshots.
    New package inputs always use the current manifest contract.
    """

    _scope_pool: ApplicationScopePool
    _shared_process_handles: tuple[ExtensionScopeHandle, ...]
    _model_resolver: CompositionResolver

    def __init__(self, *, revision_store: AgentRevisionStore | None = None) -> None:
        self._registry = builtin_extension_registry()
        self._state = AssemblyState()
        self._revision_store = revision_store

    def register(self, registration: ExtensionRegistration) -> "SAgentBuilder":
        self._registry.register(registration)
        return self

    def inventory(self) -> tuple[dict, ...]:
        return self._registry.inventory()

    async def _build_package(
        self,
        package: SageManifest | ResolvedSageManifest | str | Path,
        *,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        runtime: RuntimeConfig | dict | None = None,
    ) -> SAgentApplication:
        """Resolve one composition and open all provider scopes asynchronously."""

        runtime = RuntimeConfig.model_validate(runtime) if runtime is not None else None
        from sagents.v2.composition.resolution import _resolve_package
        _, package = _resolve_package(package, runtime=runtime, models=None)
        scope_handles = []
        try:
            return await ApplicationAssembler(
                self._state, self._registry,
                model_resolver=getattr(self, "_model_resolver", None),
                scope_pool=getattr(self, "_scope_pool", None),
                shared_process_handles=getattr(self, "_shared_process_handles", ()),
            ).assemble(
                package,
                tenant_id=tenant_id,
                agent_id=agent_id,
                scope_handles=scope_handles,
                runtime=runtime,
            )
        except BaseException as exc:
            for handle in reversed(scope_handles):
                try:
                    await handle.close()
                except BaseException as close_exc:
                    exc.add_note(f"scope rollback also failed: {close_exc}")
            raise

    async def build(
        self,
        *,
        tenant_id: str | None = None,
        runtime: RuntimeInput | None = None,
        runtime_config_text: str | None = None,
        models=None,
        models_config_text: str | None = None,
    ) -> SAgentApplication:
        """Create an App, then load Agent Packages with app.load_agent().

        """
        from copy import copy, deepcopy
        from sagents.v2.composition.inputs import runtime_input
        from sagents.v2.composition.defaults import default_runtime, effective_runtime
        from sagents.v2.composition.loaded_agents import LoadedAgents

        from sagents.v2.model.catalog import model_catalog_input
        models = model_catalog_input(
            models,
            config_text=models_config_text,
        )
        runtime = runtime_input(runtime, config_text=runtime_config_text)
        if runtime is None:
            runtime = default_runtime(self._state.session_root or ".runtime/sagents")
        runtime = effective_runtime(runtime)
        self._registry.validate_runtime(runtime)
        snapshot = copy(self)
        snapshot._state = copy(self._state)
        snapshot._state.runtime_skill_authorizations = runtime.runtime_skill_authorizations
        snapshot._state.manual_dispatcher_start = not runtime.start_workers
        snapshot._state.check_readiness = runtime.check_readiness
        store_selection = runtime.selections("session.store")
        state_root = runtime.state_root or (
            store_selection[0].config.get("root") if len(store_selection) == 1 else None
        ) or self._state.session_root or ".runtime/sagents"
        snapshot._state.session_root = Path(state_root).expanduser().resolve()
        snapshot._registry = deepcopy(self._registry)
        application = SAgentApplication._from_composition(
            agents={},
            entrypoint_agent_id=None,
            scope_handles=(),
            services={},
            adapters={},
            composition_hash="",
        )
        application._loaded_agents = LoadedAgents(
            application, snapshot, runtime, tenant_id, models
        )
        try:
            from sagents.v2.composition.bootstrap import initialize_process
            await initialize_process(application._loaded_agents)
            await application._loaded_agents.restore_pending()
            if runtime.start_workers:
                await application.service("execution.dispatcher").start()
        except BaseException as exc:
            try:
                await application.close()
            except BaseException as close_exc:
                exc.add_note(f"application rollback also failed: {close_exc}")
            raise
        from sagents.v2.runtime.observability import StructuredLogger
        StructuredLogger(application.service("observability.provider").logs, "sagents.application").info(
            "sagents.application.configured", "Sage Application configured",
            attributes={"composition_hash": application.composition_hash, "plugins": [
                {"capability": item.capability, "plugin": item.plugin_id, "version": item.plugin_version}
                for item in application.resolved_plan.providers]},
        )
        return application
