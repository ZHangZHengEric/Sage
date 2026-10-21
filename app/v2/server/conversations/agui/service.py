"""AG-UI chat: start, resume, list, and delete threads."""

from __future__ import annotations

import hashlib
import json
import asyncio
from time import perf_counter
from sagents.v2.contracts.common import utc_now

from app.v2.server.conversations.agui.mapping import to_start_run, validate_agui_id
from app.v2.server.conversations.agui.sse import (
    canonical_agui_sse,
    frame_to_agui_event,
    single_error_sse,
)
from app.v2.server.conversations.sessions import page_session_events
from app.v2.server.conversations.bindings import SessionBinding, require_binding
from app.v2.server.observability.context import get_request_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import MessageItemData, TextBlock
from sagents.v2.contracts.run_state import EventCursor, RunState, TERMINAL_RUN_STATES
from sagents.v2.interfaces.protocols.ag_ui import AgUiProtocolAdapter
from sagents.v2.runtime.observability import StructuredLogger, structured_log_context
from sagents.v2.runtime.observability.timing import log_duration


def _error(code, message, category=ErrorCategory.VALIDATION):
    return SageV2Error(
        RuntimeErrorInfo(
            code="server.chat." + code, category=category, message=message,
            metadata={"side_effect_state": "not_applied"}
        )
    )


def _external_run_key(session_id, client_run_id):
    return "external_" + hashlib.sha256((session_id + ":" + client_run_id).encode()).hexdigest()


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

    async def _legacy_scope_matches(self, session_id, legacy_id, owner_id, user_id, agent_id):
        context = self.context_for(owner_id)
        # Metadata pages omit inaccessible Sessions; an empty page alone does
        # not establish that this legacy Session is empty and may be claimed.
        await self.session_access.get_session(session_id, context)
        after, found = None, False
        while True:
            rows = await self.session_access.run_metadata_page([session_id], context,
                after=after, limit=200)
            for run in rows:
                found = True
                command = await self.session_access.get_start_command(run.run_id, context)
                tenant = command.config.metadata.get("server_v2.workspace_user_id")
                if (command.agent_id != agent_id or tenant not in {None, user_id}
                        or (tenant is None and session_id != legacy_id)):
                    return False
            if len(rows) < 200:
                return found or session_id == legacy_id
            last = rows[-1]
            after = (last.session_id, last.created_at.isoformat(), last.run_id)

    async def _find_client_run(self, session_id, client_run_id, context, *, external):
        keys = (_external_run_key(session_id, client_run_id), client_run_id) if external else (client_run_id,)
        for key in keys:
            found = await self.session_access.find_start_run(session_id, key, context)
            if found is not None:
                _, command = found
                if command.config.metadata.get("server_v2.external.run_id", command.idempotency_key) == client_run_id:
                    return found
        return None

    async def _scope(self, user_id, agent_id, session_id, *, for_start=False):
        if not user_id.strip() or not agent_id.strip():
            raise _error("invalid_identity", "user_id and agent_id are required")
        validate_agui_id(session_id, field="session_id")
        owner_id = await self.runs.catalog.agent_owner(agent_id)
        if owner_id is None:
            raise _error("agent_not_found", "agent not found")
        # Only probe the old hash for compatibility; never mint a hashed Session.
        identity = json.dumps([user_id, agent_id, session_id], ensure_ascii=False,
                              separators=(",", ":"))
        legacy_id = "external_" + hashlib.sha256(identity.encode()).hexdigest()
        for candidate in (legacy_id, session_id):
            record, binding = await asyncio.gather(
                self.threads.find(candidate), self.threads.binding(candidate),
            )
            if record is None and binding is None:
                try:
                    await self.session_access.get_session(candidate, self.context_for(owner_id))
                except SageV2Error as exc:
                    if exc.info.code.endswith("not_found"):
                        continue
                    raise _error("result_not_found", "run not found") from exc
            expected = SessionBinding(candidate, owner_id, user_id, agent_id)
            valid = record is None or (record.user_id == owner_id and record.agent_id == agent_id)
            if binding is not None:
                valid = valid and binding == expected
            elif valid:
                # Upgrade old bindings from durable Run metadata. A native
                # thread owned by the Agent owner is not an external tenant's.
                valid = await self._legacy_scope_matches(candidate, legacy_id, owner_id, user_id, agent_id)
            if not valid:
                if for_start:
                    require_binding(binding, expected)
                raise _error("result_not_found", "run not found")
            if binding is None and not for_start:
                await self.threads.bind(expected)
            return owner_id, candidate
        return owner_id, session_id

    async def result(self, *, user_id, session_id, agent_id=None, run_id=None):
        payload, _ = await self._result_with_native_run(
            user_id=user_id, session_id=session_id, agent_id=agent_id,
            run_id=run_id,
        )
        return payload

    async def _result_with_native_run(self, *, user_id, session_id,
                                      agent_id=None, run_id=None):
        owner, internal_id = user_id, session_id
        if agent_id is not None:
            owner, internal_id = await self._scope(user_id, agent_id, session_id)
        if agent_id is None:
            binding = await self.threads.binding(internal_id)
            if binding is not None and (binding.owner_id != user_id or binding.tenant_id != user_id):
                raise _error("result_not_found", "run not found")
        access = self.session_access
        context = self.context_for(owner)
        if run_id is None:
            command = await access.latest_session_start_command(internal_id, context)
            found = await access.find_start_run(internal_id, command.idempotency_key, context) if command else None
        else:
            found = await self._find_client_run(internal_id, run_id, context, external=agent_id is not None)
        if found is None:
            raise _error("result_not_found", "run not found")
        selected, command = found
        selected_run_id = command.config.metadata.get("server_v2.external.run_id", command.idempotency_key)
        payload = {
            "session_id": internal_id,
            "threadId": internal_id,
            "runId": selected_run_id,
            "state": selected.state.value,
            "text": "",
            "error": None,
        }
        if selected.state in TERMINAL_RUN_STATES:
            result = await access.get_run_result(selected.run_id, context)
            payload["error"] = (
                result.error.model_dump(mode="json") if result.error else None
            )
            if selected.state == RunState.COMPLETED:
                for item in reversed(result.final_items):
                    if (
                        isinstance(item.data, MessageItemData)
                        and item.data.role == "assistant"
                    ):
                        text = "".join(
                            block.text
                            for block in item.data.content
                            if isinstance(block, TextBlock)
                        )
                        if text.strip():
                            payload["text"] = text
                            break
        return payload, selected.run_id

    async def list_threads(self, user_id: str, *, limit=50, cursor=None, search="", agent_id=""):
        matches = ()
        if search.strip():
            summaries = await self.runs.catalog.list_agent_summaries([user_id])
            matches = tuple(item["id"] for item in summaries if search.strip().lower() in item.get("name", "").lower())
        return await self.threads.page(user_id=user_id, limit=limit, cursor=cursor,
            search=search, agent_id=agent_id, matching_agent_ids=matches)

    async def package_for_thread(self, thread_id, user_id):
        from app.v2.server.conversations.records import require_owned_thread
        require_owned_thread(await self.threads.find(thread_id), user_id)
        context = self.context_for(user_id)
        command = await self.session_access.latest_session_start_command(thread_id, context)
        if command is None:
            return None
        return command.config.metadata.get("server_v2.composition", {}).get("package")

    async def pending_approvals(self, user_id, *, limit=50, cursor=None):
        from datetime import timedelta
        from app.v2.server.runtime.policy import frozen_execution
        context = self.context_for(user_id)
        page = await self.threads.scan(user_id=user_id, limit=limit, cursor=cursor)
        threads = page.items
        filter_waiting = getattr(self.application.runtime.session_store, "filter_suspended_session_ids", None)
        if filter_waiting is not None:
            waiting = await filter_waiting([thread.thread_id for thread in threads])
            threads = [thread for thread in threads if thread.thread_id in waiting]
        views = await self.session_access.read_session_views(
            {thread.thread_id: context for thread in threads},
            suspended_only=True, skip_inaccessible=True,
        ) if threads else {}
        items = []
        for thread in threads:
            for view in views.get(thread.thread_id, ()):
                run, suspension, interaction = view.run, view.suspension, view.interaction
                if suspension is None or interaction is None:
                    continue
                if interaction.interaction_type.value != "approval":
                    continue
                _, policy = frozen_execution(view.command)
                timeout = min(policy.approval_timeout_seconds, self.runs.settings.approval_timeout_seconds)
                items.append({"run_id": run.run_id, "thread_id": thread.thread_id,
                    "title": thread.title or thread.thread_id,
                    "interaction": interaction.model_dump(mode="json"),
                    "expires_at": (interaction.requested_at + timedelta(seconds=timeout)).isoformat(),
                    "expected": {"interaction_id": interaction.interaction_id,
                        "revision": run.revision, "suspension_revision": suspension.expected_revision,
                        "interaction_revision": interaction.expected_revision}})
        return {"items": items, "next_cursor": page.next_cursor}

    async def decide_approval(self, run_id, *, user_id, decision, payload, expected):
        context = self.context_for(user_id)
        run = await self.session_access.get_run(run_id, context)
        await self.runs.resume_detached_run(run_id, context, user_id=user_id,
            session_id=run.session_id, label="approval",
            expected=expected,
            decide=lambda interaction: (decision, payload) if decision in interaction.allowed_decisions else None)
        return {"run_id": run_id, "session_id": run.session_id, "accepted": True}

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
        package = await self.package_for_thread(thread_id, record.user_id) if offset in (None, 0) else None
        return {
            "has_package": package is not None,
            "events": frames,
            "total": page.total,
            "offset": page.after_sequence,
            "limit": limit,
        }

    async def start(self, request, *, user_id: str, last_event_id: str | None = None,
                    agent_id: str | None = None, workspace_directory: str | None = None,
                    runtime_context: dict | None = None, package=None, api_key=None):
        started_at = perf_counter()
        performance_started_at = utc_now()
        logger = StructuredLogger(self.log_sink, "server_v2.agui").bind(correlation_id=get_request_id())
        if workspace_directory is not None:
            from app.v2.server.storage.external_workspaces import workspace_parts
            if agent_id is None:
                raise _error("workspace_requires_external_agent", "workspace directory requires an external Agent")
            try:
                workspace_directory = "/".join(workspace_parts(workspace_directory))
            except ValueError as exc:
                raise _error("invalid_workspace_path", "invalid workspace directory") from exc
        workspace_user_id = user_id
        stream_thread_id = stream_run_id = None
        if agent_id is not None:
            stream_thread_id, stream_run_id = request.thread_id, request.run_id
            validate_agui_id(stream_run_id, field="runId")
            with log_duration(logger, "server.admission.phase", "外部会话归属解析结束",
                              session_id=stream_thread_id, attributes={"phase": "external_scope"}):
                user_id, internal_id = await self._scope(user_id, agent_id, stream_thread_id, for_start=True)
            internal_run_id = _external_run_key(internal_id, stream_run_id)
            request = request.model_copy(update={
                "thread_id": internal_id, "run_id": internal_run_id,
                "forwarded_props": {**(request.forwarded_props or {}), "agentId": agent_id},
            })
        props = (
            request.forwarded_props if isinstance(request.forwarded_props, dict) else {}
        )
        requested_agent = str(props.get("agentId") or "").strip()
        thread_id = validate_agui_id(request.thread_id, field="threadId")
        with log_duration(logger, "server.admission.phase", "运行接纳参数准备结束",
                          session_id=thread_id, attributes={"phase": "prepare"}):
            admitted = await self.admission.prepare(
                user_id=user_id,
                session_id=thread_id,
                agent_id=requested_agent,
                pin_existing=True,
                package=package,
                tenant_id=workspace_user_id if agent_id is not None else None,
                key_id=api_key.key_id if api_key is not None else None,
            )
        enabled = tuple(item.name for item in admitted.skills)
        metadata = {**admitted.metadata, "server_v2.workspace_user_id": workspace_user_id}
        if runtime_context:
            if agent_id is None or len(runtime_context) > 32:
                raise _error("invalid_runtime_context", "invalid external runtime context")
            supplied_session = runtime_context.get("session_id")
            if supplied_session is not None and supplied_session != thread_id and supplied_session != stream_thread_id:
                raise _error("session_mismatch", "runtimeContext.session_id must match session_id")
            metadata["system_context"] = {**runtime_context, "session_id": thread_id}
        metadata["system_context"] = {**metadata.get("system_context", {}), "session_id": thread_id}
        if workspace_directory is not None:
            metadata["server_v2.external.workspace_path"] = workspace_directory
            metadata["working_directory"] = "/workspace/" + workspace_directory
        with log_duration(logger, "server.admission.phase", "运行命令构建结束",
                          session_id=thread_id, attributes={"phase": "command_build"}):
            thread_id, run_id, agent_id, command = to_start_run(
                request,
                composition_hash=self.application.composition_hash,
                default_agent_id=admitted.agent_id,
                enabled_skills=enabled,
                max_steps=admitted.max_steps,
                metadata=metadata,
            )
        if stream_run_id is not None:
            command = command.model_copy(update={"config": command.config.model_copy(update={
                "metadata": {**command.config.metadata, "server_v2.external.run_id": stream_run_id}})})
        if command.agent_id != admitted.agent_id:
            command = command.model_copy(update={"agent_id": admitted.agent_id})
            agent_id = admitted.agent_id
        if stream_run_id is not None:
            # Freeze retries to their original admitted command. Upgrades must
            # not change its idempotency digest or silently accept new input.
            previous = await self._find_client_run(thread_id, stream_run_id,
                self.context_for(user_id), external=True)
            if previous is not None:
                _, stored = previous
                old_context = dict(stored.config.metadata.get("system_context") or {})
                new_context = dict(runtime_context or {})
                old_context.pop("session_id", None)
                new_context.pop("session_id", None)
                if (stored.input != command.input or stored.agent_id != command.agent_id
                        or stored.config.metadata.get("server_v2.external.workspace_path") != workspace_directory
                        or old_context != new_context):
                    raise _error("idempotency_conflict", "runId is already bound to a different request", ErrorCategory.CONFLICT)
                command = stored
        async with self.runs.workspace_guard(workspace_user_id, admitted.agent_id):
            # Validate and claim ownership before Run creation or workspace writes.
            with log_duration(logger, "server.admission.phase", "会话归属绑定结束",
                              session_id=thread_id, attributes={"phase": "thread_bind"}):
                await self.threads.bind(SessionBinding(
                    thread_id, user_id, workspace_user_id, admitted.agent_id,
                ))
            title = ""
            if command.input and command.input[0].content:
                title = getattr(command.input[0].content[0], "text", "")[:80]
            with log_duration(logger, "server.admission.phase", "会话索引保存结束",
                              session_id=thread_id, attributes={"phase": "thread_upsert"}):
                await self.threads.upsert(
                    thread_id, user_id, title=title, agent_id=admitted.agent_id
                )
            if not admitted.model_ready:
                return single_error_sse(
                    (
                        "请先在「模型」页配置模型后再发送"
                        if self.language.lower().startswith("zh")
                        else "Configure a model on the Models page before sending"
                    ),
                    code="server.model_not_configured", session_id=thread_id,
                )

            correlation_id = get_request_id()
            context = self.context_for(user_id, correlation_id=correlation_id)
            with structured_log_context(correlation_id=correlation_id):
                native_run_id = await self.runs.start_detached_run(
                    "ag-ui",
                    command,
                    context,
                    user_id=user_id,
                    session_id=thread_id,
                    label="agui",
                    performance_started_at=performance_started_at,
                    on_finished=self._agui_finished(
                        command,
                        thread_id=thread_id,
                        client_run_id=run_id,
                        user_id=user_id,
                        agent_id=admitted.agent_id,
                        started_at=started_at,
                    ),
                )
                events = self.session_access.subscribe_events(
                    EventCursor(run_id=native_run_id, run_sequence=0),
                    context,
                )
                return canonical_agui_sse(
                    events,
                    thread_id=thread_id,
                    run_id=stream_run_id or run_id,
                    last_event_id=last_event_id,
                    logger=StructuredLogger(self.log_sink, "server_v2.agui").bind(correlation_id=correlation_id),
                    started_at=started_at,
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

        performance_started_at = utc_now()
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
                performance_started_at=performance_started_at,
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

    async def _browser_run(self, thread_id: str, *, run_id: str, user_id: str):
        """Resolve an exact browser Run; never fall back to a newer Run."""
        from app.v2.server.conversations.records import require_owned_thread

        validate_agui_id(thread_id, field="threadId")
        validate_agui_id(run_id, field="runId")
        require_owned_thread(await self.threads.find(thread_id), user_id)
        binding = await self.threads.binding(thread_id)
        if binding is not None and (
            binding.owner_id != user_id or binding.tenant_id != user_id
        ):
            raise _error("not_found", "run not found")
        context = self.context_for(user_id)
        runs = await self.session_access.list_session_runs(thread_id, context)
        selected = next((run for run in runs if run.run_id == run_id), None)
        if selected is None:
            found = await self.session_access.find_start_run(thread_id, run_id, context)
            selected = found[0] if found is not None else None
        if selected is None:
            raise _error("not_found", "run not found")
        return selected, context

    async def steer(self, thread_id: str, *, run_id: str, user_id: str,
                    message_id: str, text: str):
        selected, context = await self._browser_run(thread_id, run_id=run_id, user_id=user_id)
        validate_agui_id(message_id, field="messageId")
        return await self.runs.steer_run(
            selected.run_id, context, message_id=message_id, text=text,
        )

    async def cancel(self, thread_id: str, *, run_id: str, user_id: str):
        """Cancel only the named Run in a browser user's own Session."""
        selected, context = await self._browser_run(thread_id, run_id=run_id, user_id=user_id)
        cancelled = selected.state not in TERMINAL_RUN_STATES
        if cancelled:
            await self.runs.cancel_run(
                selected.run_id, context, expected_revision=selected.revision,
            )
        return {"session_id": thread_id, "runId": run_id, "cancelled": cancelled}

    async def delete(self, thread_id: str, user_id: str, *, admin: bool = False) -> None:
        from app.v2.server.conversations.cleanup import require_idle, reject_local_workspace_drive
        from app.v2.server.storage.workspaces import with_workspace_binding, workspace_user
        record = await self.threads.find(thread_id)
        if record is None or (not admin and record.user_id != user_id):
            raise _error("not_found", "thread not found")
        context = self.context_for(record.user_id)
        try:
            command = await self.session_access.latest_session_start_command(thread_id, context)
        except SageV2Error as exc:
            if not exc.info.code.endswith("not_found"):
                raise
            command = None
        tenant, agent_id = record.user_id, record.agent_id
        if command is not None:
            command = await with_workspace_binding(command, record.user_id, self.threads)
            tenant = workspace_user(command, record.user_id)
        reject_local_workspace_drive(self, tenant, agent_id)
        async with self.runs.workspace_guard(tenant, agent_id):
            await require_idle(self, tenant, agent_id, owner_id=record.user_id)
            current = await self.threads.find(thread_id)
            if current is None or current.user_id != record.user_id:
                raise _error("not_found", "thread not found")
            try:
                await self.session_access.delete_session(thread_id, context)
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
        started_at: float,
    ):
        logger = StructuredLogger(self.log_sink, "server_v2.agui").bind(
            thread_id=thread_id, run_id=client_run_id
        )
        logger.info(
            "agui.run.started",
            "AG-UI run started",
            attributes={"agent_id": agent_id, "user_id": user_id,
                        "preparation_ms": round((perf_counter() - started_at) * 1000, 3)},
        )

        async def _finished(snapshot) -> None:
            from app.v2.server.storage.workspaces import workspace_user
            async with self.runs.workspace_guard(workspace_user(command, user_id), agent_id):
                await self.threads.upsert(thread_id, user_id, agent_id=agent_id)
            status = snapshot.state.value
            log_terminal = logger.warning if status == "failed" else logger.info
            log_terminal(f"agui.run.{status}", f"AG-UI run {status}",
                         attributes={"duration_ms": round((perf_counter() - started_at) * 1000, 3)})

        return _finished
