from __future__ import annotations

from app.v2.desktop.backend.run_environment import catalog_agent_id

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any


from app.v2.desktop.backend.catalog import (
    DesktopCatalogStore,
    JsonDesktopCatalogStore,
)
from app.v2.desktop.backend.package import (
    DESKTOP_COMPONENT_DEFAULTS as _DESKTOP_COMPONENT_DEFAULTS,
    stable_component_id as _stable_component_id,
)
from app.v2.desktop.backend.session_index import JsonDesktopSessionIndex
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
    SessionStore,
    DerivedStateStore,
    FilesystemSessionStore,
)
from sagents.v2.runtime.session.migration import adopt_unowned_sessions
from sagents.v2.memory import MemoryService
from sagents.v2.session_memory import SessionMemoryService
from sagents.v2.skill import (
    SessionDerivedSkillActivationRepository,
)
from sagents.v2.runtime.extensions.official import builtin_extension_registry
from sagents.v2.runtime.observability import StructuredLogger
from app.v2.desktop.backend.composition import build_desktop_application
from app.v2.desktop.backend.rsi import DesktopRsiMixin
from app.v2.desktop.backend.catalog_service import DesktopCatalogServiceMixin
from app.v2.desktop.backend.observability import create_desktop_observability
from app.v2.desktop.backend.studio import DesktopStudioMixin, StudioStore
from app.v2.desktop.backend.openui import OpenUiParser, OpenUiStore, OpenUiProjector
from app.v2.desktop.backend.schemas import (
    AgentCreate as AgentCreate,
    AgentSettingsPatch as AgentSettingsPatch,
    ComponentSelectionRequest as ComponentSelectionRequest,
    DesktopProject as DesktopProject,
    DesktopRunRequest as DesktopRunRequest,
    DesktopV2Settings as DesktopV2Settings,
    ModelProviderCreate as ModelProviderCreate,
    ModelProviderPatch as ModelProviderPatch,
)
from app.v2.desktop.backend.run_context import (
    AgentRosterContextProvider as AgentRosterContextProvider,
)
from app.v2.desktop.backend.run_service import DesktopRunServiceMixin
from app.v2.desktop.backend.usage_analytics import (
    _start_run_user_text,
    _usage_percentile as _usage_percentile,
    build_usage_overview,
)
from app.v2.desktop.backend.workspace_service import DesktopWorkspaceServiceMixin


LOGGER = logging.getLogger(__name__)



class DesktopV2Service(
    DesktopRsiMixin,
    DesktopStudioMixin,
    DesktopCatalogServiceMixin,
    DesktopRunServiceMixin,
    DesktopWorkspaceServiceMixin,
):
    def __init__(
        self,
        root: Path | None = None,
        *,
        catalog: DesktopCatalogStore | None = None,
        session_store: SessionStore | None = None,
        derived_state_store: DerivedStateStore | None = None,
        observability=None,
        max_concurrent_model_calls: int = 8,
        max_waiting_model_calls: int = 128,
        model_queue_timeout_seconds: float = 60,
        sidecar_port: int | None = None,
        sidecar_auth_token: str | None = None,
        extensions=(),
        runtime=None,
    ) -> None:
        """Create one process service. Injected stores are borrowed, never closed.

        When borrowing an authoritative store, pass a derived_state_store too if
        derived state should be durable; otherwise the builder provides memory
        derived state. Close this service before closing host-owned stores.
        """
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
        self._initialize_rsi()
        self.studio_store = StudioStore(self.runtime_root / "studios.sqlite3")
        self.openui_store = OpenUiStore(self.runtime_root / "openui.sqlite3")
        self.openui_parser = OpenUiParser()
        self.extensions = builtin_extension_registry()
        self._host_runtime = runtime
        self._host_extensions = tuple(extensions)
        for registration in self._host_extensions:
            self.extensions.register(registration)
        self._workspace_initializations: dict[tuple[str, str, str], Path] = {}
        self._workspace_initialization_lock = asyncio.Lock()
        from sagents.v2.model.plugins.concurrency_budget import ModelConcurrencyBudget

        self.model_budget = ModelConcurrencyBudget(
            max_concurrent_model_calls, max_waiting=max_waiting_model_calls,
            wait_timeout_seconds=model_queue_timeout_seconds,
        )
        from app.v2.desktop.backend.model_providers import DesktopModelProviders

        self.model_providers = DesktopModelProviders(self.model_budget)
        self._last_run_plan = None
        self._mcp_plugin_cache: dict[tuple[str, str], Any] = {}
        self._owned_observability = create_desktop_observability(self.runtime_root) if observability is None else None
        self.observability = observability if observability is not None else self._owned_observability
        self.observability_plugin_id = self.observability.plugin_id
        self.log_sink = self.observability.logs
        self.diagnostics = self.observability.diagnostics
        self.logger = StructuredLogger(self.log_sink, "desktop.service")
        self.logger.info(
            "service.initializing",
            "Desktop v2 service is initializing",
            attributes={"root": str(self.root), "log_plugin": self.observability_plugin_id},
        )
        owner_adoption = (
            adopt_unowned_sessions(
                self.runtime_root,
                principal_id="default_user",
            )
            if session_store is None
            else None
        )
        if owner_adoption is not None and owner_adoption.adopted_sessions:
            self.logger.info(
                "session.legacy_owner_adopted",
                "Assigned the local Desktop user to legacy unowned Sessions",
                attributes={"sessions": owner_adoption.adopted_sessions},
            )
        settings = self._read_settings_sync()
        self.session_plugin_id = _DESKTOP_COMPONENT_DEFAULTS["session.store"]
        self._owns_session_store = session_store is None
        self.session_store = (
            session_store
            if session_store is not None
            else FilesystemSessionStore(self.runtime_root)
        )
        self._owned_session_store = self.session_store if self._owns_session_store else None
        self._derived_state_store = derived_state_store
        self._run_environments = {}
        self.runtime = HarnessRuntime(self.session_store)
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
        self.session_access = None
        self.delegation_limiter = None
        self.dynamic_agent_roster = None
        self.summary_store = None
        self.activations = None
        self.memory_provider = None
        self.memory_service = None
        self.session_memory_provider = None
        self.session_memory_service = None
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
        self._settings_update_lock = asyncio.Lock()
        self._agent_update_lock = asyncio.Lock()
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
            from .sdk_plugins import desktop_registrations
            application = await build_desktop_application(
                session_root=self.runtime_root,
                workspace=workspace,
                observability=self.observability,
                session_store=self.session_store,
                derived_state_store=(
                    self._derived_state_store
                    if self._derived_state_store is not None
                    else self.session_store
                    if self._owns_session_store
                    else None
                ),
                component_selections=settings.component_selections,
                component_configs=settings.component_configs,
                language=language,
                runtime=self._host_runtime,
                extensions=(*self._host_extensions, *desktop_registrations(self)),
                defer_recovery=True,
            )
            try:
                self.application = application
                self._bind_process_runtime()
                await self.dispatcher.start()
                self._start_studio_delivery_worker()
            except BaseException:
                self.application = None
                await application.close()
                raise

    def _bind_process_runtime(self) -> None:
        application = self.application
        self.runtime = application.runtime
        self.session_store = application.service("session.store")
        self.scheduler = application.service("execution.scheduler")
        self.dispatcher = application.service("execution.dispatcher")
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
        self.observability = application.service("observability.provider")
        self.observability_plugin_id = self.observability.plugin_id
        self.log_sink = self.observability.logs
        self.diagnostics = self.observability.diagnostics
        self.logger = StructuredLogger(self.log_sink, "desktop.service")

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
        return workspace

    async def has_background_work(self) -> bool:
        """Keep headless execution alive, including delayed/recoverable Runs."""
        return self.rsi_active or bool(await self.session_store.list_dispatchable_runs())

    async def close(self) -> None:
        async with self._start_lock:
            if self._closed:
                return
            await self._close_once()
            self._closed = True

    async def _close_once(self) -> None:
        await self.openui_parser.close()
        await self._close_rsi()
        await self._stop_studio_delivery_worker()
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
        if self._owned_session_store is not None:
            await self._owned_session_store.close()
        self._run_environments.clear()
        self.model_providers.clear()
        self._workspace_initializations.clear()
        self.logger.info("service.closed", "Desktop v2 service closed")
        if self._owned_observability is not None:
            await self._owned_observability.close()

    async def _authorized_indexed_sessions(
        self,
        user_id: str,
        *,
        skipped_unreadable_sessions: set[str] | None = None,
    ):
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
                if exc.info.category == ErrorCategory.CORRUPT_STATE:
                    if skipped_unreadable_sessions is not None:
                        skipped_unreadable_sessions.add(value.session_id)
                    self.logger.warning(
                        "session.index_entry_skipped",
                        "Skipped an unreadable indexed Session",
                        attributes={
                            "session_id": value.session_id,
                            "error_code": exc.info.code,
                            "error": exc.info.message,
                        },
                    )
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
                "format_version": getattr(self.diagnostics, "format_version", ""),
                "path": str(getattr(self.diagnostics, "root", "")),
                "authoritative": False,
            },
            "logs": {
                "format_version": self.log_sink.format_version,
                "plugin_id": self.observability_plugin_id,
                "path": str(getattr(self.log_sink, "path", "")),
                "authoritative": False,
            },
        }

    async def openui_surfaces(self, session_id: str, user_id: str):
        await self.start()
        context = self._context(user_id)
        runs = await self.session_access.list_session_runs(session_id, context)
        # Rebuild from durable completed messages if a stream had no subscriber.
        for run in runs:
            projector = OpenUiProjector(self, user_id)
            after = 0
            while True:
                events = await self.session_access.read_events(run.run_id, context, after_sequence=after, limit=500)
                if not events:
                    break
                for event in events:
                    if event.type == "message.completed":
                        await projector.project(event)
                after = events[-1].run_sequence
                if len(events) < 500:
                    break
        values = self.openui_store.list(user_id, session_id)
        for surface in values:
            message, index = surface["surface_key"].rsplit(":", 1)
            surface.update(message_id=message, block_index=int(index), complete=True)
        return values

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
                    "agent_id": catalog_agent_id(command),
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
                    "agent_id": catalog_agent_id(command),
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
        result = await self.application.entrypoint().propose_session_commit(
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
        result = await self.application.entrypoint().publish_session_commit(
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
        result = await self.application.entrypoint().reject_session_commit(
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
