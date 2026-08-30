"""Single-Session storage boundary consumed by the SAgents v2 kernel.

The kernel deliberately does not define a global Session catalog. Applications
such as Desktop may maintain their own searchable index from lifecycle events,
while this port remains responsible for authoritative Run/Event/Checkpoint
semantics for a known ``session_id``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Collection, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from sagents.v2.contracts.checkpoint import Checkpoint, Suspension
from sagents.v2.contracts.commands import (
    ReplyInteraction,
    ResumeRun,
    StartRun,
    SteerInboxEntry,
    SteerRun,
)
from sagents.v2.contracts.common import Identifier
from sagents.v2.contracts.events import (
    EventData,
    EventDurability,
    EventSource,
    EventSourceType,
    RuntimeEvent,
)
from sagents.v2.contracts.interactions import (
    InteractionRequest,
    InteractionResolution,
)
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunHandle,
    RunResult,
    RunSnapshot,
    RunState,
    SessionSnapshot,
)
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposal,
)


@dataclass(frozen=True)
class EventDraft:
    """Unsequenced event submitted atomically through a :class:`SessionStore`.

    This is part of the storage port rather than any concrete store. Callers
    describe causality and payload while the implementation supplies identity,
    timestamps, sequence numbers, actor, and default source information.
    """

    type: str
    data: EventData
    durability: EventDurability | None = None
    turn_id: Identifier | None = None
    step_id: Identifier | None = None
    item_id: Identifier | None = None
    job_id: Identifier | None = None
    interaction_id: Identifier | None = None
    flow_execution_id: Identifier | None = None
    node_execution_id: Identifier | None = None
    causation_id: Identifier | None = None
    source: EventSource = EventSource(source_type=EventSourceType.RUNTIME)
    ignorable: bool = False


@dataclass(frozen=True)
class RunCreationResult:
    handle: RunHandle
    events: tuple[RuntimeEvent, ...]
    duplicate: bool = False


@dataclass(frozen=True)
class CommitResult:
    run: RunSnapshot
    session: SessionSnapshot
    events: tuple[RuntimeEvent, ...]
    duplicate: bool = False


@dataclass(frozen=True)
class SteerClaimResult:
    run: RunSnapshot
    entries: tuple[SteerInboxEntry, ...]
    events: tuple[RuntimeEvent, ...]


class SessionStoreCapabilities(Protocol):
    api_version: Literal["2"]
    transactional_run_events: bool
    transactional_suspension: bool
    durable_across_process_restart: bool
    supports_session_canonical_log: bool
    supports_bounded_subscription: bool


class SessionStore(Protocol):
    """Minimum versioned storage port consumed by the v2 Kernel.

    The store is both the Run state store and canonical event sequencer.
    Splitting those duties across independent non-transactional stores would let
    observable events disagree with resumable state.
    """

    api_version: Literal["2"]

    @property
    def capabilities(self) -> Mapping[str, bool | str]: ...

    async def create_run(
        self, command: StartRun, context: RequestContext
    ) -> RunCreationResult: ...

    async def get_run(self, run_id: str) -> RunSnapshot: ...
    async def get_run_result(self, run_id: str) -> RunResult: ...
    async def get_session(self, session_id: str) -> SessionSnapshot: ...
    async def get_start_command(self, run_id: str) -> StartRun: ...
    async def get_checkpoint(self, checkpoint_id: str) -> Checkpoint: ...
    async def get_suspension(self, suspension_id: str) -> Suspension: ...
    async def get_interaction(self, interaction_id: str) -> InteractionRequest: ...

    async def get_interaction_resolution(
        self, interaction_id: str
    ) -> InteractionResolution: ...

    async def delete_session(self, session_id: str) -> None:
        """Delete a Session and every descendant after all Runs are terminal."""

        ...

    async def list_descendant_sessions(
        self, session_id: str
    ) -> tuple[SessionSnapshot, ...]:
        """Return the authoritative child tree below ``session_id``."""

        ...

    async def list_session_runs(self, session_id: str) -> tuple[RunSnapshot, ...]: ...

    async def propose_session_commit(
        self, command: ProposeSessionCommit, context: RequestContext
    ) -> SessionCommitProposal: ...

    async def publish_session_commit(
        self, command: PublishSessionCommit, context: RequestContext
    ) -> SessionCommitProposal: ...

    async def reject_session_commit(
        self, command: RejectSessionCommit, context: RequestContext
    ) -> SessionCommitProposal: ...

    async def get_session_commit_proposal(
        self, proposal_id: str
    ) -> SessionCommitProposal: ...

    async def list_session_commit_proposals(
        self, session_id: str
    ) -> tuple[SessionCommitProposal, ...]: ...

    async def read_session_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]: ...

    async def read_events(
        self, run_id: str, *, after_sequence: int = 0, limit: int | None = None
    ) -> tuple[RuntimeEvent, ...]: ...

    async def read_fork_base_events(self, run_id: str) -> tuple[RuntimeEvent, ...]: ...

    async def get_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> Any | None: ...

    async def put_derived_state(
        self, session_id: str, namespace: str, key: str, value: Any
    ) -> None: ...

    async def delete_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> None: ...

    def subscribe_events(self, cursor: EventCursor) -> AsyncIterator[RuntimeEvent]: ...

    async def commit_run(
        self,
        *,
        run_id: str,
        expected_revision: int,
        expected_states: Collection[RunState],
        new_state: RunState,
        drafts: tuple[EventDraft, ...],
        context: RequestContext,
        idempotency_key: str,
        checkpoint: Checkpoint | None = None,
        suspension: Suspension | None = None,
        interaction: InteractionRequest | None = None,
    ) -> CommitResult: ...

    async def enqueue_steer(
        self, command: SteerRun, context: RequestContext
    ) -> CommitResult: ...

    async def claim_steers(
        self,
        *,
        run_id: str,
        expected_revision: int,
        turn_id: str,
        context: RequestContext,
    ) -> SteerClaimResult: ...

    async def resolve_interaction(
        self, command: ReplyInteraction, context: RequestContext
    ) -> CommitResult: ...

    async def request_resume(
        self, command: ResumeRun, context: RequestContext
    ) -> CommitResult: ...
