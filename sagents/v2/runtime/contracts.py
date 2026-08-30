"""Ports exposed by the lifecycle Runtime to drivers and facades."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from sagents.v2.contracts.checkpoint import Checkpoint, Suspension
from sagents.v2.contracts.commands import (
    CancelRun,
    CommandReceipt,
    PauseRun,
    ReplyInteraction,
    ResumeRun,
    StartRun,
    SteerRun,
)
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.interactions import InteractionRequest
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunHandle,
    RunResult,
    RunSnapshot,
    SessionSnapshot,
)
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposal,
)
from sagents.v2.runtime.session.contracts import SessionStore


@dataclass
class RuntimeRunStream:
    """Raw Runtime observer returned by the low-level stream facade."""

    handle: RunHandle
    events: AsyncIterator[RuntimeEvent]

    async def detach(self) -> None:
        closer = getattr(self.events, "aclose", None)
        if closer is not None:
            await closer()


@dataclass(frozen=True)
class RuntimeSessionTreeEvent:
    """One demultiplexable observation from a Session tree subscription."""

    kind: Literal["session.discovered", "session.event"]
    session: SessionSnapshot
    run: RunSnapshot
    start_command: StartRun
    event: RuntimeEvent | None = None


class RuntimePort(Protocol):
    """Lifecycle operations consumed by Agent, Flow, and transport facades."""

    session_store: SessionStore

    async def start_run(
        self, command: StartRun, context: RequestContext
    ) -> RunHandle: ...

    async def stream(
        self, command: StartRun, context: RequestContext
    ) -> RuntimeRunStream: ...

    def subscribe_events(self, cursor: EventCursor) -> AsyncIterator[RuntimeEvent]: ...

    def subscribe_session_tree(
        self,
        session_id: str,
        *,
        cursors: dict[str, int] | None = None,
        include_root: bool = True,
    ) -> AsyncIterator[RuntimeSessionTreeEvent]: ...
    async def get_run(self, run_id: str) -> RunSnapshot: ...
    async def get_run_result(self, run_id: str) -> RunResult: ...

    async def propose_session_commit(
        self, command: ProposeSessionCommit, context: RequestContext
    ) -> SessionCommitProposal: ...

    async def publish_session_commit(
        self, command: PublishSessionCommit, context: RequestContext
    ) -> SessionCommitProposal: ...

    async def reject_session_commit(
        self, command: RejectSessionCommit, context: RequestContext
    ) -> SessionCommitProposal: ...

    async def start_execution(
        self,
        *,
        run_id: str,
        expected_revision: int,
        context: RequestContext,
        idempotency_key: str,
    ) -> RunSnapshot: ...

    async def pause_run(
        self, command: PauseRun, context: RequestContext
    ) -> CommandReceipt: ...

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
    ) -> RunSnapshot: ...

    async def resume_run(
        self, command: ResumeRun, context: RequestContext
    ) -> CommandReceipt: ...

    async def reply_interaction(
        self, command: ReplyInteraction, context: RequestContext
    ) -> CommandReceipt: ...

    async def mark_resumed(
        self,
        *,
        run_id: str,
        expected_revision: int,
        context: RequestContext,
        idempotency_key: str,
    ) -> RunSnapshot: ...

    async def steer_run(
        self, command: SteerRun, context: RequestContext
    ) -> CommandReceipt: ...

    async def cancel_run(
        self, command: CancelRun, context: RequestContext
    ) -> CommandReceipt: ...

    async def complete_run(
        self,
        *,
        run_id: str,
        expected_revision: int,
        context: RequestContext,
        idempotency_key: str,
    ) -> RunSnapshot: ...

    async def fail_run(
        self,
        *,
        run_id: str,
        expected_revision: int,
        error: RuntimeErrorInfo,
        context: RequestContext,
        idempotency_key: str,
    ) -> RunSnapshot: ...


__all__ = ["RuntimePort", "RuntimeRunStream"]
