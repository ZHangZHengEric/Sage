from __future__ import annotations

import asyncio
from dataclasses import replace
from functools import cached_property

from sagents.v2.application import SAgentApplication
from sagents.v2.builder import SAgentBuilder
from sagents.v2.model.middleware.concurrency import ModelConcurrencyBudget
from sagents.v2.model.provider import ModelProvider
from sagents.v2.runtime.observability.contracts import LogSink
from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import (
    InMemoryScheduler,
    SchedulerQuotaGroup,
)

from app.v2.server.admin.service import AdminService
from app.v2.server.conversations.admission import RunAdmission
from app.v2.server.runtime.execution import ProcessExecution
from app.v2.server.runtime.loop import CatalogRunDependencies
from app.v2.server.catalog.service import CatalogService
from app.v2.server.conversations.a2a.service import A2AService
from app.v2.server.conversations.agui.service import ConversationService
from app.v2.server.identity.credentials import CredentialService
from app.v2.server.identity.context import RequestContexts
from app.v2.server.identity.service import IdentityService
from app.v2.server.config.manifest import server_v2_manifest
from app.v2.server.runtime.official import install_sandbox
from app.v2.server.conversations.runs import RunService
from app.v2.server.skills.service import SkillCatalogService
from app.v2.server.config.settings import ServerSettings
from app.v2.server.observability.logging import get_logger
from app.v2.server.runtime.integrations.a2a import A2APluginCache
from app.v2.server.database import Database
from app.v2.server.runtime.integrations.mcp import McpPluginCache
from app.v2.server.runtime.models import ServerModelClients
from app.v2.server.identity.key_repository import ApiKeyStore, DatabaseApiKeyStore
from app.v2.server.identity.repository import DatabaseUserStore, UserStore
from app.v2.server.catalog.repository import CatalogStore, DatabaseCatalogStore
from app.v2.server.skills.repository import DatabaseSkillStore, SkillStore
from app.v2.server.conversations.repository import DatabaseThreadIndex, ThreadIndex
from app.v2.server.storage import prepare_server_v2_storage

LOGGER = get_logger(__name__)

class ServerHost:
    @cached_property
    def agent_plugin_catalog(self):
        from app.v2.server.catalog.editor import build_plugin_catalog
        return build_plugin_catalog(self)

    def __init__(
        self,
        settings: ServerSettings,
        *,
        model_provider: ModelProvider | None = None,
        database: Database,
        users: UserStore | None = None,
        catalog_store: CatalogStore | None = None,
        threads: ThreadIndex | None = None,
        skills: SkillStore | None = None,
        api_keys: ApiKeyStore | None = None,
        package_authorizer=None,
        extensions=(),
    ) -> None:
        if database is None:
            raise RuntimeError("database is required")
        self.settings = settings
        self.log_sink: LogSink | None = None
        self.diagnostics = None
        self.contexts = RequestContexts(settings.language)
        self.package_authorizer = package_authorizer
        self._registrations = tuple(extensions)
        from sagents.v2.runtime.extensions.official import builtin_extension_registry
        self.extensions = builtin_extension_registry()
        for registration in self._registrations:
            self.extensions.register(registration)
        self.agent_management = None
        self.package_queries = None
        self.database = database

        self.paths = prepare_server_v2_storage(
            settings.data_root,
            linux_execution_uid=settings.linux_execution_uid,
            linux_execution_gid=settings.linux_execution_gid,
        )

        self.users = users if users is not None else DatabaseUserStore(database)
        self.catalog_store = (
            catalog_store if catalog_store is not None else DatabaseCatalogStore(database)
        )
        self.skills = skills if skills is not None else DatabaseSkillStore(database)
        self.threads = threads if threads is not None else DatabaseThreadIndex(database)
        self.identity = IdentityService(
            self.users,
            jwt_secret=settings.jwt_secret,
            jwt_expire_hours=settings.jwt_expire_hours,
        )
        self.skill_catalog = SkillCatalogService(self.skills, self.paths.data_root)
        self.mcp_plugins = McpPluginCache()
        self.a2a_plugins = A2APluginCache()
        self.catalog = CatalogService(
            self.catalog_store,
            mcp_plugins=self.mcp_plugins,
            a2a_plugins=self.a2a_plugins,
            skills=self.skill_catalog,
        )
        self.catalog.extensions = self.extensions
        self.credentials = CredentialService(
            api_keys if api_keys is not None else DatabaseApiKeyStore(database),
            self.catalog,
        )
        self.execution = ProcessExecution(fallback_model=model_provider)
        self._application: SAgentApplication | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._background_closing = False
        self.conversations: ConversationService | None = None
        self.admin: AdminService | None = None
        self.a2a: A2AService | None = None

    @property
    def application(self) -> SAgentApplication:
        if self._application is None:
            raise RuntimeError("Server v2 runtime is not started")
        return self._application

    def _catalog_run_dependencies(self) -> CatalogRunDependencies:
        return CatalogRunDependencies(
            settings=self.settings,
            paths=self.paths,
            catalog=self.catalog,
            skill_catalog=self.skill_catalog,
            execution=self.execution,
            application=self.application,
            mcp_plugins=self.mcp_plugins,
            a2a_plugins=self.a2a_plugins,
            contexts=self.contexts,
            agent_management=self.agent_management,
            users=self.users, keys=self.credentials.keys, threads=self.threads,
        )

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
        self._background_closing = False
        self.__dict__.pop("agent_plugin_catalog", None)
        from app.v2.server.config.plugins import ServerPluginConfig

        self.settings = replace(
            self.settings,
            plugin_overrides=ServerPluginConfig(self.paths.data_root, registry=self.extensions).read(),
        )
        if self.diagnostics is None or self.diagnostics.closed:
            from app.v2.server.observability.diagnostics import SessionDiagnostics
            from app.v2.server.observability.external import external_diagnostics

            selection = server_v2_manifest(self.settings).runtime.capabilities["observability.trace-sink"]
            self.diagnostics = external_diagnostics(self.settings, selection)
            if self.diagnostics is None:
                self.diagnostics = SessionDiagnostics(self.paths.runtime_root / "diagnostics")
        if self.log_sink is None:
            from app.v2.server.observability.logging import LoggingSettings, init_logging

            self.log_sink = init_logging(
                LoggingSettings(
                    level=self.settings.log_level,
                    format=self.settings.log_format,
                    directory=self.settings.log_directory,
                ),
                service_name="sage-server",
                diagnostics=self.diagnostics,
            )
        from app.v2.server.observability.logging import ServerLogSink

        if isinstance(self.log_sink, ServerLogSink):
            self.log_sink.diagnostics = self.diagnostics
        from app.v2.server.database.schema import create_host_schema

        await create_host_schema(self.database)
        await self.identity.start()
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
        host_models: ServerModelClients | None = None
        try:
            self.execution.model_budget = model_budget
            host_models = ServerModelClients(max_clients=self.settings.max_model_clients)
            self.execution.model_pool = host_models
            from app.v2.server.runtime.sdk_plugins import server_registrations, service_registration, service_selection, SCHEDULER_CONFIG_SCHEMA
            builder = SAgentBuilder()
            choices = {}
            manifest = server_v2_manifest(self.settings)
            for capability, value, ownership in (
                ("observability.log-sink", self.log_sink, "borrowed"),
                ("observability.diagnostic-sink", self.diagnostics, "borrowed"),
                ("execution.model-budget", model_budget, "borrowed"),
                ("execution.scheduler", scheduler, "owned"),
                ("server.model-clients", host_models, "owned"),
            ):
                scheduler_port = capability == "execution.scheduler"
                builder.register(service_registration(capability, value, ownership=ownership,
                    dependencies=("server.model-clients",) if scheduler_port else (),
                    config_schema=SCHEDULER_CONFIG_SCHEMA if scheduler_port else None))
                choices[capability] = service_selection(capability, config=
                    manifest.runtime.capabilities[capability].config if scheduler_port else None)
            for registration in (*self._registrations, *server_registrations(self)):
                builder.register(registration)
            from app.v2.server.runtime.official import file_sandbox_registrations
            for registration in file_sandbox_registrations(self.settings):
                builder.register(registration)
                capability = registration.descriptor.provides[0].capability
                choices[capability] = service_selection(capability)
            from sagents.v2.package.manifest.runtime import CapabilitySelection
            choices["interface.protocol-adapter"] = (
                CapabilitySelection(plugin="sage.protocol.ag-ui", name="ag-ui", scope="process", config={"enable_sage_extensions": True}),
                CapabilitySelection(plugin="sage.protocol.a2a", name="a2a", scope="process"),
            )
            manifest = server_v2_manifest(self.settings)
            runtime = manifest.runtime.model_copy(update={
                "capabilities": {**manifest.runtime.capabilities, **choices},
                "state_root": str(self.paths.sessions_root), "start_workers": False,
            })
            self._application = await builder.build(runtime=runtime)
            from app.v2.server.observability.external import ExternalDiagnostics

            if isinstance(self.diagnostics, ExternalDiagnostics):
                self.diagnostics.trace_sink = self._application.service("observability.trace-sink")
            await install_sandbox(self.execution, self._application, self.settings)
            session_access = self._application.service("session.access")
            admission = RunAdmission(
                threads=self.threads,
                catalog=self.catalog,
                skills=self.skill_catalog,
                execution=self.execution,
                users=self.users, settings=self.settings,
                session_access=session_access, context_for=self.contexts.for_user,
            )
            runs = RunService(
                application=self._application,
                session_access=session_access,
                execution=self.execution, host=self,
                users=self.users, keys=self.credentials.keys, catalog=self.catalog, settings=self.settings,
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
            self._track(asyncio.create_task(self._expire_approvals(runs), name="approval-expiration"))
            self.admin = AdminService(
                users=self.users,
                threads=self.threads,
                catalog=self.catalog,
                skills=self.skill_catalog,
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
                public_base_url=self.settings.public_base_url,
                settings=self.settings,
            )
            from app.v2.server.packages.recovery import (
                recover_pending_packages,
            )
            from app.v2.server.packages.management import ServerAgentManagement

            self.agent_management = ServerAgentManagement(
                self.paths.data_root / "managed",
                database=self.database,
                host=self,
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
                extensions=self._registrations,
                run_quota=run_quota,
                model_budget=model_budget,
                log_sink=self.log_sink,
                diagnostic_sink=self.diagnostics,
                job_runtime=self.application.service("execution.job-runtime"),
            )
            self.package_queries = self.agent_management.queries
            await self.application.service("execution.dispatcher").start()
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
        self._background_closing = True
        await self.identity.close()
        while self._tasks:
            pending = tuple(self._tasks)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            self._tasks.difference_update(pending)
        # Stop acceptance/handoff before taking the product observer snapshot.
        await self.execution.close()
        # Managed applications share host Jobs and model pool: close them first.
        if self.agent_management is not None:
            await self.agent_management.close()
            self.agent_management = None
        self.package_queries = None
        self.conversations = None
        self.admin = None
        self.a2a = None
        # Flush grouped observation evidence while the trace exporter is alive.
        if self.diagnostics is not None:
            await self.diagnostics.close()
        if self._application is not None:
            await self._application.close()
        self._application = None
        self.execution.sandbox_provider = None
        self.execution.sandbox_grant_issuer = None
        self.mcp_plugins.clear()
        self.a2a_plugins.clear()
        self.execution.model_pool = None
        self.execution.model_budget = None

    async def _expire_approvals(self, runs):
        while True:
            more = False
            try:
                more = await runs.expire_approvals(self.threads, self.contexts.for_user)
            except Exception as exc:
                LOGGER.exception("approval.expiration.failed", "approval expiration pass failed", exc)
            await asyncio.sleep(0 if more else 60)

    def _track(self, task: asyncio.Task[None]) -> None:
        self._tasks.add(task)
        if self._background_closing:
            task.cancel()

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
