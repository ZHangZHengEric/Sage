"""AG-UI chat: start, resume, list, and delete threads."""

from __future__ import annotations

from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.run_state import EventCursor, RunState
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.runtime.observability import structured_log_context

from app.server_v2.adapters.agui.mapping import to_start_run, validate_agui_id
from app.server_v2.adapters.agui.sse import (
    canonical_agui_sse,
    frame_to_agui_event,
    single_error_sse,
)
from app.server_v2.core.errors import ServerError, map_sage_error
from app.server_v2.core.observability.context import get_request_id


class ConversationService:
    def __init__(self, *, threads, admission, sessions, runs, execution, runtime, context_for) -> None:
        self.threads = threads
        self.admission = admission
        self.sessions = sessions
        self.runs = runs
        self.execution = execution
        self.runtime = runtime
        self.context_for = context_for

    async def list_for(self, user_id: str):
        return await self.threads.list_for(user_id)

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
            raise ServerError("not_found", "thread not found")
        limit = max(1, min(int(limit), 2000))
        context = self.context_for(record.user_id)
        try:
            page = await self.sessions.page(
                thread_id, context, limit=limit, after_sequence=offset
            )
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise map_sage_error(exc) from exc
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
            composition_hash=self.runtime.composition_hash,
            default_agent_id=admitted.agent_id,
            enabled_skills=enabled,
            metadata=admitted.metadata,
        )
        if command.agent_id != admitted.agent_id:
            command = command.model_copy(update={"agent_id": admitted.agent_id})
            agent_id = admitted.agent_id
        await self.admission.remember(
            thread_id, user_id, title="", agent_id=admitted.agent_id
        )
        if not admitted.model_ready:
            return single_error_sse(
                self.execution.model_missing_message(),
                code="server.model_not_configured",
            )

        correlation_id = get_request_id()
        context = self.context_for(user_id, correlation_id=correlation_id)
        try:
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
                events = self.sessions.subscribe(
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
            raise ServerError("not_found", "thread not found")

        correlation_id = get_request_id()
        context = self.context_for(user_id, correlation_id=correlation_id)
        try:
            runs = await self.sessions.list_runs(thread_id, context)
        except SageV2Error as exc:
            raise map_sage_error(exc) from exc
        waiting = [item for item in runs if item.state == RunState.SUSPENDED]
        if not waiting:
            raise ServerError("conflict", "this thread is not waiting for input")
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
            events = self.sessions.subscribe(
                EventCursor(run_id=native.run_id, run_sequence=0), context
            )
            return canonical_agui_sse(
                events,
                thread_id=thread_id,
                run_id=run_id,
                last_event_id=last_event_id,
                restarted_after=restarted_after,
            )

    async def delete(self, thread_id: str, user_id: str, *, admin: bool = False) -> None:
        record = await self.threads.find(thread_id)
        if record is None or (not admin and record.user_id != user_id):
            raise ServerError("not_found", "thread not found")
        try:
            await self.sessions.delete(thread_id, self.context_for(record.user_id))
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise map_sage_error(exc) from exc
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
        logger = self.execution.sagents_logger().bind(
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
