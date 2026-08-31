"""Public in-process facade for starting, driving, and observing v2 Runs.

This module owns execution-task lifetime only. Durable Run state belongs to the
SessionStore, so closing a stream or dropping an `SAgent` instance is not a
valid way to pause or cancel work.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunHandle,
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
from sagents.v2.runtime.contracts import RuntimePort
from sagents.v2.memory.service import MemoryService


LOGGER = logging.getLogger(__name__)


class RunDriver(Protocol):
    """Execution strategy selected by the host for one Run.

    Agent Loop and Flow both satisfy this shape. The facade deliberately does
    not know which strategy is behind the Run.
    """

    async def execute(self, run_id: str, context: RequestContext) -> RunSnapshot: ...
    async def resume(self, run_id: str, context: RequestContext) -> RunSnapshot: ...


DriverFactory = Callable[[str], RunDriver]


@dataclass
class SAgentRunStream:
    """Convenience bundle for a Run handle, observer, and local driver task."""

    handle: RunHandle
    events: AsyncIterator[RuntimeEvent]
    _execution: asyncio.Future[RunSnapshot]

    async def detach(self) -> None:
        """Detach only this observer; execution ownership stays with Runtime."""
        closer = getattr(self.events, "aclose", None)
        if closer is not None:
            await closer()

    async def wait(self) -> RunSnapshot:
        """Wait for this process's driver without transferring cancellation."""

        return await asyncio.shield(self._execution)


class SAgent:
    """High-level v2 facade with a Native event stream, never MessageChunk batches."""

    def __init__(
        self,
        *,
        runtime: RuntimePort,
        driver_factory: DriverFactory,
        memory_service: MemoryService | None = None,
        memory_scope: dict | None = None,
        owned_resources: tuple[object, ...] = (),
        dispatcher=None,
    ) -> None:
        self.runtime = runtime
        self.driver_factory = driver_factory
        self.memory_service = memory_service
        self.memory_scope = dict(memory_scope or {})
        self._owned_resources = owned_resources
        self._dispatcher = dispatcher
        self._tasks: dict[str, asyncio.Task[RunSnapshot]] = {}
        self._drivers: dict[str, RunDriver] = {}
        self._closed = False

    async def start_run(self, command: StartRun, context: RequestContext) -> RunHandle:
        """Accept a Run and start its driver without creating an observer."""

        self._ensure_open()
        command = self._with_memory_scope(command, context)
        handle = await self.runtime.start_run(command, context)
        if self._dispatcher is None:
            self._ensure_execution(handle.run_id, context, resume=False)
        else:
            await self._submit_or_fail(handle, context, resume=False)
        return handle

    async def run_stream(
        self, command: StartRun, context: RequestContext
    ) -> SAgentRunStream:
        """Accept, execute, and observe a Run through its next transport boundary."""

        self._ensure_open()
        command = self._with_memory_scope(command, context)
        handle = await self.runtime.start_run(command, context)
        execution = (
            self._ensure_execution(handle.run_id, context, resume=False)
            if self._dispatcher is None
            else await self._submit_or_fail(handle, context, resume=False)
        )
        return SAgentRunStream(
            handle=handle,
            events=self._terminal_stream(
                EventCursor(run_id=handle.run_id, run_sequence=0)
            ),
            _execution=execution,
        )

    def drive_accepted_run(
        self,
        handle: RunHandle,
        context: RequestContext,
        *,
        resume: bool = False,
    ) -> SAgentRunStream:
        """Attach a Host-composed driver after the Runtime allocated the Run ID.

        Hosts that provision Run-owned resources need the durable identity before
        driver composition. The handle must come from this facade's Runtime.
        """

        self._ensure_open()
        execution = self._ensure_execution(handle.run_id, context, resume=resume)
        return SAgentRunStream(
            handle=handle,
            events=self._terminal_stream(
                EventCursor(run_id=handle.run_id, run_sequence=0)
            ),
            _execution=execution,
        )

    async def schedule_accepted_run(
        self,
        handle: RunHandle,
        context: RequestContext,
        *,
        resume: bool = False,
    ) -> SAgentRunStream:
        """Submit an already accepted Run through the configured dispatcher."""

        self._ensure_open()
        if self._dispatcher is None:
            return self.drive_accepted_run(handle, context, resume=resume)
        execution = await self._dispatcher.submit(
            self, handle, context, resume=resume
        )
        return SAgentRunStream(
            handle=handle,
            events=self._terminal_stream(
                EventCursor(run_id=handle.run_id, run_sequence=0)
            ),
            _execution=execution,
        )

    async def propose_session_commit(
        self, command: ProposeSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Create a publication proposal for a completed snapshot Run."""

        self._ensure_open()
        return await self.runtime.propose_session_commit(command, context)

    async def publish_session_commit(
        self, command: PublishSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Publish reviewed snapshot history at an optimistic Session boundary."""

        self._ensure_open()
        proposal = await self.runtime.publish_session_commit(command, context)
        if self.memory_service is not None:
            run = await self.runtime.get_run(proposal.source_run_id)
            await self.memory_service.ingest_committed_run(
                run, context, self.runtime.session_store
            )
        return proposal

    async def reject_session_commit(
        self, command: RejectSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Reject a pending snapshot proposal without exposing its history."""

        self._ensure_open()
        return await self.runtime.reject_session_commit(command, context)

    async def continue_run(
        self, run_id: str, context: RequestContext
    ) -> asyncio.Future[RunSnapshot]:
        """Restart local execution after resume was durably accepted."""

        self._ensure_open()
        run = await self.runtime.get_run(run_id)
        if run.state != RunState.RESUMING:
            raise ValueError(f"run must be resuming, got {run.state.value}")
        if self._dispatcher is None:
            return self._ensure_execution(run_id, context, resume=True)
        return await self._submit_or_fail(run, context, resume=True)

    async def _submit_or_fail(self, run, context, *, resume):
        """Make an accepted scheduling failure a durable typed Run fact."""

        try:
            return await self._dispatcher.submit(
                self, run, context, resume=resume
            )
        except Exception as exc:
            current = await self.runtime.get_run(run.run_id)
            if current.state not in TERMINAL_RUN_STATES and current.state not in {
                RunState.SUSPENDED,
                RunState.SUSPEND_REQUESTED,
            }:
                error = (
                    exc.info
                    if isinstance(exc, SageV2Error)
                    else RuntimeErrorInfo(
                        code="scheduler.submit_failed",
                        category=ErrorCategory.RESOURCE_LOST,
                        message=str(exc),
                        safe_to_resume=True,
                    )
                )
                try:
                    await self.runtime.fail_run(
                        run_id=run.run_id,
                        expected_revision=current.revision,
                        error=error,
                        context=context,
                        idempotency_key=(
                            f"scheduler-submit-failed:{run.run_id}:"
                            f"{current.revision}"
                        ),
                    )
                except SageV2Error:
                    # A concurrent control command may already have moved the Run.
                    pass
            raise

    def attach_dispatcher(self, dispatcher) -> None:
        """Bind the Application-owned execution entrypoint exactly once."""

        if self._dispatcher is not None and self._dispatcher is not dispatcher:
            raise RuntimeError("SAgent already has an execution dispatcher")
        self._dispatcher = dispatcher

    def subscribe_events(self, cursor: EventCursor) -> AsyncIterator[RuntimeEvent]:
        """Observe an existing Run after an exclusive replay cursor."""

        self._ensure_open()
        return self._terminal_stream(cursor)

    async def close(self) -> None:
        """Release owned provider resources after every local Run has stopped."""

        if self._closed:
            return
        active = tuple(task for task in self._tasks.values() if not task.done())
        if active:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="agent.close_active_runs",
                    category=ErrorCategory.CONFLICT,
                    message="cannot close SAgent while local Runs are active",
                    safe_to_resume=True,
                )
            )
        for driver in tuple(self._drivers.values()):
            closer = getattr(driver, "close", None)
            if closer is None:
                continue
            result = closer()
            if inspect.isawaitable(result):
                await result
        self._drivers.clear()
        seen: set[int] = set()
        for resource in reversed(self._owned_resources):
            if id(resource) in seen:
                continue
            seen.add(id(resource))
            closer = getattr(resource, "close", None)
            if closer is None:
                continue
            result = closer()
            if inspect.isawaitable(result):
                await result
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="agent.closed",
                    category=ErrorCategory.RESOURCE_LOST,
                    message="SAgent is closed",
                    safe_to_resume=True,
                )
            )

    def _with_memory_scope(
        self, command: StartRun, context: RequestContext
    ) -> StartRun:
        """Freeze actor-owned Memory scope into the accepted Run command."""

        if not self.memory_scope.get("recall"):
            return command
        metadata = {
            **command.config.metadata,
            "memory_scope": {
                "tenant_id": context.actor.tenant_id,
                "principal_id": context.actor.principal_id,
                "scope": self.memory_scope.get("scope", "principal"),
                "limit": int(self.memory_scope.get("recall_limit", 8)),
            },
        }
        return command.model_copy(
            update={"config": command.config.model_copy(update={"metadata": metadata})}
        )

    def _ensure_execution(self, run_id, context, *, resume):
        # There may be many observers, but this facade owns at most one live
        # driver task per Run. Durable distributed single-executor ownership is
        # a scheduler/lease concern, not this in-process registry.
        current = self._tasks.get(run_id)
        if current is not None and not current.done():
            return current
        driver = self._drivers.get(run_id)
        if driver is None:
            driver = self.driver_factory(run_id)
            self._drivers[run_id] = driver
        task = asyncio.create_task(
            self._drive(driver, run_id, context, resume=resume),
            name=f"sagent-v2:{run_id}",
        )
        self._tasks[run_id] = task
        task.add_done_callback(
            lambda completed, key=run_id: self._discard_task(key, completed)
        )
        return task

    def _discard_task(self, run_id, completed):
        if self._tasks.get(run_id) is completed:
            self._tasks.pop(run_id, None)

    async def _drive(self, driver, run_id, context, *, resume):
        # A driver bug must become a typed terminal fact. Otherwise subscribers
        # can wait forever on a Run that remains RUNNING after its task crashed.
        try:
            result = (
                await driver.resume(run_id, context)
                if resume
                else await driver.execute(run_id, context)
            )
            if (
                self.memory_service is not None
                and result.state == RunState.COMPLETED
                and result.concurrency_mode.value != "snapshot_isolated"
            ):
                await self.memory_service.ingest_committed_run(
                    result, context, self.runtime.session_store
                )
        except asyncio.CancelledError:
            try:
                await self._close_driver(run_id, driver)
            except BaseException:
                LOGGER.exception("failed to close cancelled Run driver %s", run_id)
            raise
        except Exception as exc:
            result = await self._fail_driver_crash(run_id, exc, context)
        if result.state in TERMINAL_RUN_STATES or result.state == RunState.SUSPENDED:
            try:
                await self._close_driver(run_id, driver)
            except BaseException:
                # Terminal state is already an authoritative durable fact.
                # Resource cleanup failure must remain diagnostic rather than
                # changing a completed client outcome into an execution error.
                LOGGER.exception("failed to close terminal Run driver %s", run_id)
        return result

    async def _close_driver(self, run_id, driver) -> None:
        try:
            closer = getattr(driver, "close", None)
            if closer is not None:
                closed = closer()
                if inspect.isawaitable(closed):
                    await closed
        finally:
            if self._drivers.get(run_id) is driver:
                self._drivers.pop(run_id, None)

    async def _fail_driver_crash(self, run_id, exc, context):
        """Record a driver crash without overwriting a concurrent pause/cancel."""

        error = (
            exc.info
            if isinstance(exc, SageV2Error)
            else RuntimeErrorInfo(
                code="agent.driver_crashed",
                category=ErrorCategory.INTERNAL,
                message=str(exc),
                safe_to_resume=True,
            )
        )
        current = await self.runtime.get_run(run_id)
        if current.state in TERMINAL_RUN_STATES or current.state in {
            RunState.SUSPENDED,
            RunState.SUSPEND_REQUESTED,
        }:
            return current
        try:
            return await self.runtime.fail_run(
                run_id=run_id,
                expected_revision=current.revision,
                error=error,
                context=context,
                idempotency_key=f"driver-crashed:{run_id}:{current.revision}",
            )
        except SageV2Error:
            # One bounded reread/retry resolves the common race where the driver
            # emitted a final delta while another actor paused or cancelled it.
            latest = await self.runtime.get_run(run_id)
            if latest.state in TERMINAL_RUN_STATES or latest.state in {
                RunState.SUSPENDED,
                RunState.SUSPEND_REQUESTED,
            }:
                return latest
            return await self.runtime.fail_run(
                run_id=run_id,
                expected_revision=latest.revision,
                error=error,
                context=context,
                idempotency_key=f"driver-crashed:{run_id}:{latest.revision}",
            )

    async def _terminal_stream(self, cursor):
        """Stop at a response boundary, not merely at terminal Run states."""

        async for event in self.runtime.subscribe_events(cursor):
            yield event
            # Suspension is a transport boundary, not a terminal Run state. A
            # caller must be able to close this response, persist its cursor,
            # resolve the interaction (or explicitly resume), then subscribe
            # again without keeping the original HTTP connection alive.
            if event.type in {
                "run.suspended",
                "run.completed",
                "run.failed",
                "run.cancelled",
            }:
                return
