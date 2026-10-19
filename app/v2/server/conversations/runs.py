"""Drive Sage Runs on background tasks shared by AG-UI and A2A."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta

from app.v2.server.observability.logging import get_logger
from app.v2.server.runtime.models import bind_model_user, reset_model_user
from sagents.v2.contracts.commands import CancelRun, ReplyInteraction, ResumeRun, SteerRun, InputItem
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import TERMINAL_RUN_STATES, RunState
from sagents.v2.contracts.common import utc_now
from app.v2.server.runtime.policy import frozen_execution, live_execution_policy

LOGGER = get_logger(__name__)


class RunService:
    def __init__(self, *, application, session_access, execution, users=None, keys=None, catalog=None, settings=None) -> None:
        # Serializes Run creation with destructive workspace/session operations.
        self.workspace_mutation_lock = asyncio.Lock()
        self.application = application
        self.session_access = session_access
        self.execution = execution
        self.users = users
        self.keys = keys
        self.catalog = catalog
        self.settings = settings
        self._agent_load_lock = asyncio.Lock()

    async def _load_run_agent(self, command, user_id):
        from app.v2.server.conversations.composition import load_composition
        from app.v2.server.config.manifest import server_v2_run_manifest
        from sagents.v2 import HostAgentExecution
        frozen = load_composition(command, user_id=user_id)
        if frozen is None:
            manifest = self.application.loaded_agents[0]._resolved
        else:
            manifest = frozen.package.resolved_manifest() if frozen.package is not None else server_v2_run_manifest(
                self.settings, agent=frozen.agent,
                registry=getattr(self.catalog, "extensions", None),
                skills=tuple(record.name for record in frozen.skills),
            )
        root = self.application.agent(self.application.resolved_plan.entrypoint_agent_id)
        execution = HostAgentExecution(
            driver_factory=root.driver_factory, spec_hash=command.resolved_spec_hash,
            runtime=self.application.runtime,
            dispatcher=self.application.service("execution.dispatcher"),
            agent_id=command.agent_id,
        )
        async with self._agent_load_lock:
            if frozen is not None:
                from app.v2.server.catalog.model_config import app_models
                models = command.config.metadata.get("server_v2.models")
                await self.application.update_models(models or app_models(await self.catalog.get(user_id)))
            current = next((value for value in self.application.loaded_agents
                            if value.package_id == (manifest.package_id if hasattr(manifest, "package_id") else manifest.metadata.id)), None)
            if current is None:
                return await self.application.load_agent(manifest, execution=execution)
            return await self.application.update_agent(agent=current, package=manifest, execution=execution)

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
                settings=self.settings, user_id=context.actor.principal_id)
            if live is None:
                raise SageV2Error(RuntimeErrorInfo(code="server.execution_grant.forbidden",
                    category=ErrorCategory.AUTHORIZATION, message="The originating execution grant is no longer valid"))

    async def expire_approvals(self, threads, context_for):
        """One host maintenance pass, no waiting task per approval."""
        for thread in await threads.list_all():
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

        agent = self.application.agent(self.application.resolved_plan.entrypoint_agent_id)
        run = await agent.runtime.get_run(run_id)
        if run.state != RunState.RESUMING or self.execution.driving(run_id):
            return
        token = bind_model_user(user_id)
        bound = False
        try:
            bound = self.execution.bind_model(session_id, user_id)
            command = await self.application.runtime.session_store.get_start_command(run_id)
            loaded = await self._load_run_agent(command, user_id)
            execution = await self.application.entrypoint().continue_run(run_id, context, agent=loaded)
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

        from app.v2.server.storage.workspaces import workspace_user
        from sagents.v2.contracts.principals import MemoryIdentity
        context = context.model_copy(update={"memory_identity": MemoryIdentity(
            user_id=workspace_user(command, user_id), workspace_id=command.agent_id,
        )})
        async with self.workspace_mutation_lock:
            token = bind_model_user(user_id)
            bound = False
            try:
                bound = self.execution.bind_model(session_id, user_id)
                application = self.application
                loaded = await self._load_run_agent(command, user_id)
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
