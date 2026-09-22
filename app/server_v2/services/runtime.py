from __future__ import annotations

import asyncio
import logging
from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
    TraceContext,
)
from sagents.v2.contracts.run_state import EventCursor, RunState, TERMINAL_RUN_STATES
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.model.provider import ModelProvider
from sagents.v2.runtime.observability import StructuredLogger, structured_log_context

from app.server_v2.agui.mapping import to_start_run, validate_agui_id
from app.server_v2.agui.sse import (
    canonical_agui_sse,
    frame_to_agui_event,
    single_error_sse,
)
from app.server_v2.core.errors import ServerV2Error, map_sage_error
from app.server_v2.core.observability.context import get_request_id
from app.server_v2.core.settings import ServerV2Settings
from app.server_v2.domain.catalog import enabled_mcp_servers, require_agent
from app.server_v2.domain.threads import resolve_thread_agent_id
from app.server_v2.services.composition import composition_metadata
from app.server_v2.services.mcp import McpPluginCache
from app.server_v2.services.models import (
    HostModelProvider,
    bind_model_user,
    reset_model_user,
)
from app.server_v2.services.official import install_sandbox
from app.server_v2.services.package import server_v2_manifest
from app.server_v2.services.skill_runtime import install_skill_driver
from app.server_v2.services.skills import SkillCatalogService
from app.server_v2.storage import prepare_server_v2_storage

LOGGER = logging.getLogger(__name__)


class ServerV2Service:
    def __init__(
        self,
        settings: ServerV2Settings,
        *,
        model_provider: ModelProvider | None = None,
        database=None,
        users=None,
        catalog=None,
        threads=None,
        skills=None,
        package_authorizer=None,
        package_extensions=(),
    ) -> None:
        self.settings = settings
        from sagents.v2.model import ModelConcurrencyBudget
        self.model_budget = ModelConcurrencyBudget(settings.max_concurrent_runs, max_waiting=settings.max_pending_runs)
        self.package_authorizer = package_authorizer
        self.package_extensions = tuple(package_extensions)
        self.catalog_locks = tuple(asyncio.Lock() for _ in range(64))
        self.agent_management = None
        from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import SchedulerQuotaGroup, InMemoryScheduler
        self.run_quota = SchedulerQuotaGroup(settings.max_concurrent_runs, settings.max_concurrent_runs_per_user, settings.max_pending_runs)
        self._scheduler = InMemoryScheduler(quota_group=self.run_quota, max_pending_items=settings.max_pending_runs)
        self.paths = prepare_server_v2_storage(settings.data_root)
        self.database = database
        injected = users is not None and catalog is not None and threads is not None
        if injected:
            self.users, self.catalog, self.threads = users, catalog, threads
            from app.server_v2.repositories.skills import MemorySkillStore

            self.skills = skills if skills is not None else MemorySkillStore()
        else:
            self.users, self.catalog, self.threads = _mysql_repositories(database)
            from app.server_v2.repositories.skills import DatabaseSkillStore

            self.skills = skills if skills is not None else DatabaseSkillStore(database)
        self.skill_catalog = SkillCatalogService(self.skills, self.paths.data_root)
        self.mcp_plugins = McpPluginCache()
        self._fallback_model = model_provider
        self._host_models: HostModelProvider | None = None
        self._application: SAgentApplication | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._agui_drives: dict[str, asyncio.Task[None]] = {}
        self._sandbox_grant_issuer = None
        self._sandbox_provider = None
        install_sandbox(self)

    @property
    def application(self) -> SAgentApplication:
        if self._application is None:
            raise RuntimeError("Server v2 runtime is not started")
        return self._application

    async def start(self) -> None:
        if self._application is not None:
            return
        if self.database is not None:
            from app.server_v2.db.models import create_host_schema

            await create_host_schema(self.database)
        await self.users.ensure_admin(
            self.settings.admin_username, self.settings.admin_password
        )
        self._host_models = HostModelProvider(
            self.catalog,
            fallback=self._fallback_model,
            session_for_run=self._session_id_for_run,
            max_clients=self.settings.max_model_clients,
        )
        self._application = await (
            SAgentBuilder()
            .with_defaults(session_root=self.paths.sessions_root)
            .with_model_provider(self._host_models)
            .with_model_budget(self.model_budget)
            .with_scheduler(self._scheduler)
            .build(server_v2_manifest(self.settings))
        )
        from app.server_v2.services.management import ServerAgentManagement
        from app.server_v2.repositories.packages import DatabasePackageStore
        self.agent_management = ServerAgentManagement(
            self, DatabasePackageStore(self.database) if self.database is not None else None)
        install_skill_driver(self)
        self._log_sagents_registration()
        self._track(asyncio.create_task(self.agent_management.recover_pending(), name="managed-recovery"))

    async def close(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        # Managed applications share host Jobs and model pool: close them first.
        if self.agent_management is not None:
            await self.agent_management.close()
            self.agent_management = None
        if self._application is not None:
            await self._application.close()
            self._application = None
        await self._scheduler.close()
        self.mcp_plugins.clear()
        if self._host_models is not None:
            await self._host_models.close()
            self._host_models = None

    def backends(self) -> dict[str, str]:
        report = {
            "host_store": "mysql" if self.database is not None else "memory",
            "session_store": "mysql" if self.settings.mysql_url else "filesystem",
            "agui_replay": "session-store",
            "log": "stdout",
            # Run ownership lives in this process (driver registry + in-memory
            # scheduler). A shared MySQL does NOT make the deployment
            # multi-node: two instances on one database would both drive the
            # same Run. Horizontal scaling needs an owner lease first.
            "run_ownership": "single-process",
        }
        if self.settings.jaeger_url:
            report["trace"] = "otlp"
        return report

    def request_context(
        self, user_id: str, *, correlation_id: str | None = None
    ) -> RequestContext:
        return RequestContext(
            actor=ActorRef(
                principal_id=user_id,
                principal_type=PrincipalType.USER,
                tenant_id=user_id,
            ),
            trace=TraceContext(correlation_id=correlation_id),
            language=self.settings.language,
        )

    async def username_for(self, user_id: str) -> str:
        user = await self.users.get_by_id(user_id)
        return user.username if user is not None else user_id

    async def delete_thread(
        self, thread_id: str, user_id: str, *, admin: bool = False
    ) -> None:
        record = await self.threads.find(thread_id)
        if record is None or (not admin and record.user_id != user_id):
            raise ServerV2Error("not_found", "thread not found")
        try:
            await self.application.service("session.access").delete_session(
                thread_id, self.request_context(record.user_id)
            )
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise map_sage_error(exc) from exc
        await self.threads.remove(thread_id, record.user_id)

    async def thread_events(
        self,
        thread_id: str,
        user_id: str,
        *,
        admin: bool = False,
        limit: int = 500,
        offset: int | None = None,
    ) -> dict[str, object]:
        """Return one bounded page of AG-UI frames for a thread.

        A thread grows without bound, so the transport projection is paginated
        over source events. ``offset``/``limit`` count source events, not
        frames: one event can translate into several frames and a page must
        never split an event's frames across two responses. ``offset=None``
        returns the newest window, which is what opening a chat needs.
        """

        record = await self.threads.find(thread_id)
        if record is None or (not admin and record.user_id != user_id):
            raise ServerV2Error("not_found", "thread not found")
        limit = max(1, min(int(limit), 2000))
        try:
            events = await self.application.service(
                "session.access"
            ).read_session_events(thread_id, self.request_context(record.user_id))
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise map_sage_error(exc) from exc
            events = []
        total = len(events)
        start = max(0, total - limit) if offset is None else max(0, int(offset))
        page = events[start : start + limit]
        adapter = AgUiProtocolAdapter(enable_sage_extensions=True)
        frames: list[dict] = []
        for event in page:
            result = adapter.translate(event)
            for frame in result.frames:
                frames.append(
                    frame_to_agui_event(frame, thread_id=thread_id, run_id=event.run_id)
                )
        return {
            "events": frames,
            "total": total,
            "offset": start,
            "limit": limit,
        }

    async def start_agui_run(
        self,
        request,
        *,
        user_id: str,
        last_event_id: str | None,
    ):
        props = (
            request.forwarded_props if isinstance(request.forwarded_props, dict) else {}
        )
        requested_agent = str(props.get("agentId") or "").strip()
        thread_id = validate_agui_id(request.thread_id, field="threadId")
        existing = await self.threads.find(thread_id)
        if existing is not None and existing.user_id != user_id:
            raise ServerV2Error("not_found", "thread not found")
        catalog = await self.catalog.get(user_id)
        record = require_agent(
            catalog, resolve_thread_agent_id(existing, requested_agent) or None
        )
        skill_records = tuple(
            await self.skill_catalog.bound_skills(
                owner_user_id=user_id, agent_id=record.id
            )
        )
        enabled = tuple(item.name for item in skill_records)
        thread_id, run_id, agent_id, command = to_start_run(
            request,
            composition_hash=self.application.composition_hash,
            default_agent_id=record.id,
            enabled_skills=enabled,
            metadata=composition_metadata(
                agent=record,
                skills=skill_records,
                mcp_servers=tuple(
                    item.name for item in enabled_mcp_servers(catalog)
                ),
            ),
        )
        if command.agent_id != record.id:
            command = command.model_copy(update={"agent_id": record.id})
            agent_id = record.id
        await self.threads.upsert(thread_id, user_id, agent_id=record.id)
        if not self._has_configured_model(catalog):
            return single_error_sse(
                self._model_missing_message(),
                code="server.model_not_configured",
            )

        correlation_id = get_request_id()
        token = bind_model_user(user_id)
        session_bound = False
        context = self.request_context(user_id, correlation_id=correlation_id)
        try:
            with structured_log_context(correlation_id=correlation_id):
                if self._host_models is not None:
                    self._host_models.bind_session_user(thread_id, user_id)
                    session_bound = True
                stream = await self.application.run_interface(
                    "ag_ui",
                    command,
                    context,
                    agent_id=self.application.resolved_plan.entrypoint_agent_id,
                )
                native_run_id = stream.handle.run_id
                if (
                    native_run_id not in self._agui_drives
                    and stream.handle.state not in TERMINAL_RUN_STATES
                    and stream.handle.state != RunState.SUSPENDED
                ):
                    task = asyncio.create_task(
                        self._observe_agui_run(
                            stream,
                            command,
                            thread_id=thread_id,
                            client_run_id=run_id,
                            user_id=user_id,
                            agent_id=agent_id,
                        ),
                        name=f"server-v2-agui-{native_run_id}",
                    )
                    self._agui_drives[native_run_id] = task
                    self._track(task)
                    session_bound = False
                else:
                    await stream.detach()
                events = self.application.service("session.access").subscribe_events(
                    EventCursor(run_id=native_run_id, run_sequence=0),
                    context,
                )
                return canonical_agui_sse(
                    events,
                    thread_id=thread_id,
                    run_id=run_id,
                    last_event_id=last_event_id,
                )
        except SageV2Error as exc:
            raise map_sage_error(exc) from exc
        finally:
            if session_bound and self._host_models is not None:
                self._host_models.unbind_session_user(thread_id)
            reset_model_user(token)

    async def _observe_agui_run(
        self,
        stream,
        command,
        *,
        thread_id: str,
        client_run_id: str,
        user_id: str,
        agent_id: str,
    ) -> None:
        native_run_id = stream.handle.run_id
        logger = self._sagents_logger().bind(
            thread_id=thread_id,
            run_id=client_run_id,
        )
        logger.info(
            "agui.run.started",
            "AG-UI run started",
            attributes={
                "agent_id": agent_id,
                "user_id": user_id,
                "native_run_id": native_run_id,
            },
        )
        try:
            snapshot = await stream.wait()
            title = ""
            if command.input:
                first = command.input[0].content[0]
                title = getattr(first, "text", "")[:80]
            await self.threads.upsert(
                thread_id, user_id, title=title, agent_id=agent_id
            )
            status = snapshot.state.value
            log_terminal = logger.warning if status == "failed" else logger.info
            log_terminal(f"agui.run.{status}", f"AG-UI run {status}")
        except Exception as exc:
            logger.exception("agui.run.crashed", "AG-UI run crashed", exc)
        finally:
            try:
                await stream.detach()
            finally:
                if self._host_models is not None:
                    self._host_models.unbind_session_user(thread_id)
                self._agui_drives.pop(native_run_id, None)

    async def _session_id_for_run(self, run_id: str) -> str | None:
        if self._application is None:
            return None
        try:
            run = await self._application.entrypoint().runtime.session_store.get_run(
                run_id
            )
        except SageV2Error:
            return None
        return run.session_id

    def _has_configured_model(self, catalog) -> bool:
        if self._fallback_model is not None:
            return True
        return bool(catalog.models)

    def _model_missing_message(self) -> str:
        if str(self.settings.language).lower().startswith("zh"):
            return "请先在「模型」页配置模型后再发送"
        return "Configure a model on the Models page before sending"

    def _sagents_logger(self) -> StructuredLogger:
        return StructuredLogger(
            self.application.service("observability.log-sink"),
            "server_v2.sagents",
        )

    def _log_sagents_registration(self) -> None:
        plan = self.application.resolved_plan
        plugins = sorted(
            {
                (binding.capability, binding.plugin_id)
                for binding in plan.providers
                if binding.plugin_id
            }
        )
        self._sagents_logger().info(
            "sagents.registered",
            "sagents plugins registered",
            attributes={
                "package_id": plan.package_id,
                "entrypoint": plan.entrypoint_agent_id,
                "composition_hash": plan.composition_hash,
                "plugins": [
                    {"capability": capability, "plugin": plugin_id}
                    for capability, plugin_id in plugins
                ],
            },
        )

    def _track(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)

        def _done(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                LOGGER.error("background AG-UI task failed", exc_info=error)

        task.add_done_callback(_done)


def _mysql_repositories(database):
    if database is None:
        raise RuntimeError("MySQL is required")
    from app.server_v2.repositories import (
        DatabaseCatalogStore,
        DatabaseThreadIndex,
        DatabaseUserStore,
    )

    return (
        DatabaseUserStore(database),
        DatabaseCatalogStore(database),
        DatabaseThreadIndex(database),
    )
