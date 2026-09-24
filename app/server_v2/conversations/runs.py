"""Drive Sage Runs on background tasks shared by AG-UI and A2A."""

from __future__ import annotations

import asyncio

from app.server_v2.observability.logging import get_logger
from app.server_v2.runtime.models import bind_model_user, reset_model_user
from sagents.v2.contracts.commands import CancelRun, ReplyInteraction, ResumeRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES, RunState

LOGGER = get_logger(__name__)


class RunService:
    def __init__(self, *, application, session_access, execution) -> None:
        self.application = application
        self.session_access = session_access
        self.execution = execution

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
        runtime = self.application.entrypoint().runtime
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
        if run.state != RunState.RESUMING or self.execution.driving(run_id):
            return
        token = bind_model_user(user_id)
        bound = False
        try:
            bound = self.execution.bind_model(session_id, user_id)
            execution = await agent.continue_run(run_id, context)
            task = asyncio.create_task(
                self._continue_drive(
                    execution, run_id=run_id, session_id=session_id, label=label
                ),
                name=f"server-v2-{label}-resume-{run_id}",
            )
            self.execution.adopt(run_id, task)
            bound = False
        finally:
            if bound:
                self.execution.unbind_model(session_id)
            reset_model_user(token)

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
            bound = self.execution.bind_model(session_id, user_id)
            application = self.application
            stream = await application.run_interface(
                interface,
                command,
                context,
                agent_id=application.resolved_plan.entrypoint_agent_id,
            )
            run_id = stream.handle.run_id
            if (
                self.execution.driving(run_id)
                or stream.handle.state in TERMINAL_RUN_STATES
                or stream.handle.state == RunState.SUSPENDED
            ):
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
            self.execution.adopt(run_id, task)
            bound = False
            return run_id
        finally:
            if bound:
                self.execution.unbind_model(session_id)
            reset_model_user(token)

    async def _drive(self, stream, *, session_id: str, label: str, on_finished) -> None:
        run_id = stream.handle.run_id
        try:
            snapshot = await stream.wait()
            if on_finished is not None:
                await on_finished(snapshot)
        except Exception as exc:
            LOGGER.exception(
                "run.background.failed",
                "background run crashed",
                exc,
                run_id=run_id,
                label=label,
            )
        finally:
            try:
                await stream.detach()
            finally:
                self.execution.unbind_model(session_id)
                self.execution.release(run_id)

    async def _continue_drive(
        self, execution, *, run_id: str, session_id: str, label: str
    ) -> None:
        try:
            await execution
        except Exception as exc:
            LOGGER.exception(
                "run.background_resume.failed",
                "background run resume crashed",
                exc,
                run_id=run_id,
                label=label,
            )
        finally:
            self.execution.unbind_model(session_id)
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
