"""Atomic in-memory implementation of the v2 SessionStore semantics.

Although this class is used heavily in tests, it is a reference implementation,
not a mock: it defines sequencing, optimistic revisions, idempotency, suspension
transactions, steering, and bounded subscription behavior reused by the
filesystem implementation.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable, Collection
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sagents.v2.contracts.checkpoint import (
    Checkpoint,
    Suspension,
    SuspensionStatus,
)
from sagents.v2.contracts.commands import (
    ReplyInteraction,
    ResumeRun,
    StartRun,
    SteerInboxEntry,
    SteerInboxStatus,
    SteerRun,
)
from sagents.v2.contracts.common import Identifier, new_id, utc_now
from sagents.v2.contracts.errors import (
    ConflictError,
    ErrorCategory,
    NotFoundError,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.events import (
    EVENT_CATALOG,
    EventData,
    EventDurability,
    EventSource,
    EventSourceType,
    InteractionEventData,
    ItemEventData,
    RunEventData,
    RuntimeEvent,
    SessionCommitEventData,
    SteeringEventData,
)
from sagents.v2.contracts.interactions import (
    InteractionRequest,
    InteractionResolution,
    InteractionStatus,
)
from sagents.v2.contracts.principals import ActorRef, RequestContext
from sagents.v2.contracts.run_state import (
    EventCursor,
    RunHandle,
    RunResult,
    RunSnapshot,
    RunState,
    SessionConcurrencyMode,
    SessionSnapshot,
    TERMINAL_RUN_STATES,
)
from sagents.v2.contracts.session_commit import (
    ProposeSessionCommit,
    PublishSessionCommit,
    RejectSessionCommit,
    SessionCommitProposal,
    SessionCommitProposalStatus,
    SessionMergeStrategy,
)
from sagents.v2.contracts.items import (
    ArtifactRef,
    ItemSnapshot,
    ItemStatus,
    MessageItemData,
    UsageSummary,
)


SESSION_AGGREGATE_FORMAT = "sage.session-aggregate/v1"


@dataclass(frozen=True)
class EventDraft:
    """Unsequenced event payload submitted inside one SessionStore transaction.

    Callers describe causality and payload; the SessionStore supplies event id,
    timestamps, Run/Session sequence numbers, actor, and default source.
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


@dataclass
class _SessionRow:
    session_id: str
    revision: int
    last_sequence: int
    created_at: datetime
    updated_at: datetime
    active_serial_run_id: str | None = None
    parent_session_id: str | None = None
    # Maps optimistic Session revisions to the last durable event visible at
    # that revision. This turns a CAS revision into a stable replay boundary for
    # snapshot and fork context construction.
    revision_sequences: dict[int, int] = field(default_factory=lambda: {0: 0})


@dataclass
class _RunRow:
    session_id: str
    run_id: str
    state: RunState
    revision: int
    last_run_sequence: int
    concurrency_mode: SessionConcurrencyMode
    base_session_revision: int
    base_session_sequence: int
    accepted_session_revision: int
    resolved_spec_hash: str
    created_at: datetime
    updated_at: datetime
    suspension_id: str | None = None
    checkpoint_id: str | None = None
    start_command: StartRun | None = None


@dataclass(eq=False)
class _Subscriber:
    queue: asyncio.Queue[Any]
    last_delivered: int
    closed: bool = False


@dataclass(frozen=True)
class _SubscriptionOverflow:
    last_delivered: int
    latest_available: int


class EphemeralSessionStore:
    """Atomic in-memory reference implementation for the SessionStore contract.

    This implementation is intentionally useful rather than a mock: it provides
    optimistic revisions, canonical session/run sequencing, command idempotency,
    atomic checkpoint/interaction writes, and bounded async subscriptions.
    """

    api_version = "2"

    @property
    def capabilities(self) -> dict[str, bool | str]:
        return {
            "api_version": self.api_version,
            "transactional_run_events": True,
            "transactional_suspension": True,
            "durable_across_process_restart": False,
            "supports_session_canonical_log": True,
            "supports_bounded_subscription": True,
            "supports_snapshot_publication": True,
        }

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        subscriber_queue_size: int = 256,
    ) -> None:
        if subscriber_queue_size < 1:
            raise ValueError("subscriber_queue_size must be positive")
        self._clock = clock
        self._subscriber_queue_size = subscriber_queue_size
        self._lock = asyncio.Lock()
        self._sessions: dict[str, _SessionRow] = {}
        self._runs: dict[str, _RunRow] = {}
        self._run_events: dict[str, list[RuntimeEvent]] = {}
        self._session_events: dict[str, list[RuntimeEvent]] = {}
        # Fork history is copied at acceptance time. A child Session therefore
        # remains self-contained even when its parent is later deleted.
        self._fork_base_events: dict[str, tuple[RuntimeEvent, ...]] = {}
        # Derived state is explicitly non-authoritative and can be discarded.
        self._derived_state: dict[tuple[str, str, str], Any] = {}
        self._start_idempotency: dict[tuple[str | None, str, str], str] = {}
        self._start_idempotency_digests: dict[tuple[str | None, str, str], str] = {}
        self._command_results: dict[tuple[str, str], CommitResult] = {}
        self._command_digests: dict[tuple[str, str], str] = {}
        self._checkpoints: dict[str, Checkpoint] = {}
        self._suspensions: dict[str, Suspension] = {}
        self._interactions: dict[str, InteractionRequest] = {}
        self._interaction_resolutions: dict[str, InteractionResolution] = {}
        self._steer_inbox: dict[str, list[SteerInboxEntry]] = {}
        self._session_commit_proposals: dict[str, SessionCommitProposal] = {}
        # Idempotency is scoped to the command target plus key, mirroring Run
        # command behavior while allowing proposal and publication retries.
        self._session_commit_command_results: dict[
            tuple[str, str], SessionCommitProposal
        ] = {}
        self._session_commit_command_digests: dict[tuple[str, str], str] = {}
        self._subscribers: dict[str, set[_Subscriber]] = {}

    async def create_run(
        self, command: StartRun, context: RequestContext
    ) -> RunCreationResult:
        """Atomically accept one Run and write its initial canonical events.

        Session selection, concurrency checks, idempotency, Run identity, input
        Items, and `run.accepted`/`run.queued` must become visible together.
        """

        async with self._lock:
            # Start idempotency is scoped to tenant + principal + key. Reusing a
            # key with a different payload is a conflict, not a duplicate.
            idempotency_scope = (
                context.actor.tenant_id,
                context.actor.principal_id,
                command.idempotency_key,
            )
            existing_run_id = self._start_idempotency.get(idempotency_scope)
            if existing_run_id is not None:
                self._require_same_idempotent_request(
                    self._start_idempotency_digests[idempotency_scope],
                    self._digest(command.model_dump(mode="json")),
                )
                row = self._runs[existing_run_id]
                return RunCreationResult(
                    handle=self._handle(row), events=(), duplicate=True
                )

            now = self._clock()
            parent_session_id: str | None = None
            fork_base_revision: int | None = None
            fork_base_sequence: int | None = None
            fork_base_events: tuple[RuntimeEvent, ...] = ()
            if command.session_concurrency_mode == SessionConcurrencyMode.FORK:
                # Fork creates a new child Session at a stable parent revision;
                # the child Run never writes into the parent canonical log.
                assert command.session_id is not None
                parent = self._sessions.get(command.session_id)
                if parent is None:
                    raise self._not_found("session.not_found", command.session_id)
                parent_session_id = command.session_id
                fork_base_revision = (
                    parent.revision
                    if command.base_session_revision is None
                    else command.base_session_revision
                )
                if fork_base_revision > parent.revision:
                    raise self._conflict(
                        "session.revision_in_future",
                        f"fork base revision {fork_base_revision} exceeds parent revision {parent.revision}",
                    )
                fork_base_sequence = self._sequence_at_revision(
                    parent, fork_base_revision
                )
                fork_base_events = self._canonical_history_events_locked(
                    parent.session_id, fork_base_sequence
                )
                session_id = new_id("session")
            else:
                session_id = command.session_id or new_id("session")

            session = self._sessions.get(session_id)
            if session is None:
                session = _SessionRow(
                    session_id=session_id,
                    revision=0,
                    last_sequence=0,
                    created_at=now,
                    updated_at=now,
                    parent_session_id=parent_session_id,
                )
                self._sessions[session_id] = session

            requested_base = command.base_session_revision
            base_revision = (
                fork_base_revision
                if fork_base_revision is not None
                else session.revision
                if requested_base is None
                else requested_base
            )
            if (
                command.session_concurrency_mode != SessionConcurrencyMode.FORK
                and base_revision > session.revision
            ):
                raise self._conflict(
                    "session.revision_in_future",
                    f"base revision {base_revision} exceeds current revision {session.revision}",
                )
            if (
                command.session_concurrency_mode == SessionConcurrencyMode.SERIAL
                and base_revision != session.revision
            ):
                raise self._conflict(
                    "session.revision_conflict",
                    f"expected session revision {base_revision}, current {session.revision}",
                )
            if command.session_concurrency_mode == SessionConcurrencyMode.SERIAL:
                # Serial mode is both revision-strict and single-writer. A
                # suspended Run still owns the Session because it may resume.
                active = session.active_serial_run_id
                if (
                    active is not None
                    and self._runs[active].state not in TERMINAL_RUN_STATES
                ):
                    raise self._conflict(
                        "session.serial_run_active",
                        f"session {session_id} already has active serial run {active}",
                    )

            base_sequence = (
                fork_base_sequence
                if fork_base_sequence is not None
                else self._sequence_at_revision(session, base_revision)
            )

            run_id = new_id("run")
            session.revision += 1
            session.updated_at = now
            row = _RunRow(
                session_id=session_id,
                run_id=run_id,
                state=RunState.QUEUED,
                revision=0,
                last_run_sequence=0,
                concurrency_mode=command.session_concurrency_mode,
                base_session_revision=base_revision,
                base_session_sequence=base_sequence,
                accepted_session_revision=session.revision,
                resolved_spec_hash=command.resolved_spec_hash,
                created_at=now,
                updated_at=now,
                start_command=command,
            )
            self._runs[run_id] = row
            self._run_events[run_id] = []
            self._fork_base_events[run_id] = fork_base_events
            self._steer_inbox[run_id] = []
            self._session_events.setdefault(session_id, [])
            if command.session_concurrency_mode == SessionConcurrencyMode.SERIAL:
                session.active_serial_run_id = run_id

            input_drafts = []
            # Inputs are committed as normal completed message Items so replay
            # and projections do not need a second source for the opening turn.
            for input_item in command.input:
                item_id = new_id("item")
                data = MessageItemData(
                    role=input_item.role,
                    content=input_item.content,
                    metadata=input_item.metadata,
                )
                encoded = json.dumps(
                    data.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                item = ItemSnapshot(
                    item_id=item_id,
                    run_id=run_id,
                    status=ItemStatus.COMPLETED,
                    data=data,
                    content_hash=f"sha256:{hashlib.sha256(encoded).hexdigest()}",
                    created_at=now,
                    updated_at=now,
                )
                input_drafts.append(
                    EventDraft(
                        type="message.completed",
                        item_id=item_id,
                        data=ItemEventData(operation="completed", item=item),
                        source=EventSource(
                            source_type=EventSourceType.USER,
                            source_id=context.actor.principal_id,
                        ),
                    )
                )
            events = self._prepare_events_locked(
                row,
                session,
                (
                    EventDraft(
                        type="run.accepted", data=RunEventData(state="accepted")
                    ),
                    EventDraft(type="run.queued", data=RunEventData(state="queued")),
                    *input_drafts,
                ),
                context.actor,
                context.trace.correlation_id,
            )
            self._persist_events_locked(row, session, events)
            self._start_idempotency[idempotency_scope] = run_id
            self._start_idempotency_digests[idempotency_scope] = self._digest(
                command.model_dump(mode="json")
            )
            await self._commit_storage_locked(session_id)
            self._fanout_locked(run_id, events)
            return RunCreationResult(handle=self._handle(row), events=events)

    async def propose_session_commit(
        self, command: ProposeSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Freeze a completed snapshot Run into an auditable proposal.

        Proposal creation does not make model history visible. It only captures
        the exact source event set, its digest, and the canonical Runs that have
        advanced the Session since the snapshot base.
        """

        async with self._lock:
            key = (command.run_id, command.idempotency_key)
            digest = self._digest(command.model_dump(mode="json"))
            previous = self._session_commit_command_results.get(key)
            if previous is not None:
                self._require_same_idempotent_request(
                    self._session_commit_command_digests[key], digest
                )
                return previous

            row = self._runs.get(command.run_id)
            if row is None:
                raise self._not_found("run.not_found", command.run_id)
            if row.revision != command.expected_run_revision:
                raise self._conflict(
                    "run.revision_conflict",
                    f"expected run revision {command.expected_run_revision}, current {row.revision}",
                )
            if row.concurrency_mode != SessionConcurrencyMode.SNAPSHOT_ISOLATED:
                raise self._conflict(
                    "session.commit_requires_snapshot",
                    "only snapshot_isolated Runs can create Session commit proposals",
                )
            if row.state != RunState.COMPLETED:
                raise self._conflict(
                    "session.commit_run_not_completed",
                    f"snapshot Run must be completed, got {row.state.value}",
                )
            if any(
                value.source_run_id == row.run_id
                and value.status
                in {
                    SessionCommitProposalStatus.PENDING,
                    SessionCommitProposalStatus.PUBLISHED,
                }
                for value in self._session_commit_proposals.values()
            ):
                raise self._conflict(
                    "session.commit_proposal_exists",
                    f"snapshot Run {row.run_id} already has an active proposal",
                )

            session = self._sessions[row.session_id]
            source_events = tuple(
                event
                for event in self._run_events[row.run_id]
                if event.durability == EventDurability.DURABLE
                and not isinstance(event.data, SessionCommitEventData)
            )
            event_ids = tuple(event.event_id for event in source_events)
            now = self._clock()
            proposal = SessionCommitProposal(
                proposal_id=new_id("session_commit"),
                session_id=row.session_id,
                source_run_id=row.run_id,
                source_run_revision=row.revision,
                base_session_revision=row.base_session_revision,
                base_session_sequence=row.base_session_sequence,
                proposed_session_revision=session.revision + 1,
                proposed_session_sequence=session.last_sequence + 1,
                proposed_event_ids=event_ids,
                proposed_event_digest=self._digest(
                    [event.model_dump(mode="json") for event in source_events]
                ),
                conflicting_run_ids=self._session_commit_conflicts_locked(row),
                created_at=now,
                updated_at=now,
            )
            events = self._prepare_events_locked(
                row,
                session,
                (
                    EventDraft(
                        type="session.commit.proposed",
                        data=self._session_commit_event_data(proposal, "proposed"),
                    ),
                ),
                context.actor,
                context.trace.correlation_id,
            )
            row.revision += 1
            row.updated_at = now
            session.revision += 1
            session.updated_at = now
            self._session_commit_proposals[proposal.proposal_id] = proposal
            self._persist_events_locked(row, session, events)
            self._session_commit_command_results[key] = proposal
            self._session_commit_command_digests[key] = digest
            await self._commit_storage_locked(row.session_id)
            self._fanout_locked(row.run_id, events)
            return proposal

    async def publish_session_commit(
        self, command: PublishSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Make one snapshot transcript visible at an explicit merge point."""

        return await self._resolve_session_commit(
            command=command,
            context=context,
            publish=True,
        )

    async def reject_session_commit(
        self, command: RejectSessionCommit, context: RequestContext
    ) -> SessionCommitProposal:
        """Permanently reject one pending snapshot publication proposal."""

        return await self._resolve_session_commit(
            command=command,
            context=context,
            publish=False,
        )

    async def _resolve_session_commit(
        self,
        *,
        command: PublishSessionCommit | RejectSessionCommit,
        context: RequestContext,
        publish: bool,
    ) -> SessionCommitProposal:
        async with self._lock:
            key = (command.proposal_id, command.idempotency_key)
            digest = self._digest(
                {
                    "operation": "publish" if publish else "reject",
                    **command.model_dump(mode="json"),
                }
            )
            previous = self._session_commit_command_results.get(key)
            if previous is not None:
                self._require_same_idempotent_request(
                    self._session_commit_command_digests[key], digest
                )
                return previous

            proposal = self._session_commit_proposals.get(command.proposal_id)
            if proposal is None:
                raise self._not_found(
                    "session.commit_proposal_not_found", command.proposal_id
                )
            if proposal.revision != command.expected_proposal_revision:
                raise self._conflict(
                    "session.commit_proposal_revision_conflict",
                    f"expected proposal revision {command.expected_proposal_revision}, current {proposal.revision}",
                )
            if proposal.status != SessionCommitProposalStatus.PENDING:
                raise self._conflict(
                    "session.commit_proposal_resolved",
                    f"proposal is already {proposal.status.value}",
                )

            row = self._runs[proposal.source_run_id]
            session = self._sessions[proposal.session_id]
            source_events = tuple(
                event
                for event in self._run_events[row.run_id]
                if event.durability == EventDurability.DURABLE
                and not isinstance(event.data, SessionCommitEventData)
            )
            if publish and (
                tuple(event.event_id for event in source_events)
                != proposal.proposed_event_ids
                or self._digest(
                    [event.model_dump(mode="json") for event in source_events]
                )
                != proposal.proposed_event_digest
            ):
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session.commit_source_changed",
                        category=ErrorCategory.CORRUPT_STATE,
                        message=(
                            "snapshot source events no longer match the reviewed "
                            "proposal"
                        ),
                        safe_to_resume=False,
                    )
                )
            if session.revision != command.expected_session_revision:
                raise self._conflict(
                    "session.revision_conflict",
                    f"expected session revision {command.expected_session_revision}, current {session.revision}",
                )
            conflicts = self._session_commit_conflicts_locked(row)
            if (
                publish
                and command.merge_strategy
                == SessionMergeStrategy.REQUIRE_UNCHANGED_BASE
                and conflicts
            ):
                raise self._conflict(
                    "session.commit_merge_required",
                    "canonical Session history advanced after the snapshot base; "
                    "retry with append_after_current only after reviewing conflicts "
                    + ", ".join(conflicts),
                )

            now = self._clock()
            if publish:
                assert isinstance(command, PublishSessionCommit)
                updated = proposal.model_copy(
                    update={
                        "revision": proposal.revision + 1,
                        "status": SessionCommitProposalStatus.PUBLISHED,
                        "merge_strategy": command.merge_strategy,
                        "conflicting_run_ids": conflicts,
                        "published_session_revision": session.revision + 1,
                        "published_session_sequence": session.last_sequence + 1,
                        "updated_at": now,
                    }
                )
                event_type = "session.commit.published"
                state = "published"
            else:
                assert isinstance(command, RejectSessionCommit)
                updated = proposal.model_copy(
                    update={
                        "revision": proposal.revision + 1,
                        "status": SessionCommitProposalStatus.REJECTED,
                        "conflicting_run_ids": conflicts,
                        "rejection_reason": command.reason,
                        "updated_at": now,
                    }
                )
                event_type = "session.commit.rejected"
                state = "rejected"

            events = self._prepare_events_locked(
                row,
                session,
                (
                    EventDraft(
                        type=event_type,
                        data=self._session_commit_event_data(updated, state),
                    ),
                ),
                context.actor,
                context.trace.correlation_id,
            )
            row.revision += 1
            row.updated_at = now
            session.revision += 1
            session.updated_at = now
            self._session_commit_proposals[updated.proposal_id] = updated
            self._persist_events_locked(row, session, events)
            self._session_commit_command_results[key] = updated
            self._session_commit_command_digests[key] = digest
            await self._commit_storage_locked(row.session_id)
            self._fanout_locked(row.run_id, events)
            return updated

    async def get_session_commit_proposal(
        self, proposal_id: str
    ) -> SessionCommitProposal:
        async with self._lock:
            proposal = self._session_commit_proposals.get(proposal_id)
            if proposal is None:
                raise self._not_found("session.commit_proposal_not_found", proposal_id)
            return proposal

    async def list_session_commit_proposals(
        self, session_id: str
    ) -> tuple[SessionCommitProposal, ...]:
        async with self._lock:
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            return tuple(
                sorted(
                    (
                        value
                        for value in self._session_commit_proposals.values()
                        if value.session_id == session_id
                    ),
                    key=lambda value: (value.created_at, value.proposal_id),
                )
            )

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
    ) -> CommitResult:
        """CAS a Run state transition and append all related events atomically.

        `expected_revision` prevents stale drivers from publishing. The
        idempotency digest permits exact retries but rejects key reuse with a
        different transition. Checkpoint/Suspension/Interaction references are
        validated before any row or sequence is changed.
        """

        async with self._lock:
            command_key = (run_id, idempotency_key)
            command_digest = self._digest(
                {
                    "expected_revision": expected_revision,
                    "expected_states": sorted(state.value for state in expected_states),
                    "new_state": new_state.value,
                    "drafts": [self._dump_draft(value) for value in drafts],
                    "checkpoint": checkpoint.model_dump(mode="json")
                    if checkpoint
                    else None,
                    "suspension": suspension.model_dump(mode="json")
                    if suspension
                    else None,
                    "interaction": interaction.model_dump(mode="json")
                    if interaction
                    else None,
                }
            )
            previous = self._command_results.get(command_key)
            if previous is not None:
                self._require_same_idempotent_request(
                    self._command_digests[command_key], command_digest
                )
                return CommitResult(
                    run=previous.run,
                    session=previous.session,
                    events=previous.events,
                    duplicate=True,
                )
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            if row.revision != expected_revision:
                # Revision conflict is the local fencing mechanism: an old
                # worker cannot commit after another command advanced the Run.
                raise self._conflict(
                    "run.revision_conflict",
                    f"expected run revision {expected_revision}, current {row.revision}",
                )
            if row.state not in expected_states:
                expected = ", ".join(sorted(state.value for state in expected_states))
                raise self._conflict(
                    "run.invalid_transition",
                    f"cannot transition {row.state.value} to {new_state.value}; expected {expected}",
                )

            session = self._sessions[row.session_id]
            if suspension is not None and suspension.run_id != run_id:
                raise ValueError("suspension.run_id must match run_id")
            if checkpoint is not None and (
                checkpoint.run_id != run_id or checkpoint.session_id != row.session_id
            ):
                raise ValueError("checkpoint identity must match run and session")
            if interaction is not None and interaction.run_id != run_id:
                raise ValueError("interaction.run_id must match run_id")
            if suspension is not None and checkpoint is not None:
                if suspension.checkpoint_id != checkpoint.checkpoint_id:
                    raise ValueError(
                        "suspension must reference the committed checkpoint"
                    )
            if suspension is not None and interaction is not None:
                if suspension.interaction_id != interaction.interaction_id:
                    raise ValueError(
                        "suspension must reference the committed interaction"
                    )

            events = self._prepare_events_locked(
                row,
                session,
                drafts,
                context.actor,
                context.trace.correlation_id,
            )
            now = self._clock()
            row.state = new_state
            # A successful commit advances both Run and Session revisions even
            # when the state enum is unchanged, because canonical facts changed.
            row.revision += 1
            row.updated_at = now
            session.revision += 1
            session.updated_at = now
            if suspension is not None:
                self._suspensions[suspension.suspension_id] = suspension
                if suspension.status in {
                    SuspensionStatus.RESOLVED,
                    SuspensionStatus.CANCELLED,
                } or new_state not in {
                    RunState.SUSPENDED,
                    RunState.SUSPEND_REQUESTED,
                    RunState.RESUMING,
                }:
                    row.suspension_id = None
                else:
                    row.suspension_id = suspension.suspension_id
            elif new_state not in {RunState.SUSPENDED, RunState.SUSPEND_REQUESTED}:
                row.suspension_id = None
            if checkpoint is not None:
                self._checkpoints[checkpoint.checkpoint_id] = checkpoint
                row.checkpoint_id = checkpoint.checkpoint_id
            if interaction is not None:
                self._interactions[interaction.interaction_id] = interaction

            self._persist_events_locked(row, session, events)
            if new_state in TERMINAL_RUN_STATES:
                if session.active_serial_run_id == run_id:
                    session.active_serial_run_id = None
            result = CommitResult(
                run=self._run_snapshot(row),
                session=self._session_snapshot(session),
                events=events,
            )
            self._command_results[command_key] = result
            self._command_digests[command_key] = command_digest
            await self._commit_storage_locked(row.session_id)
            self._fanout_locked(run_id, events)
            return result

    async def get_run(self, run_id: str) -> RunSnapshot:
        async with self._lock:
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            return self._run_snapshot(row)

    async def get_run_result(self, run_id: str) -> RunResult:
        async with self._lock:
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            if row.state not in TERMINAL_RUN_STATES:
                raise self._conflict(
                    "run.result_not_ready",
                    f"run result is unavailable while run is {row.state.value}",
                )
            items = {}
            artifacts: dict[str, ArtifactRef] = {}
            input_tokens = output_tokens = cached_tokens = reasoning_tokens = 0
            cost_total = 0.0
            has_cost = False
            models: list[str] = []
            error = None
            for event in self._run_events[run_id]:
                data = event.data
                if data.kind == "item" and data.item is not None:
                    items[data.item.item_id] = data.item
                elif data.kind == "artifact":
                    if event.type == "artifact.deleted":
                        artifacts.pop(data.artifact.artifact_id, None)
                    else:
                        artifacts[data.artifact.artifact_id] = data.artifact
                elif data.kind == "usage":
                    input_tokens += data.usage.input_tokens
                    output_tokens += data.usage.output_tokens
                    cached_tokens += data.usage.cached_input_tokens
                    reasoning_tokens += data.usage.reasoning_tokens
                    if data.usage.cost is not None:
                        has_cost = True
                        cost_total += data.usage.cost
                    for model in data.usage.models:
                        if model not in models:
                            models.append(model)
                elif event.type == "run.failed" and data.kind == "run":
                    error = data.error
            return RunResult(
                session_id=row.session_id,
                run_id=row.run_id,
                outcome=row.state,
                final_items=tuple(items.values()),
                artifacts=tuple(artifacts.values()),
                usage=UsageSummary(
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_input_tokens=cached_tokens,
                    reasoning_tokens=reasoning_tokens,
                    cost=cost_total if has_cost else None,
                    models=tuple(models),
                ),
                error=error,
                completed_at=row.updated_at,
                final_cursor=EventCursor(
                    run_id=row.run_id, run_sequence=row.last_run_sequence
                ),
            )

    async def get_start_command(self, run_id: str) -> StartRun:
        async with self._lock:
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            if row.start_command is None:
                raise self._not_found("run.header_not_found", run_id)
            return row.start_command

    async def get_latest_checkpoint(self, run_id: str) -> Checkpoint:
        async with self._lock:
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            if row.checkpoint_id is None:
                raise self._not_found("checkpoint.not_found_for_run", run_id)
            return self._checkpoints[row.checkpoint_id]

    async def get_session(self, session_id: str) -> SessionSnapshot:
        async with self._lock:
            row = self._sessions.get(session_id)
            if row is None:
                raise self._not_found("session.not_found", session_id)
            return self._session_snapshot(row)

    async def delete_session(self, session_id: str) -> None:
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise self._not_found("session.not_found", session_id)
            run_ids = {
                row.run_id
                for row in self._runs.values()
                if row.session_id == session_id
            }
            active = [
                self._runs[run_id]
                for run_id in run_ids
                if self._runs[run_id].state not in TERMINAL_RUN_STATES
            ]
            if active:
                raise self._conflict(
                    "session.active_run",
                    f"session {session_id} has an active run",
                )
            removed_interactions = {
                interaction_id
                for interaction_id, value in self._interactions.items()
                if value.run_id in run_ids
            }
            self._sessions.pop(session_id)
            self._session_events.pop(session_id, None)
            for run_id in run_ids:
                self._runs.pop(run_id, None)
                self._run_events.pop(run_id, None)
                self._fork_base_events.pop(run_id, None)
                self._steer_inbox.pop(run_id, None)
                self._subscribers.pop(run_id, None)
            for scope, run_id in tuple(self._start_idempotency.items()):
                if run_id in run_ids:
                    self._start_idempotency.pop(scope, None)
                    self._start_idempotency_digests.pop(scope, None)
            for key in tuple(self._command_results):
                if key[0] in run_ids:
                    self._command_results.pop(key, None)
                    self._command_digests.pop(key, None)
            self._checkpoints = {
                key: value
                for key, value in self._checkpoints.items()
                if value.run_id not in run_ids
            }
            self._suspensions = {
                key: value
                for key, value in self._suspensions.items()
                if value.run_id not in run_ids
            }
            self._interactions = {
                key: value
                for key, value in self._interactions.items()
                if value.run_id not in run_ids
            }
            for interaction_id in removed_interactions:
                self._interaction_resolutions.pop(interaction_id, None)
            removed_proposals = {
                proposal_id
                for proposal_id, value in self._session_commit_proposals.items()
                if value.session_id == session_id
            }
            self._session_commit_proposals = {
                key: value
                for key, value in self._session_commit_proposals.items()
                if key not in removed_proposals
            }
            for key, value in tuple(self._session_commit_command_results.items()):
                if value.proposal_id in removed_proposals:
                    self._session_commit_command_results.pop(key, None)
                    self._session_commit_command_digests.pop(key, None)
            self._derived_state = {
                key: value
                for key, value in self._derived_state.items()
                if key[0] != session_id
            }
            await self._delete_storage_locked(session_id)

    async def list_session_runs(self, session_id: str) -> tuple[RunSnapshot, ...]:
        async with self._lock:
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            rows = sorted(
                (row for row in self._runs.values() if row.session_id == session_id),
                key=lambda row: (row.created_at, row.run_id),
            )
            return tuple(self._run_snapshot(row) for row in rows)

    async def read_session_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        async with self._lock:
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            events = [
                event
                for event in self._session_events[session_id]
                if (event.session_sequence or 0) > after_sequence
            ]
            if limit is not None:
                if limit < 1:
                    raise ValueError("limit must be positive")
                events = events[:limit]
            return tuple(events)

    async def read_events(
        self, run_id: str, *, after_sequence: int = 0, limit: int | None = None
    ) -> tuple[RuntimeEvent, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        async with self._lock:
            if run_id not in self._runs:
                raise self._not_found("run.not_found", run_id)
            events = [
                event
                for event in self._run_events[run_id]
                if event.run_sequence > after_sequence
            ]
            if limit is not None:
                if limit < 1:
                    raise ValueError("limit must be positive")
                events = events[:limit]
            return tuple(events)

    async def read_fork_base_events(self, run_id: str) -> tuple[RuntimeEvent, ...]:
        """Return the immutable parent-history copy captured for a fork Run."""

        async with self._lock:
            if run_id not in self._runs:
                raise self._not_found("run.not_found", run_id)
            return self._fork_base_events.get(run_id, ())

    async def get_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> Any | None:
        """Read rebuildable state without adding it to canonical history."""

        async with self._lock:
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            return self._derived_state.get((session_id, namespace, key))

    async def put_derived_state(
        self, session_id: str, namespace: str, key: str, value: Any
    ) -> None:
        async with self._lock:
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            self._derived_state[(session_id, namespace, key)] = value

    async def delete_derived_state(
        self, session_id: str, namespace: str, key: str
    ) -> None:
        async with self._lock:
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            self._derived_state.pop((session_id, namespace, key), None)

    async def get_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        async with self._lock:
            checkpoint = self._checkpoints.get(checkpoint_id)
            if checkpoint is None:
                raise self._not_found("checkpoint.not_found", checkpoint_id)
            return checkpoint

    async def get_suspension(self, suspension_id: str) -> Suspension:
        async with self._lock:
            suspension = self._suspensions.get(suspension_id)
            if suspension is None:
                raise self._not_found("suspension.not_found", suspension_id)
            return suspension

    async def get_interaction(self, interaction_id: str) -> InteractionRequest:
        async with self._lock:
            interaction = self._interactions.get(interaction_id)
            if interaction is None:
                raise self._not_found("interaction.not_found", interaction_id)
            return interaction

    async def get_interaction_resolution(
        self, interaction_id: str
    ) -> InteractionResolution:
        async with self._lock:
            resolution = self._interaction_resolutions.get(interaction_id)
            if resolution is None:
                raise self._not_found(
                    "interaction.resolution_not_found", interaction_id
                )
            return resolution

    async def enqueue_steer(
        self, command: SteerRun, context: RequestContext
    ) -> CommitResult:
        """Append ordered steering input without mutating the model ledger yet."""

        async with self._lock:
            command_key = (command.run_id, command.idempotency_key)
            command_digest = self._digest(command.model_dump(mode="json"))
            previous = self._command_results.get(command_key)
            if previous is not None:
                self._require_same_idempotent_request(
                    self._command_digests[command_key], command_digest
                )
                return CommitResult(
                    run=previous.run,
                    session=previous.session,
                    events=previous.events,
                    duplicate=True,
                )
            row = self._runs.get(command.run_id)
            if row is None:
                raise self._not_found("run.not_found", command.run_id)
            if row.revision != command.expected_revision:
                raise self._conflict(
                    "run.revision_conflict",
                    f"expected run revision {command.expected_revision}, current {row.revision}",
                )
            if row.state != RunState.RUNNING:
                raise self._conflict(
                    "run.invalid_transition",
                    f"steer requires running run, current {row.state.value}",
                )
            active_turn = self._active_turn_locked(command.run_id)
            if active_turn is not None and active_turn != command.expected_turn_id:
                raise self._conflict(
                    "steer.turn_conflict",
                    f"active turn is {active_turn!r}, not {command.expected_turn_id!r}",
                )
            inbox = self._steer_inbox.setdefault(command.run_id, [])
            entry = SteerInboxEntry(
                steer_id=new_id("steer"),
                run_id=command.run_id,
                expected_turn_id=command.expected_turn_id,
                inbox_sequence=len(inbox) + 1,
                input=command.input,
                mode=command.mode,
                created_at=self._clock(),
            )
            session = self._sessions[row.session_id]
            events = self._prepare_events_locked(
                row,
                session,
                (
                    EventDraft(
                        type="steer.accepted",
                        turn_id=command.expected_turn_id,
                        data=SteeringEventData(
                            steer_id=entry.steer_id,
                            state="accepted",
                            expected_turn_id=entry.expected_turn_id,
                            inbox_sequence=entry.inbox_sequence,
                        ),
                    ),
                ),
                context.actor,
                context.trace.correlation_id,
            )
            now = self._clock()
            row.revision += 1
            row.updated_at = now
            session.revision += 1
            session.updated_at = now
            inbox.append(entry)
            self._persist_events_locked(row, session, events)
            result = CommitResult(
                run=self._run_snapshot(row),
                session=self._session_snapshot(session),
                events=events,
            )
            self._command_results[command_key] = result
            self._command_digests[command_key] = command_digest
            await self._commit_storage_locked(row.session_id)
            self._fanout_locked(row.run_id, events)
            return result

    async def claim_steers(
        self,
        *,
        run_id: str,
        expected_revision: int,
        turn_id: str,
        context: RequestContext,
    ) -> SteerClaimResult:
        """Atomically mark pending steering as applied at a model safe point."""

        async with self._lock:
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            pending = tuple(
                entry
                for entry in self._steer_inbox.get(run_id, ())
                if entry.status == SteerInboxStatus.PENDING
                and entry.expected_turn_id == turn_id
            )
            if not pending:
                return SteerClaimResult(
                    run=self._run_snapshot(row), entries=(), events=()
                )
            if row.revision != expected_revision or row.state != RunState.RUNNING:
                raise self._conflict(
                    "run.revision_conflict",
                    "run changed before pending steering input could be applied",
                )
            now = self._clock()
            applied = tuple(
                entry.model_copy(
                    update={"status": SteerInboxStatus.APPLIED, "applied_at": now}
                )
                for entry in pending
            )
            replacements = {entry.steer_id: entry for entry in applied}
            self._steer_inbox[run_id] = [
                replacements.get(entry.steer_id, entry)
                for entry in self._steer_inbox[run_id]
            ]
            session = self._sessions[row.session_id]
            drafts: list[EventDraft] = []
            for entry in applied:
                drafts.append(
                    EventDraft(
                        type="steer.applied",
                        turn_id=turn_id,
                        data=SteeringEventData(
                            steer_id=entry.steer_id,
                            state="applied",
                            expected_turn_id=turn_id,
                            inbox_sequence=entry.inbox_sequence,
                        ),
                    )
                )
                # A claimed steer becomes conversation fact at this safe point.
                # Persist normal completed Message Items so restart recovery can
                # rebuild the model ledger without consulting mutable inbox rows.
                for input_item in entry.input:
                    item_id = new_id("item")
                    data = MessageItemData(
                        role=input_item.role,
                        content=input_item.content,
                        metadata={
                            **input_item.metadata,
                            "steer_id": entry.steer_id,
                            "steer_inbox_sequence": entry.inbox_sequence,
                        },
                    )
                    encoded = json.dumps(
                        data.model_dump(mode="json"),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                    item = ItemSnapshot(
                        item_id=item_id,
                        run_id=run_id,
                        turn_id=turn_id,
                        status=ItemStatus.COMPLETED,
                        data=data,
                        content_hash=(f"sha256:{hashlib.sha256(encoded).hexdigest()}"),
                        created_at=now,
                        updated_at=now,
                    )
                    drafts.append(
                        EventDraft(
                            type="message.completed",
                            turn_id=turn_id,
                            item_id=item_id,
                            data=ItemEventData(operation="completed", item=item),
                            source=EventSource(
                                source_type=EventSourceType.USER,
                                source_id=context.actor.principal_id,
                            ),
                        )
                    )
            events = self._prepare_events_locked(
                row,
                session,
                tuple(drafts),
                context.actor,
                context.trace.correlation_id,
            )
            row.revision += 1
            row.updated_at = now
            session.revision += 1
            session.updated_at = now
            self._persist_events_locked(row, session, events)
            await self._commit_storage_locked(row.session_id)
            self._fanout_locked(run_id, events)
            return SteerClaimResult(
                run=self._run_snapshot(row), entries=applied, events=events
            )

    async def list_steers(self, run_id: str) -> tuple[SteerInboxEntry, ...]:
        async with self._lock:
            if run_id not in self._runs:
                raise self._not_found("run.not_found", run_id)
            return tuple(self._steer_inbox.get(run_id, ()))

    async def resolve_interaction(
        self, command: ReplyInteraction, context: RequestContext
    ) -> CommitResult:
        """Persist one answer and atomically move the suspended Run to RESUMING."""

        async with self._lock:
            command_key = (command.run_id, command.idempotency_key)
            command_digest = self._digest(command.model_dump(mode="json"))
            previous = self._command_results.get(command_key)
            if previous is not None:
                self._require_same_idempotent_request(
                    self._command_digests[command_key], command_digest
                )
                return CommitResult(
                    run=previous.run,
                    session=previous.session,
                    events=previous.events,
                    duplicate=True,
                )

            row = self._runs.get(command.run_id)
            if row is None:
                raise self._not_found("run.not_found", command.run_id)
            if row.revision != command.expected_revision:
                raise self._conflict(
                    "run.revision_conflict",
                    f"expected run revision {command.expected_revision}, current {row.revision}",
                )
            if row.state != RunState.SUSPENDED:
                raise self._conflict(
                    "run.invalid_transition",
                    f"interaction reply requires suspended run, current {row.state.value}",
                )
            if row.suspension_id != command.suspension_id:
                raise self._conflict(
                    "run.suspension_conflict",
                    f"run is suspended by {row.suspension_id!r}, not {command.suspension_id!r}",
                )

            suspension = self._suspensions.get(command.suspension_id)
            if suspension is None:
                raise self._not_found("suspension.not_found", command.suspension_id)
            if suspension.expected_revision != command.expected_suspension_revision:
                raise self._conflict(
                    "suspension.revision_conflict",
                    "suspension revision does not match",
                )
            if suspension.status != SuspensionStatus.PENDING:
                raise self._conflict(
                    "suspension.already_resolved",
                    f"suspension is {suspension.status.value}",
                )
            if suspension.interaction_id != command.interaction_id:
                raise self._conflict(
                    "suspension.interaction_conflict",
                    "interaction does not belong to this suspension",
                )

            interaction = self._interactions.get(command.interaction_id)
            if interaction is None:
                raise self._not_found("interaction.not_found", command.interaction_id)
            if interaction.expected_revision != command.expected_interaction_revision:
                raise self._conflict(
                    "interaction.revision_conflict",
                    "interaction revision does not match",
                )
            if interaction.status != InteractionStatus.PENDING:
                raise self._conflict(
                    "interaction.already_resolved",
                    f"interaction is {interaction.status.value}",
                )
            now = self._clock()
            if interaction.expires_at is not None and interaction.expires_at <= now:
                raise self._conflict(
                    "interaction.expired",
                    "interaction has expired",
                )
            if command.decision not in interaction.allowed_decisions:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="interaction.decision_not_allowed",
                        category=ErrorCategory.VALIDATION,
                        message=f"decision {command.decision!r} is not allowed",
                        safe_to_resume=True,
                    )
                )
            eligible = interaction.eligible_principal_ids
            if eligible and context.actor.principal_id not in eligible:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="interaction.principal_not_eligible",
                        category=ErrorCategory.AUTHORIZATION,
                        message="principal is not eligible to resolve this interaction",
                        safe_to_resume=True,
                    )
                )

            updated_interaction = interaction.model_copy(
                update={
                    "status": InteractionStatus.RESOLVED,
                    "expected_revision": interaction.expected_revision + 1,
                }
            )
            updated_suspension = suspension.model_copy(
                update={
                    "status": SuspensionStatus.RESOLVING,
                    "expected_revision": suspension.expected_revision + 1,
                }
            )
            resolution = InteractionResolution(
                interaction_id=interaction.interaction_id,
                decision=command.decision,
                resolver=context.actor,
                expected_revision=command.expected_interaction_revision,
                idempotency_key=command.idempotency_key,
                payload=command.payload,
                resolved_at=now,
            )
            session = self._sessions[row.session_id]
            drafts = (
                EventDraft(
                    type="interaction.resolved",
                    interaction_id=interaction.interaction_id,
                    data=InteractionEventData(
                        interaction_id=interaction.interaction_id,
                        interaction_type=interaction.interaction_type.value,
                        state="resolved",
                        decision=command.decision,
                        revision=updated_interaction.expected_revision,
                    ),
                ),
                EventDraft(
                    type="run.resume_requested",
                    data=RunEventData(state="resuming", reason="interaction_resolved"),
                ),
            )
            events = self._prepare_events_locked(
                row,
                session,
                drafts,
                context.actor,
                context.trace.correlation_id,
            )

            row.state = RunState.RESUMING
            row.revision += 1
            row.updated_at = now
            session.revision += 1
            session.updated_at = now
            self._interactions[interaction.interaction_id] = updated_interaction
            self._interaction_resolutions[interaction.interaction_id] = resolution
            self._suspensions[suspension.suspension_id] = updated_suspension
            self._persist_events_locked(row, session, events)
            result = CommitResult(
                run=self._run_snapshot(row),
                session=self._session_snapshot(session),
                events=events,
            )
            self._command_results[command_key] = result
            self._command_digests[command_key] = command_digest
            await self._commit_storage_locked(row.session_id)
            self._fanout_locked(row.run_id, events)
            return result

    async def request_resume(
        self, command: ResumeRun, context: RequestContext
    ) -> CommitResult:
        """Accept explicit resume for a non-interaction suspension."""

        async with self._lock:
            command_key = (command.run_id, command.idempotency_key)
            command_digest = self._digest(command.model_dump(mode="json"))
            previous = self._command_results.get(command_key)
            if previous is not None:
                self._require_same_idempotent_request(
                    self._command_digests[command_key], command_digest
                )
                return CommitResult(
                    run=previous.run,
                    session=previous.session,
                    events=previous.events,
                    duplicate=True,
                )
            row = self._runs.get(command.run_id)
            if row is None:
                raise self._not_found("run.not_found", command.run_id)
            if row.revision != command.expected_revision:
                raise self._conflict(
                    "run.revision_conflict",
                    f"expected run revision {command.expected_revision}, current {row.revision}",
                )
            if row.state != RunState.SUSPENDED:
                raise self._conflict(
                    "run.invalid_transition",
                    f"resume requires suspended run, current {row.state.value}",
                )
            if row.suspension_id != command.suspension_id:
                raise self._conflict(
                    "run.suspension_conflict",
                    f"run is suspended by {row.suspension_id!r}, not {command.suspension_id!r}",
                )
            suspension = self._suspensions.get(command.suspension_id)
            if suspension is None:
                raise self._not_found("suspension.not_found", command.suspension_id)
            if suspension.expected_revision != command.expected_suspension_revision:
                raise self._conflict(
                    "suspension.revision_conflict",
                    "suspension revision does not match",
                )
            if suspension.status != SuspensionStatus.PENDING:
                raise self._conflict(
                    "suspension.already_resolved",
                    f"suspension is {suspension.status.value}",
                )

            now = self._clock()
            updated_suspension = suspension.model_copy(
                update={
                    "status": SuspensionStatus.RESOLVING,
                    "expected_revision": suspension.expected_revision + 1,
                }
            )
            session = self._sessions[row.session_id]
            events = self._prepare_events_locked(
                row,
                session,
                (
                    EventDraft(
                        type="run.resume_requested",
                        data=RunEventData(state="resuming"),
                    ),
                ),
                context.actor,
                context.trace.correlation_id,
            )
            row.state = RunState.RESUMING
            row.revision += 1
            row.updated_at = now
            session.revision += 1
            session.updated_at = now
            self._suspensions[suspension.suspension_id] = updated_suspension
            self._persist_events_locked(row, session, events)
            result = CommitResult(
                run=self._run_snapshot(row),
                session=self._session_snapshot(session),
                events=events,
            )
            self._command_results[command_key] = result
            self._command_digests[command_key] = command_digest
            await self._commit_storage_locked(row.session_id)
            self._fanout_locked(row.run_id, events)
            return result

    async def subscribe_events(
        self, cursor: EventCursor
    ) -> AsyncIterator[RuntimeEvent]:
        """Replay after a cursor, then follow a bounded per-observer queue.

        A slow observer is failed with its last delivered cursor instead of
        blocking execution or other observers. Reconnection resumes from the
        canonical Run log.
        """

        subscriber = _Subscriber(
            queue=asyncio.Queue(maxsize=self._subscriber_queue_size),
            last_delivered=cursor.run_sequence,
        )
        async with self._lock:
            if cursor.run_id not in self._runs:
                raise self._not_found("run.not_found", cursor.run_id)
            replay = tuple(
                event
                for event in self._run_events[cursor.run_id]
                if event.run_sequence > cursor.run_sequence
            )
            self._subscribers.setdefault(cursor.run_id, set()).add(subscriber)
        try:
            for event in replay:
                subscriber.last_delivered = event.run_sequence
                yield event
            while True:
                value = await subscriber.queue.get()
                if isinstance(value, _SubscriptionOverflow):
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="stream.subscriber_overflow",
                            category=ErrorCategory.RATE_LIMITED,
                            message=(
                                "subscriber queue overflowed; reconnect from the "
                                f"last delivered cursor {value.last_delivered}"
                            ),
                            retryable=True,
                            safe_to_resume=True,
                            metadata={
                                "last_delivered": value.last_delivered,
                                "latest_available": value.latest_available,
                            },
                        )
                    )
                event = value
                subscriber.last_delivered = event.run_sequence
                yield event
        finally:
            async with self._lock:
                subscriber.closed = True
                self._subscribers.get(cursor.run_id, set()).discard(subscriber)

    async def export_state(self) -> dict[str, Any]:
        async with self._lock:
            return self._dump_state_locked()

    async def load_state(self, payload: dict[str, Any]) -> None:
        async with self._lock:
            self._load_state_locked(payload)

    def _dump_state_locked(self) -> dict[str, Any]:
        """Serialize the complete reference Session state while the store lock is held."""

        return {
            "session_format_version": SESSION_AGGREGATE_FORMAT,
            "sessions": [
                {
                    "session_id": row.session_id,
                    "revision": row.revision,
                    "last_sequence": row.last_sequence,
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                    "active_serial_run_id": row.active_serial_run_id,
                    "parent_session_id": row.parent_session_id,
                    "revision_sequences": {
                        str(revision): sequence
                        for revision, sequence in row.revision_sequences.items()
                    },
                }
                for row in self._sessions.values()
            ],
            "runs": [
                {
                    "session_id": row.session_id,
                    "run_id": row.run_id,
                    "state": row.state.value,
                    "revision": row.revision,
                    "last_run_sequence": row.last_run_sequence,
                    "concurrency_mode": row.concurrency_mode.value,
                    "base_session_revision": row.base_session_revision,
                    "base_session_sequence": row.base_session_sequence,
                    "accepted_session_revision": row.accepted_session_revision,
                    "resolved_spec_hash": row.resolved_spec_hash,
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                    "suspension_id": row.suspension_id,
                    "checkpoint_id": row.checkpoint_id,
                    "start_command": (
                        row.start_command.model_dump(mode="json")
                        if row.start_command is not None
                        else None
                    ),
                }
                for row in self._runs.values()
            ],
            "run_events": {
                run_id: [event.model_dump(mode="json") for event in events]
                for run_id, events in self._run_events.items()
            },
            "fork_base_events": {
                run_id: [event.model_dump(mode="json") for event in events]
                for run_id, events in self._fork_base_events.items()
                if events
            },
            "start_idempotency": [
                {
                    "tenant_id": scope[0],
                    "principal_id": scope[1],
                    "idempotency_key": scope[2],
                    "run_id": run_id,
                    "request_digest": self._start_idempotency_digests[scope],
                }
                for scope, run_id in self._start_idempotency.items()
            ],
            "command_results": [
                {
                    "run_id": key[0],
                    "idempotency_key": key[1],
                    "request_digest": self._command_digests[key],
                    "result": {
                        "run": result.run.model_dump(mode="json"),
                        "session": result.session.model_dump(mode="json"),
                        "events": [
                            event.model_dump(mode="json") for event in result.events
                        ],
                    },
                }
                for key, result in self._command_results.items()
            ],
            "checkpoints": [
                value.model_dump(mode="json") for value in self._checkpoints.values()
            ],
            "suspensions": [
                value.model_dump(mode="json") for value in self._suspensions.values()
            ],
            "interactions": [
                value.model_dump(mode="json") for value in self._interactions.values()
            ],
            "interaction_resolutions": [
                value.model_dump(mode="json")
                for value in self._interaction_resolutions.values()
            ],
            "steer_inbox": {
                run_id: [entry.model_dump(mode="json") for entry in entries]
                for run_id, entries in self._steer_inbox.items()
            },
            "session_commit_proposals": [
                value.model_dump(mode="json")
                for value in self._session_commit_proposals.values()
            ],
            "session_commit_command_results": [
                {
                    "target_id": key[0],
                    "idempotency_key": key[1],
                    "request_digest": self._session_commit_command_digests[key],
                    "proposal": value.model_dump(mode="json"),
                }
                for key, value in self._session_commit_command_results.items()
            ],
        }

    def _load_state_locked(self, payload: dict[str, Any]) -> None:
        """Validate and replace reference Session state from a trusted storage snapshot."""

        if payload.get("session_format_version") != SESSION_AGGREGATE_FORMAT:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session_store.unsupported_format",
                    category=ErrorCategory.UNSUPPORTED_SCHEMA,
                    message=(
                        "unsupported SessionStore format "
                        f"{payload.get('session_format_version')!r}"
                    ),
                )
            )
        sessions: dict[str, _SessionRow] = {}
        for value in payload.get("sessions", ()):
            session_row = _SessionRow(
                session_id=value["session_id"],
                revision=int(value["revision"]),
                last_sequence=int(value["last_sequence"]),
                created_at=datetime.fromisoformat(value["created_at"]),
                updated_at=datetime.fromisoformat(value["updated_at"]),
                active_serial_run_id=value.get("active_serial_run_id"),
                parent_session_id=value.get("parent_session_id"),
                revision_sequences={
                    int(revision): int(sequence)
                    for revision, sequence in value["revision_sequences"].items()
                },
            )
            sessions[session_row.session_id] = session_row
        runs: dict[str, _RunRow] = {}
        for value in payload.get("runs", ()):
            run_row = _RunRow(
                session_id=value["session_id"],
                run_id=value["run_id"],
                state=RunState(value["state"]),
                revision=int(value["revision"]),
                last_run_sequence=int(value["last_run_sequence"]),
                concurrency_mode=SessionConcurrencyMode(value["concurrency_mode"]),
                base_session_revision=int(value["base_session_revision"]),
                base_session_sequence=int(value["base_session_sequence"]),
                accepted_session_revision=int(value["accepted_session_revision"]),
                resolved_spec_hash=value["resolved_spec_hash"],
                created_at=datetime.fromisoformat(value["created_at"]),
                updated_at=datetime.fromisoformat(value["updated_at"]),
                suspension_id=value.get("suspension_id"),
                checkpoint_id=value.get("checkpoint_id"),
                start_command=(
                    StartRun.model_validate(value["start_command"])
                    if value.get("start_command") is not None
                    else None
                ),
            )
            if run_row.session_id not in sessions:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.corrupt_state",
                        category=ErrorCategory.CORRUPT_STATE,
                        message=f"run {run_row.run_id!r} references missing session",
                    )
                )
            runs[run_row.run_id] = run_row
        run_events = {
            run_id: [RuntimeEvent.model_validate(event) for event in events]
            for run_id, events in payload.get("run_events", {}).items()
        }
        fork_base_events = {
            run_id: tuple(RuntimeEvent.model_validate(event) for event in events)
            for run_id, events in payload.get("fork_base_events", {}).items()
        }
        if set(fork_base_events) - set(runs):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session_store.corrupt_state",
                    category=ErrorCategory.CORRUPT_STATE,
                    message="fork history references a missing Run",
                )
            )
        for run_id, run_row in runs.items():
            events = run_events.setdefault(run_id, [])
            expected = list(range(1, len(events) + 1))
            actual = [event.run_sequence for event in events]
            if actual != expected or run_row.last_run_sequence != len(events):
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.corrupt_sequence",
                        category=ErrorCategory.CORRUPT_STATE,
                        message=f"run {run_id!r} event sequence is corrupt",
                    )
                )
        session_events: dict[str, list[RuntimeEvent]] = {
            session_id: [] for session_id in sessions
        }
        for events in run_events.values():
            for event in events:
                if event.session_sequence is not None:
                    session_events[event.session_id].append(event)
        for session_id, events in session_events.items():
            events.sort(key=lambda event: event.session_sequence or 0)
            if [event.session_sequence for event in events] != list(
                range(1, len(events) + 1)
            ) or sessions[session_id].last_sequence != len(events):
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.corrupt_sequence",
                        category=ErrorCategory.CORRUPT_STATE,
                        message=f"session {session_id!r} event sequence is corrupt",
                    )
                )

        self._sessions = sessions
        self._runs = runs
        self._run_events = run_events
        self._fork_base_events = {
            run_id: fork_base_events.get(run_id, ()) for run_id in runs
        }
        self._session_events = session_events
        self._start_idempotency = {
            (
                value.get("tenant_id"),
                value["principal_id"],
                value["idempotency_key"],
            ): value["run_id"]
            for value in payload.get("start_idempotency", ())
        }
        self._start_idempotency_digests = {
            (
                value.get("tenant_id"),
                value["principal_id"],
                value["idempotency_key"],
            ): value["request_digest"]
            for value in payload.get("start_idempotency", ())
        }
        self._command_results = {}
        self._command_digests = {}
        for value in payload.get("command_results", ()):
            result = value["result"]
            self._command_results[(value["run_id"], value["idempotency_key"])] = (
                CommitResult(
                    run=RunSnapshot.model_validate(result["run"]),
                    session=SessionSnapshot.model_validate(result["session"]),
                    events=tuple(
                        RuntimeEvent.model_validate(event)
                        for event in result.get("events", ())
                    ),
                )
            )
            self._command_digests[(value["run_id"], value["idempotency_key"])] = value[
                "request_digest"
            ]
        self._checkpoints = {
            value["checkpoint_id"]: Checkpoint.model_validate(value)
            for value in payload.get("checkpoints", ())
        }
        self._suspensions = {
            value["suspension_id"]: Suspension.model_validate(value)
            for value in payload.get("suspensions", ())
        }
        self._interactions = {
            value["interaction_id"]: InteractionRequest.model_validate(value)
            for value in payload.get("interactions", ())
        }
        from sagents.v2.contracts.interactions import InteractionResolution

        self._interaction_resolutions = {
            value["interaction_id"]: InteractionResolution.model_validate(value)
            for value in payload.get("interaction_resolutions", ())
        }
        self._steer_inbox = {
            run_id: [SteerInboxEntry.model_validate(entry) for entry in entries]
            for run_id, entries in payload.get("steer_inbox", {}).items()
        }
        for run_id in runs:
            self._steer_inbox.setdefault(run_id, [])
        proposals = {
            value["proposal_id"]: SessionCommitProposal.model_validate(value)
            for value in payload.get("session_commit_proposals", ())
        }
        for proposal in proposals.values():
            source = runs.get(proposal.source_run_id)
            if (
                source is None
                or source.session_id != proposal.session_id
                or source.concurrency_mode != SessionConcurrencyMode.SNAPSHOT_ISOLATED
            ):
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.corrupt_state",
                        category=ErrorCategory.CORRUPT_STATE,
                        message=(
                            f"session commit proposal {proposal.proposal_id!r} "
                            "references an invalid snapshot Run"
                        ),
                    )
                )
        self._session_commit_proposals = proposals
        self._session_commit_command_results = {}
        self._session_commit_command_digests = {}
        for value in payload.get("session_commit_command_results", ()):
            key = (value["target_id"], value["idempotency_key"])
            proposal = SessionCommitProposal.model_validate(value["proposal"])
            if proposal.proposal_id not in proposals:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.corrupt_state",
                        category=ErrorCategory.CORRUPT_STATE,
                        message="session commit command references missing proposal",
                    )
                )
            self._session_commit_command_results[key] = proposal
            self._session_commit_command_digests[key] = value["request_digest"]
        self._derived_state = {}
        self._subscribers = {}

    async def _commit_storage_locked(self, session_id: str) -> None:
        """Durability hook invoked before newly committed events are published.

        Ephemeral storage has nothing to flush. Durable plugins override this
        method while reusing the exact same lifecycle state machine.
        """

    async def _delete_storage_locked(self, session_id: str) -> None:
        """Durability hook for removing one authoritative Session aggregate."""

    def _prepare_events_locked(
        self,
        run: _RunRow,
        session: _SessionRow,
        drafts: tuple[EventDraft, ...],
        actor: ActorRef,
        correlation_id: str | None,
    ) -> tuple[RuntimeEvent, ...]:
        events: list[RuntimeEvent] = []
        run_sequence = run.last_run_sequence
        session_sequence_cursor = session.last_sequence
        for draft in drafts:
            definition = EVENT_CATALOG.get(draft.type)
            durability = draft.durability or (
                definition.durability
                if definition is not None
                else EventDurability.REPLAY_BUFFERED
            )
            run_sequence += 1
            session_sequence: int | None = None
            if durability == EventDurability.DURABLE:
                session_sequence_cursor += 1
                session_sequence = session_sequence_cursor
            event = RuntimeEvent(
                event_id=new_id("event"),
                type=draft.type,
                occurred_at=self._clock(),
                durability=durability,
                session_id=run.session_id,
                run_id=run.run_id,
                session_sequence=session_sequence,
                run_sequence=run_sequence,
                turn_id=draft.turn_id,
                step_id=draft.step_id,
                item_id=draft.item_id,
                job_id=draft.job_id,
                interaction_id=draft.interaction_id,
                flow_execution_id=draft.flow_execution_id,
                node_execution_id=draft.node_execution_id,
                correlation_id=correlation_id,
                causation_id=draft.causation_id,
                actor=actor,
                source=draft.source,
                data=draft.data,
                ignorable=draft.ignorable,
            )
            events.append(event)
        return tuple(events)

    def _persist_events_locked(
        self,
        run: _RunRow,
        session: _SessionRow,
        events: tuple[RuntimeEvent, ...],
    ) -> None:
        if events:
            run.last_run_sequence = events[-1].run_sequence
        durable_events = tuple(
            event for event in events if event.durability == EventDurability.DURABLE
        )
        if durable_events:
            last_session_sequence = durable_events[-1].session_sequence
            assert last_session_sequence is not None
            session.last_sequence = last_session_sequence
        self._run_events[run.run_id].extend(events)
        self._session_events[run.session_id].extend(durable_events)
        session.revision_sequences[session.revision] = session.last_sequence

    def _session_commit_conflicts_locked(self, source: _RunRow) -> tuple[str, ...]:
        """Return canonical Runs that wrote after a snapshot's base boundary."""

        published_snapshots = {
            proposal.source_run_id
            for proposal in self._session_commit_proposals.values()
            if proposal.session_id == source.session_id
            and proposal.status == SessionCommitProposalStatus.PUBLISHED
        }
        conflicts = {
            event.run_id
            for event in self._session_events[source.session_id]
            if (event.session_sequence or 0) > source.base_session_sequence
            and event.run_id != source.run_id
            and (
                self._runs[event.run_id].concurrency_mode
                != SessionConcurrencyMode.SNAPSHOT_ISOLATED
                or event.run_id in published_snapshots
            )
        }
        return tuple(sorted(conflicts))

    def _canonical_history_events_locked(
        self, session_id: str, through_sequence: int
    ) -> tuple[RuntimeEvent, ...]:
        """Freeze the model-visible canonical prefix used by a child Session.

        The copy removes the only runtime dependency a fork otherwise has on
        its parent. ``parent_session_id`` remains useful lineage metadata, but
        it is deliberately not a foreign-key constraint.
        """

        published_snapshots = {
            proposal.source_run_id
            for proposal in self._session_commit_proposals.values()
            if proposal.session_id == session_id
            and proposal.status == SessionCommitProposalStatus.PUBLISHED
            and proposal.published_session_sequence is not None
            and proposal.published_session_sequence <= through_sequence
        }
        canonical_run_ids = {
            run.run_id
            for run in self._runs.values()
            if run.session_id == session_id
            and (
                run.concurrency_mode != SessionConcurrencyMode.SNAPSHOT_ISOLATED
                or run.run_id in published_snapshots
            )
        }
        return tuple(
            event
            for event in self._session_events.get(session_id, ())
            if (event.session_sequence or 0) <= through_sequence
            and event.run_id in canonical_run_ids
        )

    @staticmethod
    def _session_commit_event_data(
        proposal: SessionCommitProposal,
        state: str,
    ) -> SessionCommitEventData:
        return SessionCommitEventData(
            proposal_id=proposal.proposal_id,
            source_run_id=proposal.source_run_id,
            state=state,
            base_session_revision=proposal.base_session_revision,
            base_session_sequence=proposal.base_session_sequence,
            merge_strategy=(
                proposal.merge_strategy.value
                if proposal.merge_strategy is not None
                else None
            ),
            conflicting_run_ids=proposal.conflicting_run_ids,
            reason=proposal.rejection_reason,
        )

    @staticmethod
    def _sequence_at_revision(session: _SessionRow, revision: int) -> int:
        """Resolve a CAS revision to an exact canonical-event replay boundary."""

        try:
            return session.revision_sequences[revision]
        except KeyError as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session.revision_history_unavailable",
                    category=ErrorCategory.CORRUPT_STATE,
                    message=(
                        f"session {session.session_id} has no event boundary for "
                        f"revision {revision}"
                    ),
                )
            ) from exc

    def _active_turn_locked(self, run_id: str) -> str | None:
        active: str | None = None
        for event in self._run_events.get(run_id, ()):
            if event.type == "turn.started":
                active = event.turn_id
            elif (
                event.type in {"turn.completed", "turn.failed"}
                and event.turn_id == active
            ):
                active = None
        return active

    def _fanout_locked(self, run_id: str, events: tuple[RuntimeEvent, ...]) -> None:
        for subscriber in tuple(self._subscribers.get(run_id, ())):
            if subscriber.closed:
                continue
            for event in events:
                try:
                    subscriber.queue.put_nowait(event)
                except asyncio.QueueFull:
                    while True:
                        try:
                            subscriber.queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    subscriber.queue.put_nowait(
                        _SubscriptionOverflow(
                            last_delivered=subscriber.last_delivered,
                            latest_available=event.run_sequence,
                        )
                    )
                    subscriber.closed = True
                    break

    @staticmethod
    def _handle(row: _RunRow) -> RunHandle:
        return RunHandle(
            session_id=row.session_id,
            run_id=row.run_id,
            state=row.state,
            run_revision=row.revision,
            concurrency_mode=row.concurrency_mode,
            base_session_revision=row.base_session_revision,
            base_session_sequence=row.base_session_sequence,
            accepted_session_revision=row.accepted_session_revision,
            event_cursor=EventCursor(
                run_id=row.run_id, run_sequence=row.last_run_sequence
            ),
            resolved_spec_hash=row.resolved_spec_hash,
        )

    @staticmethod
    def _run_snapshot(row: _RunRow) -> RunSnapshot:
        return RunSnapshot(
            session_id=row.session_id,
            run_id=row.run_id,
            state=row.state,
            revision=row.revision,
            last_run_sequence=row.last_run_sequence,
            concurrency_mode=row.concurrency_mode,
            base_session_revision=row.base_session_revision,
            base_session_sequence=row.base_session_sequence,
            accepted_session_revision=row.accepted_session_revision,
            resolved_spec_hash=row.resolved_spec_hash,
            suspension_id=row.suspension_id,
            checkpoint_id=row.checkpoint_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _session_snapshot(row: _SessionRow) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=row.session_id,
            revision=row.revision,
            last_sequence=row.last_sequence,
            active_serial_run_id=row.active_serial_run_id,
            parent_session_id=row.parent_session_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _digest(value: Any) -> str:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(encoded).hexdigest()}"

    @staticmethod
    def _dump_draft(draft: EventDraft) -> dict[str, Any]:
        return {
            "type": draft.type,
            "data": draft.data.model_dump(mode="json"),
            "durability": draft.durability.value if draft.durability else None,
            "turn_id": draft.turn_id,
            "step_id": draft.step_id,
            "item_id": draft.item_id,
            "job_id": draft.job_id,
            "interaction_id": draft.interaction_id,
            "flow_execution_id": draft.flow_execution_id,
            "node_execution_id": draft.node_execution_id,
            "causation_id": draft.causation_id,
            "source": draft.source.model_dump(mode="json"),
            "ignorable": draft.ignorable,
        }

    @classmethod
    def _require_same_idempotent_request(cls, expected: str, actual: str) -> None:
        if expected != actual:
            raise cls._conflict(
                "idempotency.conflict",
                "idempotency key was already used for a different request",
            )

    @staticmethod
    def _conflict(code: str, message: str) -> ConflictError:
        return ConflictError(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.CONFLICT,
                message=message,
                retryable=False,
                safe_to_resume=True,
            )
        )

    @staticmethod
    def _not_found(code: str, target_id: str) -> NotFoundError:
        return NotFoundError(
            RuntimeErrorInfo(
                code=code,
                category=ErrorCategory.VALIDATION,
                message=f"resource {target_id!r} was not found",
                retryable=False,
                safe_to_resume=False,
            )
        )
