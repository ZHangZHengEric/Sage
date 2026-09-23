from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.contracts.commands import CancelRun, ReplyInteraction, ResumeRun
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
from app.server_v2.core.errors import ServerV2Error, map_error_info, map_sage_error
from app.server_v2.core.observability.context import get_request_id
from app.server_v2.core.settings import ServerV2Settings
from app.server_v2.domain.api_keys import ApiKeyRecord
from app.server_v2.domain.catalog import (
    enabled_a2a_agents,
    enabled_mcp_servers,
    require_agent,
)
from app.server_v2.domain.threads import resolve_thread_agent_id
from app.server_v2.services.composition import composition_metadata
from app.server_v2.services.a2a_client import A2APluginCache
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
            self.users, self.catalog, self.threads = users, catalog, threads
            from app.server_v2.repositories.skills import MemorySkillStore

            self.skills = skills if skills is not None else MemorySkillStore()
        else:
            self.users, self.catalog, self.threads = _mysql_repositories(database)
            from app.server_v2.repositories.skills import DatabaseSkillStore

            self.skills = skills if skills is not None else DatabaseSkillStore(database)
        self.api_keys = api_keys if api_keys is not None else _api_key_store(database)
        self.skill_catalog = SkillCatalogService(self.skills, self.paths.data_root)
        self.mcp_plugins = McpPluginCache()
        self.a2a_plugins = A2APluginCache()
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

    async def cancel_run(
        self,
        run_id: str,
        context: RequestContext,
        *,
        expected_revision: int,
        reason: str = "user_requested",
    ) -> None:
        """Ask a Run to stop, guarding the transition with the revision read.

        The revision is the caller's: passing it through rather than re-reading
        it here is what makes the cancel a compare-and-set against the state the
        caller decided on, so a Run that finished on its own in the meantime is
        reported as a conflict instead of being silently cancelled after the
        fact.
        """

        runtime = self.application.entrypoint().runtime
        receipt = await runtime.cancel_run(
            CancelRun(
                run_id=run_id,
                expected_revision=expected_revision,
                idempotency_key=f"cancel:{run_id}:{expected_revision}",
                reason=reason,
            ),
            context,
        )
        _accepted(receipt)

    async def resume_detached_run(
        self,
        run_id: str,
        context: RequestContext,
        *,
        user_id: str,
        session_id: str,
        label: str,
        decide=None,
    ) -> None:
        """Answer whatever a suspended Run is waiting on and put it back in flight.

        A suspension is either a question (an Interaction) or a plain barrier,
        and the two are resolved by different commands, so the suspension itself
        decides which one is sent rather than the caller guessing.

        ``decide`` is called with the pending Interaction and returns the
        ``(decision, payload)`` to answer it with. Passing a callback rather
        than a ready-made answer is what keeps the question and its answer on
        the same read: an answer chosen from an Interaction this method re-read
        afterwards could be answering a question that has since changed.
        """

        access = self.application.service("session.access")
        run = await access.get_run(run_id, context)
        if run.state != RunState.SUSPENDED or run.suspension_id is None:
            raise ServerV2Error(
                "conflict", f"run is {run.state.value}, not waiting for input"
            )
        suspension = await access.get_suspension(run.suspension_id, context)
        runtime = self.application.entrypoint().runtime
        if suspension.interaction_id is None:
            # A barrier with no question — a manual pause, or a safe point an
            # earlier process left behind. There is nothing to answer.
            receipt = await runtime.resume_run(
                ResumeRun(
                    run_id=run_id,
                    suspension_id=suspension.suspension_id,
                    expected_revision=run.revision,
                    expected_suspension_revision=suspension.expected_revision,
                    idempotency_key=f"resume:{run_id}:{run.revision}",
                ),
                context,
            )
        else:
            interaction = await access.get_interaction(
                suspension.interaction_id, context
            )
            answer = decide(interaction) if decide is not None else None
            if answer is None:
                raise ServerV2Error(
                    "validation",
                    "the reply does not answer this interaction; allowed "
                    f"decisions are {', '.join(interaction.allowed_decisions)}",
                )
            decision, payload = answer
            receipt = await runtime.reply_interaction(
                ReplyInteraction(
                    run_id=run_id,
                    suspension_id=suspension.suspension_id,
                    interaction_id=interaction.interaction_id,
                    expected_revision=run.revision,
                    expected_suspension_revision=suspension.expected_revision,
                    expected_interaction_revision=interaction.expected_revision,
                    decision=decision,
                    payload=payload,
                    idempotency_key=f"reply:{interaction.interaction_id}:{run.revision}",
                ),
                context,
            )
        _accepted(receipt)
        await self.continue_detached_run(
            run_id,
            context,
            user_id=user_id,
            session_id=session_id,
            label=label,
        )

    async def continue_detached_run(
        self,
        run_id: str,
        context: RequestContext,
        *,
        user_id: str,
        session_id: str,
        label: str,
    ) -> None:
        """Restart local execution of a Run whose resume was already accepted.

        Accepting a resume and running it are two steps on purpose: the durable
        transition is what a client's reply buys, and the execution that follows
        belongs to the server whether or not the client stays connected. So the
        continuation is driven on a background task, exactly as a fresh Run is.

        Doing nothing when the Run is not resuming is not a silent failure: a
        duplicate reply, or a concurrent one that won the race, leaves the Run
        already running under a drive that is someone else's.
        """

        agent = self.application.entrypoint()
        run = await agent.runtime.get_run(run_id)
        if run.state != RunState.RESUMING or run_id in self._drives:
            return
        token = bind_model_user(user_id)
        bound = False
        try:
            if self._host_models is not None:
                self._host_models.bind_session_user(session_id, user_id)
                bound = True
            execution = await agent.continue_run(run_id, context)
            task = asyncio.create_task(
                self._continue_drive(
                    execution, run_id=run_id, session_id=session_id, label=label
                ),
                name=f"server-v2-{label}-resume-{run_id}",
            )
            self._drives[run_id] = task
            self._track(task)
            bound = False
        finally:
            if bound and self._host_models is not None:
                self._host_models.unbind_session_user(session_id)
            reset_model_user(token)

    async def _continue_drive(
        self, execution, *, run_id: str, session_id: str, label: str
    ) -> None:
        try:
            await execution
        except Exception as exc:
            LOGGER.error(
                "background %s resume of run %s crashed", label, run_id, exc_info=exc
            )
        finally:
            if self._host_models is not None:
                self._host_models.unbind_session_user(session_id)
            self._drives.pop(run_id, None)

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
                a2a_agents=tuple(
                    item.name for item in enabled_a2a_agents(catalog)
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
        context = self.request_context(user_id, correlation_id=correlation_id)
        try:
            with structured_log_context(correlation_id=correlation_id):
                native_run_id = await self.start_detached_run(
                    "ag_ui",
                    command,
                    context,
                    user_id=user_id,
                    session_id=thread_id,
                    label="agui",
                    on_finished=self._agui_finished(
                        command,
                        thread_id=thread_id,
                        client_run_id=run_id,
                        user_id=user_id,
                        agent_id=agent_id,
                    ),
                )
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

    async def resume_agui_run(
        self,
        thread_id: str,
        *,
        run_id: str,
        user_id: str,
        decision: str,
        payload: dict,
        last_event_id: str | None,
    ):
        """Answer the question a thread is waiting on and stream what follows.

        The thread, not the client, says which Run is waiting: a thread has at
        most one Run in flight, and asking the caller to name it would let a
        stale tab answer a question two Runs ago. ``run_id`` is the AG-UI run
        identity for the stream this returns, which is the client's to choose,
        exactly as it is when starting a Run.
        """

        thread_id = validate_agui_id(thread_id, field="threadId")
        run_id = validate_agui_id(run_id, field="runId")
        thread = await self.threads.find(thread_id)
        if thread is None or thread.user_id != user_id:
            # Another user's thread is absent rather than forbidden, so thread
            # ids cannot be probed for existence.
            raise ServerV2Error("not_found", "thread not found")

        correlation_id = get_request_id()
        context = self.request_context(user_id, correlation_id=correlation_id)
        access = self.application.service("session.access")
        try:
            runs = await access.list_session_runs(thread_id, context)
        except SageV2Error as exc:
            raise map_sage_error(exc) from exc
        waiting = [item for item in runs if item.state == RunState.SUSPENDED]
        if not waiting:
            raise ServerV2Error("conflict", "this thread is not waiting for input")
        native = max(waiting, key=lambda item: item.created_at)
        restarted_after = native.last_run_sequence

        with structured_log_context(correlation_id=correlation_id):
            await self.resume_detached_run(
                native.run_id,
                context,
                user_id=user_id,
                session_id=thread_id,
                label="agui",
                decide=lambda interaction: (
                    (decision, dict(payload))
                    if decision in interaction.allowed_decisions
                    else None
                ),
            )
            events = access.subscribe_events(
                EventCursor(run_id=native.run_id, run_sequence=0), context
            )
            return canonical_agui_sse(
                events,
                thread_id=thread_id,
                run_id=run_id,
                last_event_id=last_event_id,
                restarted_after=restarted_after,
            )

    async def start_detached_run(
        self,
        interface: str,
        command,
        context: RequestContext,
        *,
        user_id: str,
        session_id: str,
        label: str,
        on_finished=None,
    ) -> str:
        """Start a Run that outlives the request which asked for it.

        The Run is driven on a background task rather than on the request's own
        task, because the Run is the record and the response is only one view of
        it: a client that hangs up mid-answer, or asks for the Task back
        immediately, must not abort work the agent has already begun.

        The model binding is handed to that task along with the drive. The
        ContextVar travels because ``create_task`` copies the current context;
        the session binding is released by the drive, not here, which is why
        ``bound`` is cleared once the task owns it.
        """

        token = bind_model_user(user_id)
        bound = False
        try:
            if self._host_models is not None:
                self._host_models.bind_session_user(session_id, user_id)
                bound = True
            stream = await self.application.run_interface(
                interface,
                command,
                context,
                agent_id=self.application.resolved_plan.entrypoint_agent_id,
            )
            run_id = stream.handle.run_id
            if (
                run_id in self._drives
                or stream.handle.state in TERMINAL_RUN_STATES
                or stream.handle.state == RunState.SUSPENDED
            ):
                # Already finished, already waiting on input, or already being
                # driven by an earlier request that shared its idempotency key.
                await stream.detach()
                return run_id
            task = asyncio.create_task(
                self._drive(
                    stream,
                    session_id=session_id,
                    label=label,
                    on_finished=on_finished,
                ),
                name=f"server-v2-{label}-{run_id}",
            )
            self._drives[run_id] = task
            self._track(task)
            bound = False
            return run_id
        finally:
            if bound and self._host_models is not None:
                self._host_models.unbind_session_user(session_id)
            reset_model_user(token)

    async def _drive(
        self,
        stream,
        *,
        session_id: str,
        label: str,
        on_finished,
    ) -> None:
        run_id = stream.handle.run_id
        try:
            snapshot = await stream.wait()
            if on_finished is not None:
                await on_finished(snapshot)
        except Exception as exc:
            LOGGER.error(
                "background %s run %s crashed", label, run_id, exc_info=exc
            )
        finally:
            try:
                await stream.detach()
            finally:
                if self._host_models is not None:
                    self._host_models.unbind_session_user(session_id)
                self._drives.pop(run_id, None)

    def _agui_finished(
        self,
        command,
        *,
        thread_id: str,
        client_run_id: str,
        user_id: str,
        agent_id: str,
    ):
        logger = self._sagents_logger().bind(thread_id=thread_id, run_id=client_run_id)
        logger.info(
            "agui.run.started",
            "AG-UI run started",
            attributes={"agent_id": agent_id, "user_id": user_id},
        )

        async def _finished(snapshot) -> None:
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

        return _finished

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


def _accepted(receipt) -> None:
    """Fail loudly when the runtime refused a command it was handed.

    Control commands report refusal in their receipt instead of raising, so a
    caller that ignores the receipt reports "cancelled" or "resumed" for a Run
    the runtime never touched. A duplicate is not a refusal: the command was
    already applied, which is the outcome the caller asked for.
    """

    if receipt.error is not None:
        raise map_error_info(receipt.error)


def _api_key_store(database):
    from app.server_v2.repositories.api_keys import (
        DatabaseApiKeyStore,
        MemoryApiKeyStore,
    )

    return MemoryApiKeyStore() if database is None else DatabaseApiKeyStore(database)


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
