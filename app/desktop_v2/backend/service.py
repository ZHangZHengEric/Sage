from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any


from app.desktop_v2.backend.catalog import (
    DesktopCatalogStore,
    JsonDesktopCatalogStore,
)
from app.desktop_v2.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS as _DESKTOP_COMPONENT_DEFAULTS,
    stable_component_id as _stable_component_id,
)
from app.desktop_v2.backend.session_index import JsonDesktopSessionIndex
from sagents.v2 import SAgent
from sagents.v2.agent.multi_agent import (
    DelegationConcurrencyLimiter,
    SessionDynamicAgentRoster,
)
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionMergeStrategy,
)
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import (
    FilesystemSessionStore,
    LeaseFencedSessionStore,
)
from sagents.v2.runtime.session.migration import adopt_unowned_sessions
from sagents.v2.memory import MemoryService
from sagents.v2.session_memory import SessionMemoryService
from sagents.v2.runtime.execution.sandbox import (
    SandboxGrantIssuer,
)
from sagents.v2.skill import (
    SessionDerivedSkillActivationRepository,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.observability import (
    FilesystemDiagnosticSink,
    LogSink,
    StructuredLogger,
)
from app.desktop_v2.backend.bindings import DesktopExecutionBindingProvider
from app.desktop_v2.backend.composition import build_desktop_application
from app.desktop_v2.backend.catalog_service import DesktopCatalogServiceMixin
from app.desktop_v2.backend.observability import create_desktop_log_sink
from app.desktop_v2.backend.schemas import (
    AgentCreate as AgentCreate,
    AgentSettingsPatch as AgentSettingsPatch,
    ComponentSelectionRequest as ComponentSelectionRequest,
    DesktopProject as DesktopProject,
    DesktopRunRequest as DesktopRunRequest,
    DesktopV2Settings as DesktopV2Settings,
    ModelProviderCreate as ModelProviderCreate,
    ModelProviderPatch as ModelProviderPatch,
)
from app.desktop_v2.backend.run_lifecycle import (
    DesktopDriver as _DesktopDriver,
    DesktopRunResources as _DesktopRunResources,  # noqa: F401 - compatibility export
)
from app.desktop_v2.backend.run_context import (
    AgentRosterContextProvider as AgentRosterContextProvider,
)
from app.desktop_v2.backend.run_service import DesktopRunServiceMixin
from app.desktop_v2.backend.runtime_config import (
    _agent_memory_enabled,
)
from app.desktop_v2.backend.usage_analytics import (
    _start_run_user_text,
    _usage_percentile as _usage_percentile,
    build_usage_overview,
)
from app.desktop_v2.backend.workspace_service import DesktopWorkspaceServiceMixin


LOGGER = logging.getLogger(__name__)

class _DesktopRecoveryAgent:
    """Recompose a Desktop driver for a durable Run with lost scheduler work."""

    def __init__(self, service: "DesktopV2Service") -> None:
        self.service = service
        self.runtime = service.driver_runtime

    def _ensure_execution(self, run_id, context, *, resume):
        return asyncio.create_task(
            self._execute(run_id, context, resume=resume),
            name=f"desktop-recovery:{run_id}",
        )

    async def _compose_driver(self, run_id, context):
        command = await self.service.session_store.get_start_command(run_id)
        user_id = context.actor.principal_id
        agent = await self.service._agent_for_command(command, user_id)
        provider = await self.service._provider_for_command(command, agent, user_id)
        workspace = await self.service.workspace_root(
            command.config.metadata.get("workspace_id"), command.agent_id
        )

        async def build():
            return await self.service._build_loop(
                agent=agent,
                provider=provider,
                workspace=workspace,
                preferred_skills=tuple(
                    command.config.metadata.get("preferred_skills") or ()
                ),
                approval_mode=str(
                    command.config.metadata.get("approval_mode") or "high_risk"
                ),
                invocation_mode=command.invocation_mode or "normal",
                session_id=(await self.runtime.get_run(run_id)).session_id,
                run_id=run_id,
                resolved_spec_hash=command.resolved_spec_hash,
                component_snapshot=command.config.metadata.get("runtime_components"),
            )

        driver = _DesktopDriver(self.service, None, workspace, None, lazy_builder=build)
        self.service._drivers[run_id] = driver
        return driver, agent

    async def _execute(self, run_id, context, *, resume):
        driver, agent = await self._compose_driver(run_id, context)
        memory_enabled = _agent_memory_enabled(
            agent,
            self.service.memory_plugin_id,
            self.service.session_memory_plugin_id,
        )
        facade = SAgent(
            runtime=self.runtime,
            driver_factory=lambda _: driver,
            memory_service=(self.service.memory_service if memory_enabled else None),
            memory_scope={"recall": False, "auto_write": memory_enabled},
        )
        try:
            execution = facade._ensure_execution(run_id, context, resume=resume)
            return await execution
        finally:
            if self.service._drivers.get(run_id) is driver:
                self.service._drivers.pop(run_id, None)

    async def _recover_interrupted_run(self, run_id, context):
        driver, _ = await self._compose_driver(run_id, context)
        try:
            await driver._ensure_composed()
            return await driver.loop.recover_interrupted(run_id, context)
        finally:
            await driver.close()
            if self.service._drivers.get(run_id) is driver:
                self.service._drivers.pop(run_id, None)

    async def _fail_driver_crash(self, run_id, error, context):
        facade = SAgent(runtime=self.runtime, driver_factory=lambda _: None)
        return await facade._fail_driver_crash(run_id, error, context)


class DesktopV2Service(
    DesktopCatalogServiceMixin,
    DesktopRunServiceMixin,
    DesktopWorkspaceServiceMixin,
):
    def __init__(
        self,
        root: Path | None = None,
        *,
        catalog: DesktopCatalogStore | None = None,
        log_sink: LogSink | None = None,
        log_plugin_id: str | None = None,
        sidecar_port: int | None = None,
        sidecar_auth_token: str | None = None,
    ) -> None:
        if sidecar_auth_token is not None and not sidecar_auth_token.strip():
            raise ValueError("Desktop sidecar auth token must not be empty")
        self.root = (root or Path.home() / "sage").resolve()
        self.sidecar_port = sidecar_port
        self.sidecar_auth_token = sidecar_auth_token
        self.root.mkdir(parents=True, exist_ok=True)
        self.agent_workspace = self.root / "agent_workspace"
        self.runtime_root = self.root / "runtime"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.runtime_root / "settings.json"
        self.extensions = builtin_extension_registry()
        self._workspace_initializations: dict[tuple[str, str, str], Path] = {}
        self._workspace_initialization_lock = asyncio.Lock()
        self._sandbox_grant_issuer = SandboxGrantIssuer()
        self._host_model_providers: dict[tuple[Any, ...], Any] = {}
        self._sandbox_providers: dict[str, Any] = {}
        self._last_run_plan = None
        if log_sink is None:
            self._owns_log_sink = True
            self.log_plugin_id, self.log_sink = create_desktop_log_sink(
                self.runtime_root
            )
        else:
            self._owns_log_sink = False
            self.log_plugin_id = log_plugin_id or "injected"
            self.log_sink = log_sink
        self.logger = StructuredLogger(self.log_sink, "desktop.service")
        self.logger.info(
            "service.initializing",
            "Desktop v2 service is initializing",
            attributes={"root": str(self.root), "log_plugin": self.log_plugin_id},
        )
        owner_adoption = adopt_unowned_sessions(
            self.runtime_root,
            principal_id="default_user",
        )
        if owner_adoption.adopted_sessions:
            self.logger.info(
                "session.legacy_owner_adopted",
                "Assigned the local Desktop user to legacy unowned Sessions",
                attributes={"sessions": owner_adoption.adopted_sessions},
            )
        settings = self._read_settings_sync()
        self.session_plugin_id = _DESKTOP_COMPONENT_DEFAULTS["session.store"]
        self.session_store = FilesystemSessionStore(self.runtime_root)
        self.runtime = HarnessRuntime(self.session_store)
        self.diagnostic_plugin_id = _DESKTOP_COMPONENT_DEFAULTS[
            "observability.diagnostic-sink"
        ]
        self.diagnostics = FilesystemDiagnosticSink(
            self.runtime_root / "sessions",
            legacy_root=self.runtime_root / "diagnostics",
        )
        self.summary_store_plugin_id = _stable_component_id(
            "context.summary-store",
            _DESKTOP_COMPONENT_DEFAULTS["context.summary-store"],
        )
        self.memory_plugin_id = _stable_component_id(
            "memory.provider",
            settings.component_selections.get(
                "memory.provider", _DESKTOP_COMPONENT_DEFAULTS["memory.provider"]
            ),
        )
        self.session_memory_plugin_id = _stable_component_id(
            "session-memory.provider",
            settings.component_selections.get(
                "session-memory.provider",
                _DESKTOP_COMPONENT_DEFAULTS["session-memory.provider"],
            ),
        )
        self.application = None
        self.scheduler = None
        self.dispatcher = None
        self.driver_session_store = None
        self.driver_runtime = None
        self.session_access = None
        self.delegation_limiter = None
        self.dynamic_agent_roster = None
        self.summary_store = None
        self.activations = None
        self.memory_provider = None
        self.memory_service = None
        self.session_memory_provider = None
        self.session_memory_service = None
        self.execution_binding_provider = None
        self._start_lock = asyncio.Lock()
        self._closed = False
        self.session_index = JsonDesktopSessionIndex(
            self.runtime_root / "session-index.json"
        )
        self.catalog = catalog or JsonDesktopCatalogStore(
            self.runtime_root / "desktop-catalog.json"
        )
        self.skill_root = self.root / "skills"
        self.skill_root.mkdir(parents=True, exist_ok=True)
        self._settings_lock = asyncio.Lock()
        self._drivers: dict[str, _DesktopDriver] = {}
        self._run_observers: dict[str, asyncio.Task] = {}
        self._application_close_tasks: set[asyncio.Task] = set()
        self._sandbox_cleanup_tasks: set[asyncio.Task] = set()
        self.logger.info(
            "service.initialized",
            "Desktop v2 service initialized",
            attributes={
                "log_path": str(getattr(self.log_sink, "path", "")),
                "diagnostics_path": str(getattr(self.diagnostics, "root", "")),
                "memory_plugin": self.memory_plugin_id,
            },
        )

    async def start(self) -> None:
        """Build the process Application once through SAgentBuilder."""

        async with self._start_lock:
            if self._closed:
                raise RuntimeError("Desktop v2 service is closed")
            if self.application is not None:
                return
            settings = self._read_settings_sync()
            language = "en" if settings.language == "system" else settings.language
            workspace = self._agent_workspace_path(settings.agent_workspace_path)
            execution_binding_provider = DesktopExecutionBindingProvider(
                workspace,
                issuer=self._sandbox_grant_issuer,
                private_workspace_root=self.runtime_root / "private-workspaces",
            )
            application = await build_desktop_application(
                session_root=self.runtime_root,
                workspace=workspace,
                log_sink=self.log_sink,
                diagnostic_sink=self.diagnostics,
                session_store=self.session_store,
                derived_state_store=self.session_store,
                component_selections=settings.component_selections,
                component_configs=settings.component_configs,
                language=language,
                bindings=execution_binding_provider,
            )
            try:
                self.execution_binding_provider = execution_binding_provider
                self.application = application
                self._bind_process_runtime()
            except BaseException:
                self.execution_binding_provider = None
                self.application = None
                await application.close()
                await execution_binding_provider.close()
                raise

    def _bind_process_runtime(self) -> None:
        application = self.application
        self.scheduler = application.service("execution.scheduler")
        self.dispatcher = application.service("execution.dispatcher")
        self.dispatcher.attach_recovery_agent(_DesktopRecoveryAgent(self), replace=True)
        self.driver_session_store = LeaseFencedSessionStore(
            self.session_store, self.scheduler
        )
        self.driver_runtime = HarnessRuntime(self.driver_session_store)
        self.session_access = application.service("session.access")
        self.delegation_limiter = DelegationConcurrencyLimiter(
            max_concurrency=8,
            max_per_tenant=2,
        )
        derived_state = application.service("derived-state.store")
        self.dynamic_agent_roster = SessionDynamicAgentRoster(
            self.session_store, derived_state
        )
        self.summary_store = application.service("context.summary-store")
        self.activations = SessionDerivedSkillActivationRepository(
            derived_state,
            self._session_id_for_run,
        )
        self.memory_provider = application.service("memory.provider")
        self.memory_service = MemoryService(
            self.memory_provider,
            scope_mode="agent",
            on_error=self._log_memory_error,
        )
        self.session_memory_provider = application.service("session-memory.provider")
        self.session_memory_service = SessionMemoryService(self.session_memory_provider)
        self.summary_store_plugin_id = self._plan_plugin_id(
            "context.summary-store", self.summary_store_plugin_id
        )
        self.memory_plugin_id = self._plan_plugin_id(
            "memory.provider", self.memory_plugin_id
        )
        self.session_memory_plugin_id = self._plan_plugin_id(
            "session-memory.provider", self.session_memory_plugin_id
        )
        self.diagnostic_plugin_id = self._plan_plugin_id(
            "observability.diagnostic-sink", self.diagnostic_plugin_id
        )

    def _plan_plugin_id(self, capability: str, fallback: str) -> str:
        if self.application is None:
            return fallback
        for provider in self.application.resolved_plan.providers:
            if provider.capability == capability and provider.plugin_id:
                return provider.plugin_id
        return fallback

    async def _log_memory_error(self, error: Exception) -> None:
        self.logger.exception(
            "memory.ingestion_failed",
            "Committed Run memory ingestion failed",
            error,
        )

    async def initialize_agent_workspace(self) -> Path:
        await self.start()
        settings = await self.get_settings()
        workspace = await self._ensure_agent_workspace(
            settings.agent_workspace_path,
            component_selections=settings.component_selections,
            language=settings.language,
        )
        await self._recover_pending_sandbox_cleanups()
        return workspace

    async def close(self) -> None:
        async with self._start_lock:
            if self._closed:
                return
            await self._close_once()
            self._closed = True

    async def _close_once(self) -> None:
        observers = tuple(self._run_observers.values())
        self._run_observers.clear()
        for task in observers:
            task.cancel()
        if observers:
            await asyncio.gather(*observers, return_exceptions=True)
        cleanup_tasks = tuple(self._sandbox_cleanup_tasks)
        for task in cleanup_tasks:
            task.cancel()
        if cleanup_tasks:
            await asyncio.gather(*cleanup_tasks, return_exceptions=True)
        if self.application is not None:
            await self.application.close()
            self.application = None
        await asyncio.sleep(0)
        close_tasks = tuple(self._application_close_tasks)
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        drivers = tuple(self._drivers.items())
        if drivers:
            results = await asyncio.gather(
                *(driver.close_binding() for _, driver in drivers),
                return_exceptions=True,
            )
            close_errors = []
            for (run_id, driver), result in zip(drivers, results, strict=True):
                if isinstance(result, BaseException):
                    close_errors.append(result)
                elif self._drivers.get(run_id) is driver:
                    self._drivers.pop(run_id, None)
            if close_errors:
                raise RuntimeError(
                    f"{len(close_errors)} Desktop Run driver(s) failed to close"
                ) from close_errors[0]
        if self.execution_binding_provider is not None:
            await self.execution_binding_provider.close()
            self.execution_binding_provider = None
        await self.session_store.close()
        self._host_model_providers.clear()
        self._sandbox_providers.clear()
        self._workspace_initializations.clear()
        self.logger.info("service.closed", "Desktop v2 service closed")
        if self._owns_log_sink:
            self.log_sink.close()

    async def _authorized_indexed_sessions(self, user_id: str):
        await self.start()
        context = self._context(user_id)
        visible = []
        for value in await self.session_index.list():
            try:
                await self.session_access.get_session(value.session_id, context)
            except SageV2Error as exc:
                if (
                    exc.info.category == ErrorCategory.AUTHORIZATION
                    or exc.info.code
                    in {
                        "session.not_found",
                        "session_not_found",
                    }
                ):
                    continue
                raise
            visible.append(value)
        return tuple(visible)

    async def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        values = await self._authorized_indexed_sessions(user_id)
        return [value.model_dump(mode="json") for value in values]

    async def usage_overview(
        self,
        user_id: str,
        *,
        days: int = 30,
        timezone_offset_minutes: int = 0,
    ) -> dict[str, Any]:
        return await build_usage_overview(
            self,
            user_id,
            days=days,
            timezone_offset_minutes=timezone_offset_minutes,
        )

    async def delete_session(self, session_id: str, user_id: str) -> None:
        await self.start()
        context = self._context(user_id)
        deleted_session_ids = {session_id}
        try:
            descendants = await self.session_access.list_descendant_sessions(
                session_id, context
            )
            deleted_session_ids.update(value.session_id for value in descendants)
            await self.session_access.delete_session(session_id, context)
        except SageV2Error as exc:
            if exc.info.code != "session.not_found":
                raise
            self.logger.info(
                "session.delete.already_absent",
                "Authoritative Session state was already absent; continuing cleanup",
                session_id=session_id,
            )
        try:
            await self.session_index.remove_many(deleted_session_ids)
        except Exception:
            LOGGER.exception(
                "Desktop Session tree index removal failed for %s", session_id
            )

    async def session_snapshot(self, session_id: str, user_id: str) -> dict[str, Any]:
        await self.start()
        context = self._context(user_id)
        session = await self.session_access.get_session(session_id, context)
        runs = await self.session_access.list_session_runs(session_id, context)
        proposals = await self.session_access.list_session_commit_proposals(
            session_id, context
        )
        return {
            "session": session.model_dump(mode="json"),
            "runs": [value.model_dump(mode="json") for value in runs],
            "commit_proposals": [value.model_dump(mode="json") for value in proposals],
            "diagnostics": {
                "format_version": self.diagnostics.format_version,
                "path": str(self.diagnostics.root),
                "authoritative": False,
            },
            "logs": {
                "format_version": self.log_sink.format_version,
                "plugin_id": self.log_plugin_id,
                "path": str(getattr(self.log_sink, "path", "")),
                "authoritative": False,
            },
        }

    async def session_runs(self, session_id: str, user_id: str) -> list[dict[str, Any]]:
        await self.start()
        values = await self.session_access.list_session_runs(
            session_id, self._context(user_id)
        )
        return [value.model_dump(mode="json") for value in values]

    async def session_tree(self, session_id: str, user_id: str) -> list[dict[str, Any]]:
        """Project the authoritative descendant tree for presentation clients."""

        await self.start()
        context = self._context(user_id)
        descendants = await self.session_access.list_descendant_sessions(
            session_id, context
        )
        nodes: list[dict[str, Any]] = []
        for session in descendants:
            runs = await self.session_access.list_session_runs(
                session.session_id, context
            )
            if not runs:
                continue
            run = runs[-1]
            command = await self.session_access.get_start_command(run.run_id, context)
            metadata = command.config.metadata
            nodes.append(
                {
                    "session": session.model_dump(mode="json"),
                    "run": run.model_dump(mode="json"),
                    "agent_id": command.agent_id,
                    "parent_run_id": command.parent_run_id
                    or metadata.get("fork_source_run_id"),
                    "parent_tool_call_id": str(
                        metadata.get("parent_tool_call_id") or ""
                    ),
                    "invocation_mode": command.invocation_mode,
                    "task_name": str(metadata.get("task_name") or ""),
                    "task": _start_run_user_text(command),
                    "original_task": str(
                        metadata.get("original_task") or metadata.get("task") or ""
                    ),
                }
            )
        return nodes

    async def subscribe_session_tree(
        self, session_id: str, user_id: str
    ) -> AsyncIterator[str]:
        """Multiplex descendant Run logs while preserving their own cursors.

        This is the v2 equivalent of v1's child chunks on the parent stream:
        clients consume one stream, then demultiplex by ``session_id``. Child
        events remain authoritative only in their own Session/Run logs.
        """

        await self.start()
        context = self._context(user_id)
        async for observation in self.session_access.subscribe_session_tree(
            session_id, context, include_root=False
        ):
            command = observation.start_command
            metadata = command.config.metadata
            if observation.kind == "session.discovered":
                value = {
                    "kind": observation.kind,
                    "session": observation.session.model_dump(mode="json"),
                    "run": observation.run.model_dump(mode="json"),
                    "agent_id": command.agent_id,
                    "parent_run_id": command.parent_run_id
                    or metadata.get("fork_source_run_id"),
                    "parent_tool_call_id": str(
                        metadata.get("parent_tool_call_id") or ""
                    ),
                    "invocation_mode": command.invocation_mode,
                    "task_name": str(metadata.get("task_name") or ""),
                    "task": _start_run_user_text(command),
                    "original_task": str(
                        metadata.get("original_task") or metadata.get("task") or ""
                    ),
                }
            else:
                value = {
                    "kind": observation.kind,
                    "session_id": observation.session.session_id,
                    "parent_session_id": observation.session.parent_session_id,
                    "run_id": observation.run.run_id,
                    "event": observation.event.model_dump(mode="json"),
                }
            yield json.dumps(value, ensure_ascii=False) + "\n"

    async def session_commit_proposals(
        self, session_id: str, user_id: str
    ) -> list[dict[str, Any]]:
        await self.start()
        values = await self.session_access.list_session_commit_proposals(
            session_id, self._context(user_id)
        )
        return [value.model_dump(mode="json") for value in values]

    async def propose_session_commit(self, run_id: str, user_id: str):
        await self.start()
        context = self._context(user_id)
        run = await self.session_access.get_run(run_id, context)
        result = await self.runtime.propose_session_commit(
            ProposeSessionCommit(
                run_id=run_id,
                expected_run_revision=run.revision,
                idempotency_key=new_id("session_commit_propose"),
            ),
            context,
        )
        await self._index_session(run.session_id)
        return result

    async def publish_session_commit(
        self,
        proposal_id: str,
        merge_strategy: SessionMergeStrategy,
        user_id: str,
    ):
        await self.start()
        context = self._context(user_id)
        proposal = await self.session_access.get_session_commit_proposal(
            proposal_id, context
        )
        session = await self.session_access.get_session(proposal.session_id, context)
        result = await self.runtime.publish_session_commit(
            PublishSessionCommit(
                proposal_id=proposal_id,
                expected_proposal_revision=proposal.revision,
                expected_session_revision=session.revision,
                merge_strategy=merge_strategy,
                idempotency_key=new_id("session_commit_publish"),
            ),
            context,
        )
        await self._index_session(proposal.session_id)
        return result

    async def reject_session_commit(self, proposal_id: str, reason: str, user_id: str):
        await self.start()
        context = self._context(user_id)
        proposal = await self.session_access.get_session_commit_proposal(
            proposal_id, context
        )
        session = await self.session_access.get_session(proposal.session_id, context)
        result = await self.runtime.reject_session_commit(
            RejectSessionCommit(
                proposal_id=proposal_id,
                expected_proposal_revision=proposal.revision,
                expected_session_revision=session.revision,
                reason=reason,
                idempotency_key=new_id("session_commit_reject"),
            ),
            context,
        )
        await self._index_session(proposal.session_id)
        return result

    async def session_events(
        self,
        session_id: str,
        user_id: str,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        await self.start()
        values = await self.session_access.read_session_events(
            session_id,
            self._context(user_id),
            after_sequence=after_sequence,
            limit=limit,
        )
        return [value.model_dump(mode="json") for value in values]

    async def list_llm_requests(
        self, session_id: str, user_id: str, run_id: str | None = None
    ) -> list[dict[str, Any]]:
        await self.start()
        context = self._context(user_id)
        await self.session_access.get_session(session_id, context)
        if run_id is not None:
            run = await self.session_access.get_run(run_id, context)
            if run.session_id != session_id:
                raise ValueError(f"run {run_id} does not belong to {session_id}")
        return list(
            await self.diagnostics.list_model_requests(
                session_id=session_id,
                run_id=run_id,
            )
        )

    async def get_llm_request(
        self, session_id: str, run_id: str, request_id: str, user_id: str
    ) -> dict[str, Any]:
        await self.start()
        run = await self.session_access.get_run(run_id, self._context(user_id))
        if run.session_id != session_id:
            raise ValueError(f"run {run_id} does not belong to {session_id}")
        return await self.diagnostics.get_model_request(
            session_id=session_id,
            run_id=run_id,
            request_id=request_id,
        )
