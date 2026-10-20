"""Drive Sage Runs on background tasks shared by AG-UI and A2A."""

from __future__ import annotations

import asyncio
import hashlib
from time import perf_counter
from datetime import datetime, timedelta
from inspect import iscoroutinefunction
from weakref import WeakValueDictionary
from contextlib import asynccontextmanager

from app.v2.server.observability.logging import get_logger
from sagents.v2.contracts.commands import CancelRun, ReplyInteraction, ResumeRun, SteerRun, InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES, RunState
from sagents.v2.contracts.common import utc_now
from app.v2.server.runtime.policy import frozen_execution, live_execution_policy
from sagents.v2.runtime.observability.timing import log_duration

LOGGER = get_logger(__name__)


class RunService:
    def __init__(self, *, application, session_access, execution, users=None, keys=None, catalog=None, settings=None, host=None) -> None:
        # Only operations on the same physical workspace exclude one another.
        self._workspace_locks: WeakValueDictionary[tuple[str, str], asyncio.Lock] = WeakValueDictionary()
        self._workspace_owners = {}
        self.application = application
        self.session_access = session_access
        self.execution = execution
        self.users = users
        self.keys = keys
        self.catalog = catalog
        self.settings = settings
        self.host = host
        self._approval_scan_cursor = None
        self._approval_scan_end = None
        self._approval_scan_remaining = 0
        self.approval_scan_seconds = 5.0

    def workspace_lock(self, tenant_id: str, agent_id: str) -> asyncio.Lock:
        return self._workspace_locks.setdefault((tenant_id, agent_id), asyncio.Lock())

    @asynccontextmanager
    async def workspace_guard(self, tenant_id: str, agent_id: str):
        """One task may nest admission inside its ownership/index transaction."""
        key, task = (tenant_id, agent_id), asyncio.current_task()
        if self._workspace_owners.get(key) is task:
            yield
            return
        async with self.workspace_lock(*key):
            self._workspace_owners[key] = task
            try:
                yield
            finally:
                self._workspace_owners.pop(key, None)

    async def _load_run_agent(self, command, user_id):
        from app.v2.server.runtime.loop import load_catalog_agent
        if self.host is None:
            raise RuntimeError("Server capabilities have not been registered")
        with log_duration(LOGGER, "server.run.agent_load", "运行 Agent 加载结束",
                          session_id=command.session_id, attributes={"agent_id": command.agent_id}):
            return await load_catalog_agent(self.host, command, user_id)

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

        runtime = self.application.runtime
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

    async def steer_run(self, run_id, context, *, message_id, text):
        """Reuse the durable steering inbox and its safe-point delivery."""
        run = await self.session_access.get_run(run_id, context)
        content = text.strip()
        if not content:
            raise SageV2Error(RuntimeErrorInfo(
                code="server.conversations.steer.empty", category=ErrorCategory.VALIDATION,
                message="supplemental input must not be empty",
            ))
        inputs = (InputItem(role="user", content=(TextBlock(text=content),),
                            metadata={"web_message_id": message_id}),)
        # HTTP retries must reuse the accepted entry even after its Run revision
        # advances or completes; reconstructing a CAS command would change it.
        entries = await self.application.runtime.session_store.list_steers(run_id)
        for entry in entries:
            if any(item.metadata.get("web_message_id") == message_id for item in entry.input):
                if entry.input != inputs:
                    raise SageV2Error(RuntimeErrorInfo(
                        code="server.conversations.steer.conflict", category=ErrorCategory.CONFLICT,
                        message="messageId is already bound to different input",
                    ))
                return {"steer_id": entry.steer_id, "state": entry.status.value}
        events = await self.session_access.read_events(run_id, context)
        turn = next((event.turn_id for event in reversed(events) if event.type == "turn.started"), None)
        if run.state != RunState.RUNNING or turn is None:
            raise SageV2Error(RuntimeErrorInfo(
                code="server.conversations.steer.conflict", category=ErrorCategory.CONFLICT,
                message="Run is no longer accepting supplemental input",
            ))
        receipt = await self.application.runtime.steer_run(SteerRun(
            run_id=run_id, expected_revision=run.revision, expected_turn_id=turn,
            idempotency_key=f"web-steer:{hashlib.sha256(message_id.encode()).hexdigest()}", input=inputs,
        ), context)
        _accepted(receipt)
        return {"steer_id": receipt.result["steer_id"], "state": "pending"}

    async def resume_detached_run(
        self,
        run_id: str,
        context: RequestContext,
        *,
        user_id: str,
        session_id: str,
        label: str,
        decide=None,
        expected=None,
        performance_started_at: datetime | None = None,
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

        performance_started_at = performance_started_at or utc_now()
        access = self.session_access
        run = await access.get_run(run_id, context)
        if run.state != RunState.SUSPENDED or run.suspension_id is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="server.conversations.runs.conflict",
                    category=ErrorCategory.CONFLICT,
                    message=f"run is {run.state.value}, not waiting for input",
                )
            )
        suspension = await access.get_suspension(run.suspension_id, context)
        runtime = self.application.runtime
        if suspension.interaction_id is None:
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
            if expected is not None and expected != {
                "interaction_id": interaction.interaction_id,
                "revision": run.revision,
                "suspension_revision": suspension.expected_revision,
                "interaction_revision": interaction.expected_revision,
            }:
                raise SageV2Error(RuntimeErrorInfo(code="server.approval.conflict",
                    category=ErrorCategory.CONFLICT, message="Approval changed; refresh before deciding"))
            answer = decide(interaction) if decide is not None else None
            if answer is None:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="server.conversations.runs.validation",
                        category=ErrorCategory.VALIDATION,
                        message="the reply does not answer this interaction; allowed "
                        f"decisions are {', '.join(interaction.allowed_decisions)}",
                    )
                )
            decision, payload = answer
            await self._check_execution_grant(run, interaction, context, decision)
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
            performance_started_at=performance_started_at,
        )

    async def approval_expired(self, run, interaction) -> bool:
        command = await self.application.runtime.session_store.get_start_command(run.run_id)
        _, policy = frozen_execution(command)
        timeout = policy.approval_timeout_seconds
        if self.settings is not None:
            timeout = min(timeout, self.settings.approval_timeout_seconds)
        return (interaction.interaction_type.value == "approval"
                and utc_now() >= interaction.requested_at + timedelta(seconds=timeout))

    async def _check_execution_grant(self, run, interaction, context, decision):
        if await self.approval_expired(run, interaction):
            await self.cancel_run(run.run_id, context, expected_revision=run.revision,
                                  reason="approval_timeout")
            raise SageV2Error(RuntimeErrorInfo(code="server.approval.expired",
                category=ErrorCategory.CONFLICT, message="Approval expired; start a new task"))
        if self.keys is not None and decision not in {"deny", "cancel"}:
            command = await self.application.runtime.session_store.get_start_command(run.run_id)
            live = await live_execution_policy(command, users=self.users, keys=self.keys, catalog=self.catalog,
                settings=self.settings, user_id=context.actor.principal_id,
                package_authorizer=self.host.agent_management.authorize_package if self.host is not None else None,
                context=context)
            if live is None:
                raise SageV2Error(RuntimeErrorInfo(code="server.execution_grant.forbidden",
                    category=ErrorCategory.AUTHORIZATION, message="The originating execution grant is no longer valid"))

    async def expire_approvals(self, threads, context_for):
        """Advance a finite round; tail arrivals cannot starve older approvals.

        Return True when the same round still has pages. The host immediately
        schedules the next slice instead of sleeping a minute after every page.
        """
        if self._approval_scan_end is None:
            self._approval_scan_end, self._approval_scan_remaining = await threads.scan_snapshot()
            self._approval_scan_cursor = None
            if self._approval_scan_end is None or self._approval_scan_remaining <= 0:
                return False
        deadline = perf_counter() + max(0, self.approval_scan_seconds)
        while True:
            page = await threads.scan(limit=min(200, self._approval_scan_remaining), cursor=self._approval_scan_cursor,
                                      through=self._approval_scan_end)
            await self._expire_thread_approvals(page.items, context_for)
            self._approval_scan_remaining -= len(page.items)
            if page.next_cursor is None or self._approval_scan_remaining <= 0:
                self._approval_scan_cursor = self._approval_scan_end = None
                self._approval_scan_remaining = 0
                return False
            if page.next_cursor == self._approval_scan_cursor:
                raise RuntimeError("Approval scan cursor did not advance")
            self._approval_scan_cursor = page.next_cursor
            if perf_counter() >= deadline:
                return True
            await asyncio.sleep(0)

    async def _expire_thread_approvals(self, records, context_for):
        filter_waiting = getattr(self.application.runtime.session_store, "filter_suspended_session_ids", None)
        if iscoroutinefunction(filter_waiting):
            waiting = await filter_waiting([thread.thread_id for thread in records])
            records = [thread for thread in records if thread.thread_id in waiting]
        for thread in records:
            context = context_for(thread.user_id)
            try:
                runs = await self.session_access.list_session_runs(thread.thread_id, context)
                for run in runs:
                    if run.state != RunState.SUSPENDED or not run.suspension_id:
                        continue
                    suspension = await self.session_access.get_suspension(run.suspension_id, context)
                    if not suspension.interaction_id:
                        continue
                    interaction = await self.session_access.get_interaction(suspension.interaction_id, context)
                    if await self.approval_expired(run, interaction):
                        await self.cancel_run(run.run_id, context, expected_revision=run.revision,
                                              reason="approval_timeout")
            except SageV2Error as exc:
                LOGGER.warning("approval.expiration.skipped", "approval changed during cleanup",
                               thread_id=thread.thread_id, error_code=exc.info.code)

    async def continue_detached_run(
        self,
        run_id: str,
        context: RequestContext,
        *,
        user_id: str,
        session_id: str,
        label: str,
        performance_started_at: datetime | None = None,
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

        resume_started_at = performance_started_at or utc_now()
        from app.v2.server.storage.workspaces import workspace_user, workspace_agent_id, with_workspace_binding
        command = await self.session_access.get_start_command(run_id, context)
        command = await with_workspace_binding(command, user_id, self.host.threads if self.host is not None else None)
        workspace = (workspace_user(command, user_id), workspace_agent_id(command))
        async with self.workspace_guard(*workspace):
            run = await self.application.runtime.get_run(run_id)
            if run.state != RunState.RESUMING or self.execution.driving(run_id):
                return
            LOGGER.info("server.run.performance.resuming", "恢复运行性能计时起点",
                session_id=session_id, run_id=run_id,
                attributes={"started_at": resume_started_at.isoformat()})
            try:
                loaded = await self.application.agent_for_run(run_id, context)
                execution = await self.application.entrypoint().continue_run(run_id, context, agent=loaded)
            except BaseException as exc:
                LOGGER.info("server.run.performance.finished", "运行性能计时结束",
                    session_id=session_id, run_id=run_id,
                    attributes={"run_state": "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"})
                raise
            task = asyncio.create_task(
                self._continue_drive(execution, run_id=run_id, session_id=session_id, label=label),
                name=f"server-v2-{label}-resume-{run_id}",
            )
            self.execution.adopt(run_id, task, workspace=workspace)

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
        performance_started_at: datetime | None = None,
    ) -> str:
        """Start a Run that outlives the request which asked for it.

        The Run is driven on a background task rather than on the request's own
        task, because the Run is the record and the response is only one view of
        it: a client that hangs up mid-answer, or asks for the Task back
        immediately, must not abort work the agent has already begun.

        The SDK owns execution and the Run's model scope. This task observes
        its future and applies product completion callbacks after it settles.
        """

        from app.v2.server.storage.workspaces import workspace_user, workspace_agent_id
        from sagents.v2.contracts.principals import MemoryIdentity
        # The per-request SDK entry boundary precedes load/update/admission;
        # process startup and its one-time initialization happen elsewhere.
        request_started_at = performance_started_at or utc_now()
        context = context.model_copy(update={"memory_identity": MemoryIdentity(
            user_id=workspace_user(command, user_id), workspace_id=workspace_agent_id(command),
        )})
        started = perf_counter()
        workspace = (workspace_user(command, user_id), workspace_agent_id(command))
        async with self.workspace_guard(*workspace):
            LOGGER.debug("server.run.preparation.started", "开始准备运行",
                session_id=session_id, agent_id=command.agent_id,
                lock_wait_ms=round((perf_counter() - started) * 1000, 3))
            application = self.application
            loaded = await self._load_run_agent(command, user_id)
            command = command.model_copy(update={"agent_id": loaded.id, "resolved_spec_hash": loaded.composition_hash})
            with log_duration(LOGGER, "server.run.accepted", "运行接纳结束",
                              session_id=session_id, attributes={"interface": interface}):
                stream = await application.run_interface(
                    interface,
                    command,
                    context,
                    agent=loaded,
                )
            run_id = stream.handle.run_id
            if (
                self.execution.driving(run_id)
                or stream.handle.state in TERMINAL_RUN_STATES
                or stream.handle.state == RunState.SUSPENDED
            ):
                await stream.detach()
                return run_id
            LOGGER.info("server.run.performance.accepted", "运行性能计时起点",
                session_id=session_id, run_id=run_id,
                attributes={"agent_id": command.agent_id, "started_at": request_started_at.isoformat()})
            task = asyncio.create_task(
                self._drive(
                    stream,
                    session_id=session_id,
                    label=label,
                    on_finished=on_finished,
                ),
                name=f"server-v2-{label}-{run_id}",
            )
            self.execution.adopt(run_id, task, workspace=workspace)
            return run_id

    async def _drive(self, stream, *, session_id: str, label: str, on_finished) -> None:
        run_id = stream.handle.run_id
        try:
            snapshot = await stream.wait()
            LOGGER.info("server.run.performance.finished", "运行性能计时结束",
                session_id=session_id, run_id=run_id,
                attributes={"run_state": snapshot.state.value})
            if on_finished is not None:
                await on_finished(snapshot)
        except Exception as exc:
            LOGGER.exception(
                "run.background.failed",
                "background run crashed",
                exc,
                session_id=session_id,
                run_id=run_id,
                label=label,
            )
            LOGGER.info("server.run.performance.finished", "运行性能计时结束",
                session_id=session_id, run_id=run_id, attributes={"run_state": "failed"})
        finally:
            try:
                await stream.detach()
            finally:
                self.execution.release(run_id)

    async def _continue_drive(
        self, execution, *, run_id: str, session_id: str, label: str
    ) -> None:
        try:
            snapshot = await execution
            LOGGER.info("server.run.performance.finished", "运行性能计时结束",
                session_id=session_id, run_id=run_id,
                attributes={"run_state": snapshot.state.value})
        except Exception as exc:
            LOGGER.exception(
                "run.background_resume.failed",
                "background run resume crashed",
                exc,
                session_id=session_id,
                run_id=run_id,
                label=label,
            )
            LOGGER.info("server.run.performance.finished", "运行性能计时结束",
                session_id=session_id, run_id=run_id, attributes={"run_state": "failed"})
        finally:
            self.execution.release(run_id)


def _accepted(receipt) -> None:
    """Fail loudly when the runtime refused a command it was handed.

    Control commands report refusal in their receipt instead of raising, so a
    caller that ignores the receipt reports "cancelled" or "resumed" for a Run
    the runtime never touched. A duplicate is not a refusal: the command was
    already applied, which is the outcome the caller asked for.
    """

    if receipt.error is not None:
        raise SageV2Error(receipt.error)
