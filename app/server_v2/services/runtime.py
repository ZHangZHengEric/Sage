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
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.model.provider import ModelProvider
from sagents.v2.runtime.observability import StructuredLogger, structured_log_context

from app.server_v2.agui.mapping import to_start_run, validate_agui_id
from app.server_v2.agui.redis_store import RedisAguiReplayStore
from app.server_v2.agui.replay import AguiRun
from app.server_v2.agui.sse import (
    ClientOwnedUserTextFilter,
    RunStartedGate,
    frame_to_agui_event,
    run_error_event,
)
from app.server_v2.core.errors import ServerV2Error, map_sage_error
from app.server_v2.core.observability.context import get_request_id
from app.server_v2.core.settings import ServerV2Settings
from app.server_v2.domain.catalog import require_agent
from app.server_v2.domain.threads import resolve_thread_agent_id
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
        redis=None,
        users=None,
        catalog=None,
        threads=None,
        skills=None,
        replay=None,
    ) -> None:
        self.settings = settings
        self.paths = prepare_server_v2_storage(settings.data_root)
        self.database = database
        self._redis = redis
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
        self.replay = replay if replay is not None else _redis_replay(redis)
        self._fallback_model = model_provider
        self._host_models: HostModelProvider | None = None
        self._application: SAgentApplication | None = None
        self._tasks: set[asyncio.Task[None]] = set()
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
        )
        self._application = await (
            SAgentBuilder()
            .with_defaults(session_root=self.paths.sessions_root)
            .with_model_provider(self._host_models)
            .build(server_v2_manifest(self.settings))
        )
        install_skill_driver(self)
        self._log_sagents_registration()

    async def close(self) -> None:
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        if self._application is not None:
            await self._application.close()
            self._application = None

    def backends(self) -> dict[str, str]:
        report = {
            "host_store": "mysql" if self.database is not None else "memory",
            "session_store": "mysql" if self.settings.mysql_url else "filesystem",
            "agui_replay": "redis" if self._redis is not None else "memory",
            "log": "stdout",
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
        self, thread_id: str, user_id: str, *, admin: bool = False
    ) -> list[dict]:
        record = await self.threads.find(thread_id)
        if record is None or (not admin and record.user_id != user_id):
            raise ServerV2Error("not_found", "thread not found")
        try:
            events = await self.application.service(
                "session.access"
            ).read_session_events(thread_id, self.request_context(record.user_id))
        except SageV2Error as exc:
            if exc.info.code.endswith("not_found"):
                return []
            raise map_sage_error(exc) from exc
        adapter = AgUiProtocolAdapter(enable_sage_extensions=True)
        frames: list[dict] = []
        for event in events:
            result = adapter.translate(event)
            for frame in result.frames:
                frames.append(
                    frame_to_agui_event(frame, thread_id=thread_id, run_id=event.run_id)
                )
        return frames

    async def start_agui_run(
        self,
        request,
        *,
        user_id: str,
        last_event_id: str | None,
    ):
        props = request.forwarded_props if isinstance(request.forwarded_props, dict) else {}
        requested_agent = str(props.get("agentId") or "").strip()
        thread_id = validate_agui_id(request.thread_id, field="threadId")
        existing = await self.threads.find(thread_id)
        if existing is not None and existing.user_id != user_id:
            raise ServerV2Error("not_found", "thread not found")
        catalog = await self.catalog.get(user_id)
        record = require_agent(
            catalog, resolve_thread_agent_id(existing, requested_agent) or None
        )
        enabled = await self.skill_catalog.bound_names(user_id, record.id)
        thread_id, run_id, agent_id, command = to_start_run(
            request,
            composition_hash=self.application.composition_hash,
            default_agent_id=record.id,
            enabled_skills=enabled,
        )
        if command.agent_id != record.id:
            command = command.model_copy(update={"agent_id": record.id})
            agent_id = record.id
        await self.threads.upsert(thread_id, user_id, agent_id=record.id)
        claim = await self.replay.claim(
            user_id=user_id, thread_id=thread_id, run_id=run_id
        )
        if claim.created:
            self._track(
                asyncio.create_task(
                    self._drive_agui_run(
                        claim.run,
                        command,
                        user_id=user_id,
                        agent_id=agent_id,
                        correlation_id=get_request_id(),
                    ),
                    name=f"server-v2-agui-{run_id}",
                )
            )
        return self.replay.subscribe(claim.run, last_event_id=last_event_id)

    async def _drive_agui_run(
        self,
        run: AguiRun,
        command,
        *,
        user_id: str,
        agent_id: str,
        correlation_id: str,
    ) -> None:
        with structured_log_context(correlation_id=correlation_id):
            await self._drive_correlated_agui_run(
                run,
                command,
                user_id=user_id,
                agent_id=agent_id,
                correlation_id=correlation_id,
            )

    async def _drive_correlated_agui_run(
        self,
        run: AguiRun,
        command,
        *,
        user_id: str,
        agent_id: str,
        correlation_id: str,
    ) -> None:
        token = bind_model_user(user_id)
        if self._host_models is not None:
            self._host_models.bind_session_user(run.thread_id, user_id)
        context = self.request_context(user_id, correlation_id=correlation_id)
        stream = None
        gate = RunStartedGate()
        owned_user_text = ClientOwnedUserTextFilter()
        logger = self._sagents_logger().bind(
            thread_id=run.thread_id,
            run_id=run.run_id,
        )
        logger.info(
            "agui.run.started",
            "AG-UI run started",
            attributes={"agent_id": agent_id, "user_id": user_id},
        )
        try:
            if not await self._has_configured_model(user_id):
                await self._fail_agui_run(
                    run,
                    gate,
                    self._model_missing_message(),
                    code="server.model_not_configured",
                )
                logger.warning(
                    "agui.run.failed",
                    "AG-UI run failed",
                    attributes={"code": "server.model_not_configured"},
                )
                return
            stream = await self.application.run_interface(
                "ag_ui",
                command,
                context,
                agent_id=self.application.resolved_plan.entrypoint_agent_id,
            )
            async for result in stream.results:
                for frame in result.frames:
                    event = frame_to_agui_event(
                        frame, thread_id=run.thread_id, run_id=run.run_id
                    )
                    if not owned_user_text.allow(event):
                        continue
                    for payload in gate.release(event):
                        await self.replay.publish(run, payload)
            title = ""
            if command.input:
                first = command.input[0].content[0]
                title = getattr(first, "text", "")[:80]
            await self.threads.upsert(
                run.thread_id, user_id, title=title, agent_id=agent_id
            )
            await self.replay.finish(run, "completed")
            logger.info("agui.run.completed", "AG-UI run completed")
        except SageV2Error as exc:
            logger.warning(
                "agui.run.failed",
                "AG-UI run failed",
                attributes={"code": exc.info.code, "category": exc.info.category.value},
            )
            mapped = map_sage_error(exc)
            for payload in gate.release(
                run_error_event(mapped.message, code=exc.info.code)
            ):
                await self.replay.publish(run, payload)
            await self.replay.finish(run, "failed")
        except Exception as exc:
            logger.exception("agui.run.crashed", "AG-UI run crashed", exc)
            for payload in gate.release(
                run_error_event("internal server error", code="INTERNAL")
            ):
                await self.replay.publish(run, payload)
            await self.replay.finish(run, "failed")
        finally:
            if self._host_models is not None:
                self._host_models.unbind_session_user(run.thread_id)
            reset_model_user(token)
            if stream is not None:
                await stream.detach()

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

    async def _has_configured_model(self, user_id: str) -> bool:
        if self._fallback_model is not None:
            return True
        return await self.catalog.default_model(user_id) is not None

    def _model_missing_message(self) -> str:
        if str(self.settings.language).lower().startswith("zh"):
            return "请先在「模型」页配置模型后再发送"
        return "Configure a model on the Models page before sending"

    async def _fail_agui_run(
        self,
        run: AguiRun,
        gate: RunStartedGate,
        message: str,
        *,
        code: str,
    ) -> None:
        for payload in gate.release(run_error_event(message, code=code)):
            await self.replay.publish(run, payload)
        await self.replay.finish(run, "failed")

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


def _redis_replay(redis):
    if redis is None:
        raise RuntimeError("Redis is required")
    return RedisAguiReplayStore(redis)
