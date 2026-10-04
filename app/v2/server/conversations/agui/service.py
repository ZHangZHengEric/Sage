"""AG-UI chat: start, resume, list, and delete threads."""

from __future__ import annotations

from app.v2.server.conversations.agui.mapping import to_start_run, validate_agui_id
from app.v2.server.conversations.agui.sse import (
    canonical_agui_sse,
    frame_to_agui_event,
    single_error_sse,
)
from app.v2.server.conversations.sessions import page_session_events
from app.v2.server.observability.context import get_request_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.run_state import EventCursor, RunState
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.runtime.observability import StructuredLogger, structured_log_context


class ConversationService:
    def __init__(
        self,
        *,
        threads,
        admission,
        runs,
        application,
        session_access,
        log_sink,
        context_for,
        language: str,
    ) -> None:
        self.threads = threads
        self.admission = admission
        self.runs = runs
        self.language = language
        self.application = application
        self.session_access = session_access
        self.log_sink = log_sink
        self.context_for = context_for

    async def list_threads(self, user_id: str):
        return await self.threads.list_for(user_id)

    async def pending_approvals(self, user_id, *, limit=50, offset=0):
        from datetime import timedelta
        from app.v2.server.runtime.policy import frozen_execution
        context = self.context_for(user_id)
        threads = await self.threads.list_for(user_id)
        # Cursor pages scan a bounded set of threads, including empty pages.
        items = []
        for thread in threads[offset:offset + limit]:
            try:
                runs = await self.session_access.list_session_runs(thread.thread_id, context)
            except SageV2Error:
                continue
            for run in runs:
                if run.state != RunState.SUSPENDED or not run.suspension_id:
                    continue
                suspension = await self.session_access.get_suspension(run.suspension_id, context)
                if not suspension.interaction_id:
                    continue
                interaction = await self.session_access.get_interaction(suspension.interaction_id, context)
                if interaction.interaction_type.value != "approval":
                    continue
                command = await self.application.entrypoint().runtime.session_store.get_start_command(run.run_id)
                _, policy = frozen_execution(command)
                timeout = min(policy.approval_timeout_seconds, self.runs.settings.approval_timeout_seconds)
                items.append({"run_id": run.run_id, "thread_id": thread.thread_id,
                    "title": thread.title or thread.thread_id,
                    "interaction": interaction.model_dump(mode="json"),
                    "expires_at": (interaction.requested_at + timedelta(seconds=timeout)).isoformat(),
                    "expected": {"interaction_id": interaction.interaction_id,
                        "revision": run.revision, "suspension_revision": suspension.expected_revision,
                        "interaction_revision": interaction.expected_revision}})
        return {"items": items, "next_offset": offset + limit if len(threads) > offset + limit else None}

    async def decide_approval(self, run_id, *, user_id, decision, payload, expected):
        context = self.context_for(user_id)
        run = await self.session_access.get_run(run_id, context)
        await self.runs.resume_detached_run(run_id, context, user_id=user_id,
            session_id=run.session_id, label="approval",
            expected=expected,
            decide=lambda interaction: (decision, payload) if decision in interaction.allowed_decisions else None)
        return {"run_id": run_id, "accepted": True}

    async def events(
        self,
        thread_id: str,
        user_id: str,
        *,
        limit: int,
        offset,
        admin: bool = False,
    ):
        record = await self.threads.find(thread_id)
        if record is None or (not admin and record.user_id != user_id):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.agui.service.not_found",
                    category=ErrorCategory.VALIDATION,
                    message="thread not found",
                )
            )
        limit = max(1, min(int(limit), 2000))
        context = self.context_for(record.user_id)
        try:
            page = await page_session_events(
                self.session_access,
                thread_id,
                context,
                limit=limit,
                after_sequence=offset,
            )
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise
            return {"events": [], "total": 0, "offset": 0, "limit": limit}
        adapter = AgUiProtocolAdapter(enable_sage_extensions=True)
        frames: list[dict] = []
        for event in page.events:
            result = adapter.translate(event)
            for frame in result.frames:
                frames.append(
                    frame_to_agui_event(frame, thread_id=thread_id, run_id=event.run_id)
                )
        return {
            "events": frames,
            "total": page.total,
            "offset": page.after_sequence,
            "limit": limit,
        }

    async def start(self, request, *, user_id: str, last_event_id: str | None):
        props = (
            request.forwarded_props if isinstance(request.forwarded_props, dict) else {}
        )
        requested_agent = str(props.get("agentId") or "").strip()
        thread_id = validate_agui_id(request.thread_id, field="threadId")
        admitted = await self.admission.prepare(
            user_id=user_id,
            session_id=thread_id,
            agent_id=requested_agent,
            pin_existing=True,
        )
        enabled = tuple(item.name for item in admitted.skills)
        thread_id, run_id, agent_id, command = to_start_run(
            request,
            composition_hash=self.application.composition_hash,
            default_agent_id=admitted.agent_id,
            enabled_skills=enabled,
            metadata=admitted.metadata,
        )
        if command.agent_id != admitted.agent_id:
            command = command.model_copy(update={"agent_id": admitted.agent_id})
            agent_id = admitted.agent_id
        await self.threads.upsert(
            thread_id, user_id, title="", agent_id=admitted.agent_id
        )
        if not admitted.model_ready:
            return single_error_sse(
                (
                    "请先在「模型」页配置模型后再发送"
                    if self.language.lower().startswith("zh")
                    else "Configure a model on the Models page before sending"
                ),
                code="server.model_not_configured",
            )

        correlation_id = get_request_id()
        context = self.context_for(user_id, correlation_id=correlation_id)
        with structured_log_context(correlation_id=correlation_id):
            native_run_id = await self.runs.start_detached_run(
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
            events = self.session_access.subscribe_events(
                EventCursor(run_id=native_run_id, run_sequence=0),
                context,
            )
            return canonical_agui_sse(
                events,
                thread_id=thread_id,
                run_id=run_id,
                last_event_id=last_event_id,
            )

    async def resume(
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
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.agui.service.not_found",
                    category=ErrorCategory.VALIDATION,
                    message="thread not found",
                )
            )

        correlation_id = get_request_id()
        context = self.context_for(user_id, correlation_id=correlation_id)
        runs = await self.session_access.list_session_runs(thread_id, context)
        waiting = [item for item in runs if item.state == RunState.SUSPENDED]
        if not waiting:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.agui.service.conflict",
                    category=ErrorCategory.CONFLICT,
                    message="this thread is not waiting for input",
                )
            )
        native = max(waiting, key=lambda item: item.created_at)
        restarted_after = native.last_run_sequence

        with structured_log_context(correlation_id=correlation_id):
            await self.runs.resume_detached_run(
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
            events = self.session_access.subscribe_events(
                EventCursor(run_id=native.run_id, run_sequence=0), context
            )
            return canonical_agui_sse(
                events,
                thread_id=thread_id,
                run_id=run_id,
                last_event_id=last_event_id,
                restarted_after=restarted_after,
            )

    async def delete(
        self, thread_id: str, user_id: str, *, admin: bool = False
    ) -> None:
        record = await self.threads.find(thread_id)
        if record is None or (not admin and record.user_id != user_id):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.agui.service.not_found",
                    category=ErrorCategory.VALIDATION,
                    message="thread not found",
                )
            )
        try:
            await self.session_access.delete_session(
                thread_id, self.context_for(record.user_id)
            )
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise
        await self.threads.remove(thread_id, record.user_id)

    def _agui_finished(
        self,
        command,
        *,
        thread_id: str,
        client_run_id: str,
        user_id: str,
        agent_id: str,
    ):
        logger = StructuredLogger(self.log_sink, "server_v2.agui").bind(
            thread_id=thread_id, run_id=client_run_id
        )
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
