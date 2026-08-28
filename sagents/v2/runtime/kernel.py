"""Transport-neutral command/query facade for the durable Run state machine.

`HarnessRuntime` does not execute prompts, tools, or Flow nodes. Drivers perform
that work and call this facade to make legal, atomic lifecycle transitions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

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
from sagents.v2.contracts.errors import RuntimeErrorInfo, SageV2Error
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
)
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposal,
)
from sagents.v2.runtime.session.ephemeral import EventDraft, EphemeralSessionStore
from sagents.v2.runtime.session.contracts import SessionStore


@dataclass
class RuntimeRunStream:
    """Repository event observer returned by the low-level Runtime facade."""

    handle: RunHandle
    events: AsyncIterator[RuntimeEvent]

    async def detach(self) -> None:
        closer = getattr(self.events, "aclose", None)
        if closer is not None:
            await closer()


class HarnessRuntime:
    """Transport-neutral asynchronous command/query/event facade.

    The Runtime is deliberately smaller than an Agent framework. It validates
    lifecycle commands and delegates atomic persistence to the SessionStore;
    Agent Loop, Flow, Scheduler, and application transports remain separate.

    Every persistence operation is typed against `SessionStore`. A custom
    backend may use SQL, a remote transactional service, or another durable
    store as long as it preserves the declared atomic lifecycle semantics.
    """

    def __init__(self, session_store: SessionStore | None = None) -> None:
        self.session_store = session_store or EphemeralSessionStore()

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
                error=exc.info,
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
                error=exc.info,
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
                error=exc.info,
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
                error=exc.info,
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
