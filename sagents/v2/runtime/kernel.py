"""Transport-neutral command/query facade for the durable Run state machine.

`HarnessRuntime` does not execute prompts, tools, or Flow nodes. Drivers perform
that work and call this facade to make legal, atomic lifecycle transitions.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from sagents.v2.contracts.checkpoint import (
    Checkpoint,
    Suspension,
    SuspensionStatus,
)
from sagents.v2.contracts.commands import (
    CancelRun,
    CommandDecision,
    CommandReceipt,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    StartRun,
    SteerRun,
)
from sagents.v2.contracts.common import new_id
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.events import (
    CheckpointEventData,
    RunEventData,
    RuntimeEvent,
)
from sagents.v2.contracts.interactions import InteractionRequest
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunHandle,
    RunResult,
    RunSnapshot,
    RunState,
    TERMINAL_RUN_STATES,
)
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposal,
)
from sagents.v2.runtime.session.contracts import EventDraft, SessionStore
from sagents.v2.runtime.contracts import RuntimeRunStream, RuntimeSessionTreeEvent
from sagents.v2.i18n import error_recovery_payload, localize_error


class HarnessRuntime:
    """Transport-neutral asynchronous command/query/event facade.

    The Runtime is deliberately smaller than an Agent framework. It validates
    lifecycle commands and delegates atomic persistence to the SessionStore;
    Agent Loop, Flow, Scheduler, and application transports remain separate.

    Every persistence operation is typed against `SessionStore`. A custom
    backend may use SQL, a remote transactional service, or another durable
    store as long as it preserves the declared atomic lifecycle semantics.
    """

    def __init__(self, session_store: SessionStore, *, job_runtime=None) -> None:
        self.session_store = session_store
        self.job_runtime = job_runtime

    async def start_run(self, command: StartRun, context: RequestContext) -> RunHandle:
        """Accept a Run request; execution is started separately by a driver."""

        result = await self.session_store.create_run(command, context)
        return result.handle

    async def stream(
        self, command: StartRun, context: RequestContext
    ) -> RuntimeRunStream:
        """Accept a Run and attach a raw observer without starting a driver."""

        handle = await self.start_run(command, context)
        return RuntimeRunStream(
            handle=handle,
            events=self.subscribe_events(
                EventCursor(run_id=handle.run_id, run_sequence=0)
            ),
        )

    def subscribe_events(self, cursor: EventCursor) -> AsyncIterator[RuntimeEvent]:
        """Replay and then follow events after the supplied exclusive cursor."""

        return self.session_store.subscribe_events(cursor)

    async def subscribe_session_tree(
        self,
        session_id: str,
        *,
        cursors: dict[str, int] | None = None,
        include_root: bool = True,
    ) -> AsyncIterator[RuntimeSessionTreeEvent]:
        """Replay and follow a root Run plus every descendant Run.

        Each yielded value retains its own Session and Run identity. Consumers
        can therefore use one channel without mixing child sequence numbers or
        writing child events into the parent's canonical history.
        """

        root = await self.session_store.get_session(session_id)
        positions = dict(cursors or {})
        announced_runs: set[str] = set()
        while True:
            descendants = await self.session_store.list_descendant_sessions(
                session_id
            )
            sessions = ((root,) if include_root else ()) + descendants
            # A descendant can be created at any point while the root Run is
            # active. Keep a descendants-only subscription alive during that
            # window instead of treating an initially empty tree as complete.
            # Otherwise presentation clients race the first delegation: they
            # subscribe when the root stream opens, observe no children, and
            # permanently miss the child Session and all of its events.
            active = False
            if not include_root:
                root_runs = await self.session_store.list_session_runs(
                    root.session_id
                )
                if root_runs and root_runs[-1].state not in TERMINAL_RUN_STATES:
                    active = True
            for session in sessions:
                runs = await self.session_store.list_session_runs(session.session_id)
                if not runs:
                    continue
                run = runs[-1]
                command = await self.session_store.get_start_command(run.run_id)
                if run.run_id not in announced_runs:
                    announced_runs.add(run.run_id)
                    yield RuntimeSessionTreeEvent(
                        kind="session.discovered",
                        session=session,
                        run=run,
                        start_command=command,
                    )
                events = await self.session_store.read_events(
                    run.run_id, after_sequence=positions.get(run.run_id, 0)
                )
                for event in events:
                    positions[run.run_id] = event.run_sequence
                    yield RuntimeSessionTreeEvent(
                        kind="session.event",
                        session=session,
                        run=run,
                        start_command=command,
                        event=event,
                    )
                if run.state not in TERMINAL_RUN_STATES:
                    active = True
            if not active:
                return
            await asyncio.sleep(0.2)

    async def get_run(self, run_id: str) -> RunSnapshot:
        return await self.session_store.get_run(run_id)

    async def get_run_result(self, run_id: str) -> RunResult:
        return await self.session_store.get_run_result(run_id)

    async def propose_session_commit(
        self, command: ProposeSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Freeze a completed snapshot Run without publishing its history."""

        return await self.session_store.propose_session_commit(command, context)

    async def publish_session_commit(
        self, command: PublishSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Explicitly make a reviewed snapshot transcript canonical."""

        return await self.session_store.publish_session_commit(command, context)

    async def reject_session_commit(
        self, command: RejectSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Resolve a snapshot proposal without changing model-visible history."""

        return await self.session_store.reject_session_commit(command, context)

    async def start_execution(
        self,
        *,
        run_id: str,
        expected_revision: int,
        context: RequestContext,
        idempotency_key: str,
    ) -> RunSnapshot:
        """Claim a queued Run for execution and publish `run.started`."""

        result = await self.session_store.commit_run(
            run_id=run_id,
            expected_revision=expected_revision,
            expected_states={RunState.QUEUED},
            new_state=RunState.RUNNING,
            drafts=(
                EventDraft(type="run.started", data=RunEventData(state="running")),
            ),
            context=context,
            idempotency_key=idempotency_key,
        )
        return result.run

    async def pause_run(
        self, command: PauseRun, context: RequestContext
    ) -> CommandReceipt:
        """Request cooperative suspension; the driver commits the Checkpoint."""

        return await self._command_transition(
            command_idempotency_key=command.idempotency_key,
            run_id=command.run_id,
            expected_revision=command.expected_revision,
            expected_states={RunState.RUNNING},
            new_state=RunState.SUSPEND_REQUESTED,
            drafts=(
                EventDraft(
                    type="run.pause_requested",
                    data=RunEventData(state="suspend_requested", reason=command.reason),
                ),
            ),
            context=context,
        )

    async def commit_suspension(
        self,
        *,
        run_id: str,
        expected_revision: int,
        checkpoint: Checkpoint,
        suspension: Suspension,
        context: RequestContext,
        idempotency_key: str,
        interaction: InteractionRequest | None = None,
    ) -> RunSnapshot:
        """Atomically persist the resume boundary and enter SUSPENDED.

        Checkpoint, Suspension, optional InteractionRequest, and their events
        must share one SessionStore transaction. A partially recorded suspension
        would be observable but impossible to resume safely.
        """

        if self.job_runtime is not None:
            current = await self.session_store.get_run(run_id)
            if checkpoint.run_id != run_id or checkpoint.session_id != current.session_id:
                raise ValueError("checkpoint identity must match run and session")
            if suspension.run_id != run_id:
                raise ValueError("suspension.run_id must match run_id")
            if suspension.checkpoint_id != checkpoint.checkpoint_id:
                raise ValueError("suspension must reference the committed checkpoint")
            if interaction is not None:
                if interaction.run_id != run_id:
                    raise ValueError("interaction.run_id must match run_id")
                if suspension.interaction_id != interaction.interaction_id:
                    raise ValueError(
                        "suspension must reference the committed interaction"
                    )

            prepare_key = f"{idempotency_key}:prepare-job-pause"
            if current.state == RunState.RUNNING:
                prepared = await self.session_store.commit_run(
                    run_id=run_id,
                    expected_revision=expected_revision,
                    expected_states={RunState.RUNNING},
                    new_state=RunState.SUSPEND_REQUESTED,
                    drafts=(
                        EventDraft(
                            type="run.pause_requested",
                            data=RunEventData(
                                state="suspend_requested",
                                reason=suspension.reason.value,
                            ),
                        ),
                    ),
                    context=context,
                    idempotency_key=prepare_key,
                )
                expected_revision = prepared.run.revision
            elif current.state == RunState.SUSPEND_REQUESTED:
                if current.revision != expected_revision:
                    # A retry after the final suspension write failed must
                    # recover the durable preparation through its own key.
                    prepared = await self.session_store.commit_run(
                        run_id=run_id,
                        expected_revision=expected_revision,
                        expected_states={RunState.RUNNING},
                        new_state=RunState.SUSPEND_REQUESTED,
                        drafts=(
                            EventDraft(
                                type="run.pause_requested",
                                data=RunEventData(
                                    state="suspend_requested",
                                    reason=suspension.reason.value,
                                ),
                            ),
                        ),
                        context=context,
                        idempotency_key=prepare_key,
                    )
                    expected_revision = prepared.run.revision
            else:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="run.invalid_transition",
                        category=ErrorCategory.CONFLICT,
                        message=(
                            "cannot suspend Run while it is "
                            f"{current.state.value}"
                        ),
                        safe_to_resume=False,
                    )
                )
            await self.job_runtime.handle_run_pause(run_id)

        drafts: list[EventDraft] = [
            EventDraft(
                type="checkpoint.committed",
                data=CheckpointEventData(
                    checkpoint_id=checkpoint.checkpoint_id,
                    checkpoint_codec_version=checkpoint.checkpoint_codec_version,
                    run_sequence=checkpoint.run_sequence,
                    session_revision=checkpoint.session_revision,
                ),
            ),
            EventDraft(
                type="run.suspended",
                data=RunEventData(state="suspended", reason=suspension.reason.value),
            ),
        ]
        if interaction is not None:
            from sagents.v2.contracts.events import InteractionEventData

            drafts.insert(
                0,
                EventDraft(
                    type="interaction.requested",
                    interaction_id=interaction.interaction_id,
                    data=InteractionEventData(
                        interaction_id=interaction.interaction_id,
                        interaction_type=interaction.interaction_type.value,
                        state="requested",
                        allowed_decisions=interaction.allowed_decisions,
                        payload=interaction.payload,
                        revision=interaction.expected_revision,
                    ),
                ),
            )
        result = await self.session_store.commit_run(
            run_id=run_id,
            expected_revision=expected_revision,
            expected_states={RunState.RUNNING, RunState.SUSPEND_REQUESTED},
            new_state=RunState.SUSPENDED,
            drafts=tuple(drafts),
            context=context,
            idempotency_key=idempotency_key,
            checkpoint=checkpoint,
            suspension=suspension,
            interaction=interaction,
        )
        return result.run

    async def resume_run(
        self, command: ResumeRun, context: RequestContext
    ) -> CommandReceipt:
        """Accept explicit resume and move SUSPENDED to RESUMING."""

        command_id = new_id("command")
        try:
            result = await self.session_store.request_resume(command, context)
        except SageV2Error as exc:
            return CommandReceipt(
                command_id=command_id,
                decision=CommandDecision.REJECTED,
                target_id=command.run_id,
                error=self._command_error(exc.info, context.language),
            )
        return CommandReceipt(
            command_id=command_id,
            decision=(
                CommandDecision.DUPLICATE
                if result.duplicate
                else CommandDecision.ACCEPTED
            ),
            target_id=command.run_id,
            current_revision=result.run.revision,
            result={"state": result.run.state.value},
        )

    async def reply_interaction(
        self, command: ReplyInteraction, context: RequestContext
    ) -> CommandReceipt:
        """Resolve a pending interaction and prepare the same Run to resume."""

        command_id = new_id("command")
        try:
            result = await self.session_store.resolve_interaction(command, context)
        except SageV2Error as exc:
            return CommandReceipt(
                command_id=command_id,
                decision=CommandDecision.REJECTED,
                target_id=command.run_id,
                error=self._command_error(exc.info, context.language),
            )
        return CommandReceipt(
            command_id=command_id,
            decision=(
                CommandDecision.DUPLICATE
                if result.duplicate
                else CommandDecision.ACCEPTED
            ),
            target_id=command.run_id,
            current_revision=result.run.revision,
            result={
                "state": result.run.state.value,
                "interaction_id": command.interaction_id,
                "decision": command.decision,
            },
        )

    async def mark_resumed(
        self,
        *,
        run_id: str,
        expected_revision: int,
        context: RequestContext,
        idempotency_key: str,
    ) -> RunSnapshot:
        """Driver acknowledgement that checkpoint restoration may continue."""

        run = await self.session_store.get_run(run_id)
        suspension = None
        if run.suspension_id is not None:
            current = await self.session_store.get_suspension(run.suspension_id)
            suspension = current.model_copy(
                update={
                    "status": SuspensionStatus.RESOLVED,
                    "expected_revision": current.expected_revision + 1,
                }
            )
        result = await self.session_store.commit_run(
            run_id=run_id,
            expected_revision=expected_revision,
            expected_states={RunState.RESUMING},
            new_state=RunState.RUNNING,
            drafts=(
                EventDraft(type="run.resumed", data=RunEventData(state="running")),
            ),
            context=context,
            idempotency_key=idempotency_key,
            suspension=suspension,
        )
        return result.run

    async def steer_run(
        self, command: SteerRun, context: RequestContext
    ) -> CommandReceipt:
        """Append durable steering input; the driver claims it at a safe point."""

        command_id = new_id("command")
        try:
            result = await self.session_store.enqueue_steer(command, context)
        except SageV2Error as exc:
            return CommandReceipt(
                command_id=command_id,
                decision=CommandDecision.REJECTED,
                target_id=command.run_id,
                error=self._command_error(exc.info, context.language),
            )
        event = result.events[-1]
        return CommandReceipt(
            command_id=command_id,
            decision=(
                CommandDecision.DUPLICATE
                if result.duplicate
                else CommandDecision.ACCEPTED
            ),
            target_id=command.run_id,
            current_revision=result.run.revision,
            result={
                "state": result.run.state.value,
                "steer_id": event.data.steer_id,
                "inbox_sequence": event.data.inbox_sequence,
            },
        )

    async def cancel_run(
        self, command: CancelRun, context: RequestContext
    ) -> CommandReceipt:
        """Enter the terminal CANCELLED state; this does not delete the Session."""

        return await self._command_transition(
            command_idempotency_key=command.idempotency_key,
            run_id=command.run_id,
            expected_revision=command.expected_revision,
            expected_states={
                RunState.QUEUED,
                RunState.RUNNING,
                RunState.SUSPEND_REQUESTED,
                RunState.SUSPENDED,
                RunState.RESUMING,
            },
            new_state=RunState.CANCELLED,
            drafts=(
                EventDraft(
                    type="run.cancelled",
                    data=RunEventData(state="cancelled", reason=command.reason),
                ),
            ),
            context=context,
        )

    async def complete_run(
        self,
        *,
        run_id: str,
        expected_revision: int,
        context: RequestContext,
        idempotency_key: str,
    ) -> RunSnapshot:
        """Commit the successful terminal state for a driver."""

        result = await self.session_store.commit_run(
            run_id=run_id,
            expected_revision=expected_revision,
            expected_states={RunState.RUNNING},
            new_state=RunState.COMPLETED,
            drafts=(
                EventDraft(type="run.completed", data=RunEventData(state="completed")),
            ),
            context=context,
            idempotency_key=idempotency_key,
        )
        return result.run

    async def fail_run(
        self,
        *,
        run_id: str,
        expected_revision: int,
        error: RuntimeErrorInfo,
        context: RequestContext,
        idempotency_key: str,
    ) -> RunSnapshot:
        """Commit a typed terminal failure for a driver."""

        error = localize_error(error, context.language)
        if "recovery_questionnaire" not in error.metadata:
            error = error.model_copy(
                update={
                    "metadata": {
                        **error.metadata,
                        "recovery_questionnaire": error_recovery_payload(
                            error, context.language, resumable=False
                        ),
                    }
                }
            )
        result = await self.session_store.commit_run(
            run_id=run_id,
            expected_revision=expected_revision,
            expected_states={
                RunState.QUEUED,
                RunState.RUNNING,
                RunState.SUSPEND_REQUESTED,
                RunState.RESUMING,
            },
            new_state=RunState.FAILED,
            drafts=(
                EventDraft(
                    type="run.failed",
                    data=RunEventData(state="failed", error=error),
                ),
            ),
            context=context,
            idempotency_key=idempotency_key,
        )
        return result.run

    @staticmethod
    def _command_error(
        error: RuntimeErrorInfo, language: str | None
    ) -> RuntimeErrorInfo:
        localized = localize_error(error, language)
        return localized.model_copy(
            update={
                "metadata": {
                    **localized.metadata,
                    "recovery_questionnaire": error_recovery_payload(
                        localized,
                        language,
                        resumable=(
                            localized.safe_to_resume or localized.retryable
                        ),
                    ),
                }
            }
        )

    async def _command_transition(
        self,
        *,
        command_idempotency_key: str,
        run_id: str,
        expected_revision: int,
        expected_states: set[RunState],
        new_state: RunState,
        drafts: tuple[EventDraft, ...],
        context: RequestContext,
    ) -> CommandReceipt:
        command_id = new_id("command")
        try:
            result = await self.session_store.commit_run(
                run_id=run_id,
                expected_revision=expected_revision,
                expected_states=expected_states,
                new_state=new_state,
                drafts=drafts,
                context=context,
                idempotency_key=command_idempotency_key,
            )
        except SageV2Error as exc:
            return CommandReceipt(
                command_id=command_id,
                decision=CommandDecision.REJECTED,
                target_id=run_id,
                error=self._command_error(exc.info, context.language),
            )
        return CommandReceipt(
            command_id=command_id,
            decision=(
                CommandDecision.DUPLICATE
                if result.duplicate
                else CommandDecision.ACCEPTED
            ),
            target_id=run_id,
            current_revision=result.run.revision,
            result={"state": result.run.state.value},
        )

    @staticmethod
    def _rejected_receipt(run_id: str, error: RuntimeErrorInfo) -> CommandReceipt:
        return CommandReceipt(
            command_id=new_id("command"),
            decision=CommandDecision.REJECTED,
            target_id=run_id,
            error=error,
        )
