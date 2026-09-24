from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
    TraceContext,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.runtime.observability import StructuredLogger

from app.server_v2.application.admin import AdminService
from app.server_v2.application.admission import RunAdmission
from app.server_v2.application.a2a import A2AService
from app.server_v2.application.execution import ProcessExecution
from app.server_v2.application.catalog import CatalogService
from app.server_v2.application.conversations import ConversationService
from app.server_v2.application.credentials import CredentialService
from app.server_v2.application.identity import IdentityService
from app.server_v2.application.manifest import server_v2_manifest
from app.server_v2.application.official import install_sandbox
from app.server_v2.application.runs import RunService
from app.server_v2.application.runtime_port import AgentRuntime
from app.server_v2.application.sessions import SessionLog
from app.server_v2.application.skill_runtime import install_skill_driver
from app.server_v2.application.skills import SkillCatalogService
from app.server_v2.core.settings import ServerSettings
from app.server_v2.domain.api_keys import ApiKeyRecord
from app.server_v2.infrastructure.a2a_client import A2APluginCache
from app.server_v2.infrastructure.database import Database
from app.server_v2.infrastructure.mcp import McpPluginCache
from app.server_v2.infrastructure.models import HostModelProvider
from app.server_v2.infrastructure.persistence import (
    ApiKeyStore,
    CatalogStore,
    DatabaseApiKeyStore,
    DatabaseCatalogStore,
    DatabaseSkillStore,
    DatabaseThreadIndex,
    DatabaseUserStore,
    SkillStore,
    ThreadIndex,
    UserStore,
)
from app.server_v2.infrastructure.storage import prepare_server_v2_storage

LOGGER = logging.getLogger(__name__)

TOOL_SCOPES = (
    "tool.read",
    "tool.write",
    "tool.internal",
    "tool.external_side_effect",
    "skill.load",
    "workspace.read",
    "workspace.write",
    "workspace.delete",
    "process.run",
)


@dataclass(frozen=True, slots=True)
class HostRepositories:
    users: UserStore
    catalog: CatalogStore
    threads: ThreadIndex
    skills: SkillStore
    api_keys: ApiKeyStore


class RequestContexts:
    def __init__(self, language: str) -> None:
        self.language = language

    def for_user(
        self, user_id: str, *, correlation_id: str | None = None
    ) -> RequestContext:
        return RequestContext(
            actor=ActorRef(
                principal_id=user_id,
                principal_type=PrincipalType.USER,
                tenant_id=user_id,
                scopes=TOOL_SCOPES,
            ),
            trace=TraceContext(correlation_id=correlation_id),
            language=self.language,
        )

    def for_a2a_key(
        self, key: ApiKeyRecord, *, correlation_id: str | None = None
    ) -> RequestContext:
        # The owner remains the principal so their A2A threads are accessible
        # from the web UI and other keys. Keep the credential in delegated_by.
        return RequestContext(
            actor=ActorRef(
                principal_id=key.owner_user_id,
                principal_type=PrincipalType.USER,
                tenant_id=key.owner_user_id,
                delegated_by=key.key_id,
                scopes=(*key.scopes, *TOOL_SCOPES),
            ),
            trace=TraceContext(correlation_id=correlation_id),
            language=self.language,
        )


class ServerHost:
    def __init__(
        self,
        settings: ServerSettings,
        *,
        model_provider: ModelProvider | None = None,
        database: Database | None = None,
        repositories: HostRepositories | None = None,
        package_authorizer=None,
        package_extensions=(),
    ) -> None:
        if database is not None and repositories is not None:
            raise ValueError("provide database or repositories, not both")
        self.settings = settings
        self.contexts = RequestContexts(settings.language)
        from sagents.v2.model import ModelConcurrencyBudget
        self.model_budget = ModelConcurrencyBudget(settings.max_concurrent_runs, max_waiting=settings.max_pending_runs)
        self.package_authorizer = package_authorizer
        self.package_extensions = tuple(package_extensions)
        self.agent_management = None
        from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import SchedulerQuotaGroup, InMemoryScheduler
        self.run_quota = SchedulerQuotaGroup(settings.max_concurrent_runs, settings.max_concurrent_runs_per_user, settings.max_pending_runs)
        self._scheduler = InMemoryScheduler(quota_group=self.run_quota, max_pending_items=settings.max_pending_runs)
        self.paths = prepare_server_v2_storage(settings.data_root)
        self.database = database
        if repositories is None:
            if database is None:
                raise RuntimeError("MySQL is required")
            repositories = HostRepositories(
                users=DatabaseUserStore(database),
                catalog=DatabaseCatalogStore(database),
                threads=DatabaseThreadIndex(database),
                skills=DatabaseSkillStore(database),
                api_keys=DatabaseApiKeyStore(database),
            )
        self.users = repositories.users
        self.threads = repositories.threads
        self.skills = repositories.skills
        self.api_keys = repositories.api_keys
        self.identity = IdentityService(self.users)
        self.skill_catalog = SkillCatalogService(self.skills, self.paths.data_root)
        self.mcp_plugins = McpPluginCache()
        self.a2a_plugins = A2APluginCache()
        self.catalog = CatalogService(
            repositories.catalog,
            mcp_plugins=self.mcp_plugins,
            a2a_plugins=self.a2a_plugins,
            skills=self.skill_catalog,
        )
        self.credentials = CredentialService(self.api_keys, self.catalog)
        self.execution = ProcessExecution(model_missing=self._model_missing_message())
        self._fallback_model = model_provider
        install_sandbox(self.execution)
        self.sessions = SessionLog(lambda: self.application.service("session.access"))
        self.runtime = AgentRuntime(lambda: self._application)
        self.admission = RunAdmission(
            threads=self.threads,
            catalog=self.catalog,
            skills=self.skill_catalog,
            execution=self.execution,
        )
        self.runs = RunService(
            runtime=self.runtime,
            sessions=self.sessions,
            execution=self.execution,
        )
        self.conversations = ConversationService(
            threads=self.threads,
            admission=self.admission,
            sessions=self.sessions,
            runs=self.runs,
            execution=self.execution,
            runtime=self.runtime,
            context_for=self.contexts.for_user,
        )
        self.admin = AdminService(
            users=self.users,
            threads=self.threads,
            catalog=self.catalog,
            conversations=self.conversations,
        )
        self.a2a = A2AService(
            threads=self.threads,
            catalog=self.catalog,
            admission=self.admission,
            runs=self.runs,
            sessions=self.sessions,
            execution=self.execution,
            runtime=self.runtime,
            context_for=self.contexts.for_a2a_key,
        )
        self._host_models: HostModelProvider | None = None
        self._application: SAgentApplication | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def _fallback_model(self):
        return self.execution.fallback_model

    @_fallback_model.setter
    def _fallback_model(self, value) -> None:
        self.execution._fallback = value

    @property
    def application(self) -> SAgentApplication:
        if self._application is None:
            raise RuntimeError("Server v2 runtime is not started")
        return self._application

    async def start(self) -> None:
        if self._application is not None:
            return
        if self.database is not None:
            from app.server_v2.infrastructure.database.schema import create_host_schema

            await create_host_schema(self.database)
        await self.identity.ensure_admin(
            self.settings.admin_username, self.settings.admin_password
        )
        self._host_models = HostModelProvider(
            self.catalog,
            fallback=self._fallback_model,
            session_for_run=self._session_id_for_run,
            max_clients=self.settings.max_model_clients,
        )
        self.execution.attach_models(self._host_models)
        self._application = await (
            SAgentBuilder()
            .with_defaults(session_root=self.paths.sessions_root)
            .with_model_provider(self._host_models)
            .with_model_budget(self.model_budget)
            .with_scheduler(self._scheduler)
            .build(server_v2_manifest(self.settings))
        )
        from app.server_v2.application.packages import ServerAgentManagement
        from app.server_v2.infrastructure.persistence.packages import DatabasePackageStore
        self.agent_management = ServerAgentManagement(
            self, DatabasePackageStore(self.database) if self.database is not None else None)
        install_skill_driver(self)
        self.execution.attach_logger(self._sagents_logger())
        self._log_sagents_registration()
        self._track(asyncio.create_task(self.agent_management.recover_pending(), name="managed-recovery"))

    async def close(self) -> None:
        await self.execution.close()
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
        self.a2a_plugins.clear()
        if self._host_models is not None:
            await self._host_models.close()
            self._host_models = None
        self.execution.attach_models(None)
        self.execution.attach_logger(None)

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
                LOGGER.error("background task failed", exc_info=error)

        task.add_done_callback(_done)
