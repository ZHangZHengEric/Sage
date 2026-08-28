"""Public in-process facade for starting, driving, and observing v2 Runs.

This module owns execution-task lifetime only. Durable Run state belongs to the
SessionStore, so closing a stream or dropping an `SAgent` instance is not a
valid way to pause or cancel work.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

from sagents.v2.contracts.commands import StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
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
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.memory.service import MemoryService


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
    _execution: asyncio.Task[RunSnapshot]

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
        runtime: HarnessRuntime,
        driver_factory: DriverFactory,
        memory_service: MemoryService | None = None,
        memory_scope: dict | None = None,
    ) -> None:
        self.runtime = runtime
        self.driver_factory = driver_factory
        self.memory_service = memory_service
        self.memory_scope = dict(memory_scope or {})
        self._tasks: dict[str, asyncio.Task[RunSnapshot]] = {}

    async def start_run(self, command: StartRun, context: RequestContext) -> RunHandle:
        """Accept a Run and start its driver without creating an observer."""

        command = self._with_memory_scope(command, context)
        handle = await self.runtime.start_run(command, context)
        self._ensure_execution(handle.run_id, context, resume=False)
        return handle

    async def run_stream(
        self, command: StartRun, context: RequestContext
    ) -> SAgentRunStream:
        """Accept, execute, and observe a Run through its next transport boundary."""

        command = self._with_memory_scope(command, context)
        handle = await self.runtime.start_run(command, context)
        execution = self._ensure_execution(handle.run_id, context, resume=False)
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

        return await self.runtime.propose_session_commit(command, context)

    async def publish_session_commit(
        self, command: PublishSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Publish reviewed snapshot history at an optimistic Session boundary."""

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

        return await self.runtime.reject_session_commit(command, context)

    async def continue_run(
        self, run_id: str, context: RequestContext
    ) -> asyncio.Task[RunSnapshot]:
        """Restart local execution after resume was durably accepted."""

        run = await self.runtime.get_run(run_id)
        if run.state != RunState.RESUMING:
            raise ValueError(f"run must be resuming, got {run.state.value}")
        return self._ensure_execution(run_id, context, resume=True)

    def subscribe_events(self, cursor: EventCursor) -> AsyncIterator[RuntimeEvent]:
        """Observe an existing Run after an exclusive replay cursor."""

        return self._terminal_stream(cursor)

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
        driver = self.driver_factory(run_id)
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
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            current = await self.runtime.get_run(run_id)
            if current.state in TERMINAL_RUN_STATES:
                return current
            return await self.runtime.fail_run(
                run_id=run_id,
                expected_revision=current.revision,
                error=RuntimeErrorInfo(
                    code="agent.driver_crashed",
                    category=ErrorCategory.INTERNAL,
                    message=str(exc),
                    safe_to_resume=True,
                ),
                context=context,
                idempotency_key=f"driver-crashed:{run_id}:{current.revision}",
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
