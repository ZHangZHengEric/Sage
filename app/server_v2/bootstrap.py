from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sagents.v2.application import SAgentApplication
from sagents.v2.builder import SAgentBuilder
from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
    TraceContext,
)
from sagents.v2.model.middleware.concurrency import ModelConcurrencyBudget
from sagents.v2.model.provider import ModelProvider
from sagents.v2.runtime.observability.contracts import LogSink
from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import (
    InMemoryScheduler,
    SchedulerQuotaGroup,
)

from app.server_v2.admin.service import AdminService
from app.server_v2.conversations.admission import RunAdmission
from app.server_v2.runtime.execution import ProcessExecution
from app.server_v2.catalog.service import CatalogService
from app.server_v2.conversations.a2a.service import A2AService
from app.server_v2.conversations.agui.service import ConversationService
from app.server_v2.identity.credentials import CredentialService
from app.server_v2.identity.service import IdentityService
from app.server_v2.config.manifest import server_v2_manifest
from app.server_v2.runtime.official import install_sandbox
from app.server_v2.conversations.runs import RunService
from app.server_v2.skills.runtime import CatalogRunDriver
from app.server_v2.skills.service import SkillCatalogService
from app.server_v2.config.settings import ServerSettings
from app.server_v2.observability.logging import get_logger
from app.server_v2.identity.keys import ApiKeyRecord
from app.server_v2.runtime.integrations.a2a import A2APluginCache
from app.server_v2.database import Database
from app.server_v2.runtime.integrations.mcp import McpPluginCache
from app.server_v2.runtime.models import HostModelProvider
from app.server_v2.identity.key_repository import ApiKeyStore, DatabaseApiKeyStore
from app.server_v2.identity.repository import DatabaseUserStore, UserStore
from app.server_v2.catalog.repository import CatalogStore, DatabaseCatalogStore
from app.server_v2.skills.repository import DatabaseSkillStore, SkillStore
from app.server_v2.conversations.repository import DatabaseThreadIndex, ThreadIndex
from app.server_v2.storage import prepare_server_v2_storage

LOGGER = get_logger(__name__)

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
        database: Database,
        repositories: HostRepositories | None = None,
        package_authorizer=None,
        package_extensions=(),
    ) -> None:
        if database is None:
            raise RuntimeError("database is required")
        self.settings = settings
        self.log_sink: LogSink | None = None
        self.contexts = RequestContexts(settings.language)
        self.package_authorizer = package_authorizer
        self.package_extensions = tuple(package_extensions)
        self.agent_management = None
        self.package_queries = None
        self.database = database

        self.paths = prepare_server_v2_storage(settings.data_root)

        if repositories is None:
            repositories = HostRepositories(
                users=DatabaseUserStore(database),
                catalog=DatabaseCatalogStore(database),
                threads=DatabaseThreadIndex(database),
                skills=DatabaseSkillStore(database),
                api_keys=DatabaseApiKeyStore(database),
            )
        self.users = repositories.users
        self.catalog_store = repositories.catalog
        self.skills = repositories.skills
        self.threads = repositories.threads
        self.identity = IdentityService(self.users)
        self.skill_catalog = SkillCatalogService(self.skills, self.paths.data_root)
        self.mcp_plugins = McpPluginCache()
        self.a2a_plugins = A2APluginCache()
        self.catalog = CatalogService(
            self.catalog_store,
            mcp_plugins=self.mcp_plugins,
            a2a_plugins=self.a2a_plugins,
            skills=self.skill_catalog,
        )
        self.credentials = CredentialService(repositories.api_keys, self.catalog)
        self.execution = ProcessExecution(fallback_model=model_provider)
        self._application: SAgentApplication | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        install_sandbox(self.execution)
        self.conversations: ConversationService | None = None
        self.admin: AdminService | None = None
        self.a2a: A2AService | None = None

    @property
    def application(self) -> SAgentApplication:
        if self._application is None:
            raise RuntimeError("Server v2 runtime is not started")
        return self._application

    async def ready(self) -> bool:
        if self._application is None or self.agent_management is None:
            return False
        try:
            return await asyncio.wait_for(self.database.ready(), timeout=1.0)
        except TimeoutError:
            return False

    async def start(self) -> None:
        if self._application is not None:
            return
        if self.log_sink is None:
            from app.server_v2.observability.logging import LoggingSettings, init_logging

            self.log_sink = init_logging(
                LoggingSettings(
                    level=self.settings.log_level,
                    format=self.settings.log_format,
                    directory=self.settings.log_directory,
                ),
                service_name="sage-server",
            )
        from app.server_v2.database.schema import create_host_schema

        await create_host_schema(self.database)
        await self.identity.ensure_admin(
            self.settings.admin_username, self.settings.admin_password
        )
        model_budget = ModelConcurrencyBudget(
            self.settings.max_concurrent_runs,
            max_waiting=self.settings.max_pending_runs,
        )
        run_quota = SchedulerQuotaGroup(
            self.settings.max_concurrent_runs,
            self.settings.max_concurrent_runs_per_user,
            self.settings.max_pending_runs,
        )
        scheduler = InMemoryScheduler(
            quota_group=run_quota,
            max_pending_items=self.settings.max_pending_runs,
        )
        host_models: HostModelProvider | None = None
        try:
            self.execution.model_budget = model_budget
            host_models = HostModelProvider(
                self.catalog_store,
                fallback=self.execution.fallback_model,
                max_clients=self.settings.max_model_clients,
            )
            self.execution.model_pool = host_models
            self._application = await (
                SAgentBuilder()
                .with_defaults(session_root=self.paths.sessions_root)
                .with_model_provider(host_models)
                .with_log_sink(self.log_sink)
                .with_model_budget(model_budget)
                .with_scheduler(scheduler)
                .with_run_driver_factory(lambda run_id: CatalogRunDriver(self, run_id))
                .with_owned_resources(scheduler, host_models)
                .build(server_v2_manifest(self.settings))
            )
            host_models.session_store = self._application.entrypoint().runtime.session_store
            session_access = self._application.service("session.access")
            admission = RunAdmission(
                threads=self.threads,
                catalog=self.catalog,
                skills=self.skill_catalog,
                execution=self.execution,
            )
            runs = RunService(
                application=self._application,
                session_access=session_access,
                execution=self.execution,
            )
            self.conversations = ConversationService(
                threads=self.threads,
                admission=admission,
                runs=runs,
                application=self._application,
                session_access=session_access,
                log_sink=self.log_sink,
                context_for=self.contexts.for_user,
                language=self.settings.language,
            )
            self.admin = AdminService(
                users=self.users,
                threads=self.threads,
                catalog=self.catalog,
            )
            self.a2a = A2AService(
                threads=self.threads,
                catalog=self.catalog,
                admission=admission,
                runs=runs,
                application=self._application,
                session_access=session_access,
                context_for=self.contexts.for_a2a_key,
                language=self.settings.language,
            )
            from app.server_v2.packages.recovery import (
                recover_pending_packages,
            )
            from app.server_v2.packages.management import ServerAgentManagement

            self.agent_management = ServerAgentManagement(
                self.paths.data_root / "managed",
                database=self.database,
                settings=self.settings,
                paths=self.paths,
                users=self.users,
                catalog=self.catalog,
                skills=self.skills,
                skill_catalog=self.skill_catalog,
                execution=self.execution,
                mcp_plugins=self.mcp_plugins,
                a2a_plugins=self.a2a_plugins,
                package_authorizer=self.package_authorizer,
                extensions=self.package_extensions,
                run_quota=run_quota,
                model_budget=model_budget,
                log_sink=self.log_sink,
                job_runtime=self.application.service("execution.job-runtime"),
            )
            self.package_queries = self.agent_management.queries
            self._track(
                asyncio.create_task(
                    recover_pending_packages(
                        self.agent_management, self.users, self.contexts
                    ),
                    name="managed-recovery",
                )
            )
        except BaseException as exc:
            try:
                await self.close()
            except BaseException as close_exc:
                exc.add_note(f"server startup cleanup also failed: {close_exc}")
            try:
                await scheduler.close()
            except BaseException as close_exc:
                exc.add_note(f"scheduler cleanup also failed: {close_exc}")
            if host_models is not None:
                try:
                    await host_models.close()
                except BaseException as close_exc:
                    exc.add_note(f"model pool cleanup also failed: {close_exc}")
            raise

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
        self.package_queries = None
        self.conversations = None
        self.admin = None
        self.a2a = None
        if self._application is not None:
            await self._application.close()
            self._application = None
        self.mcp_plugins.clear()
        self.a2a_plugins.clear()
        self.execution.model_pool = None
        self.execution.model_budget = None

    def _track(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)

        def _done(completed: asyncio.Task[None]) -> None:
            self._tasks.discard(completed)
            if completed.cancelled():
                return
            error = completed.exception()
            if error is not None:
                LOGGER.exception(
                    "server.background.failed", "background task failed", error
                )

        task.add_done_callback(_done)
