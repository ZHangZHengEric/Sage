from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

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
from app.server_v2.application.execution import ProcessExecution
from app.server_v2.application.catalog import CatalogService
from app.server_v2.application.conversations import ConversationService
from app.server_v2.application.credentials import CredentialService
from app.server_v2.application.identity import IdentityService
from app.server_v2.application.manifest import server_v2_manifest
from app.server_v2.application.official import install_sandbox
from app.server_v2.application.runs import RunService
from app.server_v2.application.skill_runtime import install_skill_driver
from app.server_v2.application.skills import SkillCatalogService
from app.server_v2.core.errors import ServerV2Error
from app.server_v2.core.settings import ServerV2Settings
from app.server_v2.domain.api_keys import ApiKeyRecord
from app.server_v2.infrastructure.a2a_client import A2APluginCache
from app.server_v2.infrastructure.mcp import McpPluginCache
from app.server_v2.infrastructure.models import (
    HostModelProvider,
    bind_model_user,
    reset_model_user,
)
from app.server_v2.infrastructure.storage import prepare_server_v2_storage

LOGGER = logging.getLogger(__name__)

# What a Run of this tenant's own Agents may reach for. These are Tool-layer
# scopes and are a different namespace from the ``agent.*`` scopes stored on an
# API key, which gate the HTTP surface instead. Tools that need one of these
# are still gated twice per call — by the Run's Tool grant and by the approval
# policy — so withholding them here would not add a check, it would only make a
# tenant's own MCP servers and A2A peers unusable from their own session.
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
        api_keys=None,
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
            self.users, catalog_store, self.threads = users, catalog, threads
            from app.server_v2.infrastructure.persistence.skills import MemorySkillStore

            self.skills = skills if skills is not None else MemorySkillStore()
        else:
            self.users, catalog_store, self.threads = _mysql_repositories(database)
            from app.server_v2.infrastructure.persistence.skills import DatabaseSkillStore

            self.skills = skills if skills is not None else DatabaseSkillStore(database)
        self.api_keys = api_keys if api_keys is not None else _api_key_store(database)
        self.identity = IdentityService(self.users)
        self.skill_catalog = SkillCatalogService(self.skills, self.paths.data_root)
        self.mcp_plugins = McpPluginCache()
        self.a2a_plugins = A2APluginCache()
        self.catalog = CatalogService(
            catalog_store,
            self.catalog_locks,
            mcp_plugins=self.mcp_plugins,
            a2a_plugins=self.a2a_plugins,
            skills=self.skill_catalog,
        )
        self.credentials = CredentialService(self.api_keys, self.catalog)
        self.execution = ProcessExecution(self)
        self.admission = RunAdmission(self)
        self.runs = RunService(self)
        self.conversations = ConversationService(self)
        self.admin = AdminService(self)
        self._fallback_model = model_provider
        self._host_models: HostModelProvider | None = None
        self._application: SAgentApplication | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        # Runs being driven on a background task, keyed by native run id. One
        # dict for every interface: a run id identifies a Run, not a protocol,
        # and driving the same Run twice would race two writers on its log.
        self._drives: dict[str, asyncio.Task[None]] = {}
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
        self.a2a_plugins.clear()
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
                scopes=TOOL_SCOPES,
            ),
            trace=TraceContext(correlation_id=correlation_id),
            language=self.settings.language,
        )

    async def username_for(self, user_id: str) -> str:
        user = await self.users.get_by_id(user_id)
        return user.username if user is not None else user_id

    def a2a_request_context(
        self, key: ApiKeyRecord, *, correlation_id: str | None = None
    ) -> RequestContext:
        """Build the actor for an inbound A2A call.

        The actor is the key's *owner*, identically to a browser request. The
        session store authorizes on the full triple
        ``(tenant_id, principal_type, principal_id)``, so giving the key its own
        principal identity would make every A2A thread unreadable from the web
        UI — and unreadable from a second key of the same user. The credential
        is recorded in ``delegated_by`` instead, which keeps it in the audit
        trail without partitioning the tenant's own data. Scopes come from the
        stored key, so a request body can never widen them.
        """

        return RequestContext(
            actor=ActorRef(
                principal_id=key.owner_user_id,
                principal_type=PrincipalType.USER,
                tenant_id=key.owner_user_id,
                delegated_by=key.key_id,
                # The key's own scopes gate this HTTP surface; the Tool-layer
                # ones are what the Agent behind it runs with, and are the same
                # either way because it is the same Agent the tenant configured.
                scopes=(*key.scopes, *TOOL_SCOPES),
            ),
            trace=TraceContext(correlation_id=correlation_id),
            language=self.settings.language,
        )

    def ensure_model_configured(self, catalog) -> None:
        """Fail a Run that has no model before it reaches the runtime."""

        if not self._has_configured_model(catalog):
            raise ServerV2Error(
                "validation",
                self._model_missing_message(),
            )

    @asynccontextmanager
    async def bound_model_session(self, *, user_id: str, session_id: str):
        """Scope a Run's model identity to one caller for the block's lifetime.

        Two bindings are needed and neither is redundant: the ContextVar covers
        calls made on this task, and the session binding covers calls the
        runtime makes from its own tasks, which resolve the user through the
        Run's Session instead.
        """

        token = bind_model_user(user_id)
        bound = False
        try:
            if self._host_models is not None:
                self._host_models.bind_session_user(session_id, user_id)
                bound = True
            yield
        finally:
            if bound and self._host_models is not None:
                self._host_models.unbind_session_user(session_id)
            reset_model_user(token)

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
                LOGGER.error("background task failed", exc_info=error)

        task.add_done_callback(_done)


def _api_key_store(database):
    from app.server_v2.infrastructure.persistence.api_keys import (
        DatabaseApiKeyStore,
        MemoryApiKeyStore,
    )

    return MemoryApiKeyStore() if database is None else DatabaseApiKeyStore(database)


def _mysql_repositories(database):
    if database is None:
        raise RuntimeError("MySQL is required")
    from app.server_v2.infrastructure.persistence import (
        DatabaseCatalogStore,
        DatabaseThreadIndex,
        DatabaseUserStore,
    )

    return (
        DatabaseUserStore(database),
        DatabaseCatalogStore(database),
        DatabaseThreadIndex(database),
    )
