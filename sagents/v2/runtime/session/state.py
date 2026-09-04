"""Backend-neutral state machine for the v2 SessionStore semantics.

This module defines sequencing, optimistic revisions, idempotency, suspension,
steering, subscriptions, and state serialization. Concrete storage adapters
reuse these rules without depending on one another.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager, nullcontext
from collections.abc import AsyncIterator, Callable, Collection, Coroutine
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
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
from sagents.v2.contracts.common import new_id, new_sortable_id, utc_now
from sagents.v2.contracts.errors import (
    ConflictError,
    ErrorCategory,
    NotFoundError,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.events import (
    EVENT_CATALOG,
    EventDurability,
    EventSource,
    EventSourceType,
    InteractionEventData,
    ItemEventData,
    RunEventData,
    RuntimeEvent,
    SandboxEventData,
    SessionCommitEventData,
    SteeringEventData,
)
from sagents.v2.contracts.interactions import (
    InteractionRequest,
    InteractionResolution,
    InteractionStatus,
)
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
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
from sagents.v2.runtime.session.contracts import (
    CommitResult,
    EventDraft,
    RunCreationResult,
    DispatchableRun,
    SteerClaimResult,
)
from sagents.v2.runtime.execution.resources import (
    ExecutionResourceRecord,
    ExecutionResourceState,
)
from sagents.v2.runtime.session.journal import SessionStateDeltaMutation


SESSION_AGGREGATE_FORMAT = "sage.session-aggregate/v2"


@dataclass
class _SessionRow:
    session_id: str
    revision: int
    last_sequence: int
    created_at: datetime
    updated_at: datetime
    active_serial_run_id: str | None = None
    parent_session_id: str | None = None
    owner: ActorRef | None = None
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
    request_context: RequestContext | None = None


@dataclass(eq=False)
class _Subscriber:
    queue: asyncio.Queue[Any]
    last_delivered: int
    closed: bool = False


@dataclass(frozen=True)
class _SubscriptionOverflow:
    last_delivered: int
    latest_available: int


@dataclass
class _SessionUndo:
    """Object-level undo watermark for one Session operation.

    Event history is recorded by length only so a failed persist can truncate
    instead of copying or re-validating the full canonical log.
    """

    session_id: str
    existed: bool
    session: _SessionRow | None
    runs: dict[str, _RunRow]
    run_event_lens: dict[str, int]
    run_event_lists: dict[str, list[RuntimeEvent]]
    session_event_len: int
    session_events: list[RuntimeEvent] | None
    fork_base_events: dict[str, tuple[RuntimeEvent, ...]]
    start_idempotency: dict[tuple[str | None, PrincipalType, str, str], str]
    start_idempotency_digests: dict[tuple[str | None, PrincipalType, str, str], str]
    command_results: dict[tuple[str, str], CommitResult]
    command_digests: dict[tuple[str, str], str]
    execution_resources: dict[str, ExecutionResourceRecord]
    execution_resource_command_results: dict[tuple[str, str], ExecutionResourceRecord]
    execution_resource_command_digests: dict[tuple[str, str], str]
    checkpoints: dict[str, Checkpoint]
    suspensions: dict[str, Suspension]
    interactions: dict[str, InteractionRequest]
    interaction_resolutions: dict[str, InteractionResolution]
    steer_inbox: dict[str, list[SteerInboxEntry]]
    proposals: dict[str, SessionCommitProposal]
    proposal_results: dict[tuple[str, str], SessionCommitProposal]
    proposal_digests: dict[tuple[str, str], str]
    topology_revision: int


@dataclass
class _SessionOperation:
    undos: dict[str, _SessionUndo] | None
    cancellation: asyncio.CancelledError | None = None


class SessionStoreCoordinator:
    """Atomic reference state machine for the SessionStore contract.

    The default persistence hooks retain process-local state. Concrete adapters
    may override only those hooks while preserving canonical sequencing,
    idempotency, checkpoint transactions, and bounded subscriptions.
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
            "supports_actor_authorization": True,
            "multi_process_writes": False,
            "cross_process_subscribe": False,
            "transactional_outbox": False,
            "atomic_session_cas": True,
        }

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utc_now,
        subscriber_queue_size: int = 256,
        persistence_can_fail: bool = True,
    ) -> None:
        if subscriber_queue_size < 1:
            raise ValueError("subscriber_queue_size must be positive")
        self._clock = clock
        self._subscriber_queue_size = subscriber_queue_size
        self._persistence_can_fail = persistence_can_fail
        self._lock = asyncio.Lock()
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._start_locks: dict[
            tuple[str | None, PrincipalType, str, str], asyncio.Lock
        ] = {}
        self._topology_revision = 0
        self._sessions: dict[str, _SessionRow] = {}
        self._runs: dict[str, _RunRow] = {}
        self._run_events: dict[str, list[RuntimeEvent]] = {}
        self._session_events: dict[str, list[RuntimeEvent]] = {}
        # Fork history is copied at acceptance time, so a child Run does not
        # read mutable parent state while it executes. Deletion still follows
        # Session ownership and cascades from parent to descendants.
        self._fork_base_events: dict[str, tuple[RuntimeEvent, ...]] = {}
        # Derived state is explicitly non-authoritative and can be discarded.
        self._derived_state: dict[tuple[str, str, str], Any] = {}
        self._start_idempotency: dict[
            tuple[str | None, PrincipalType, str, str], str
        ] = {}
        self._start_idempotency_digests: dict[
            tuple[str | None, PrincipalType, str, str], str
        ] = {}
        self._command_results: dict[tuple[str, str], CommitResult] = {}
        self._command_digests: dict[tuple[str, str], str] = {}
        self._execution_resources: dict[str, ExecutionResourceRecord] = {}
        self._execution_resource_command_results: dict[
            tuple[str, str], ExecutionResourceRecord
        ] = {}
        self._execution_resource_command_digests: dict[tuple[str, str], str] = {}
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
        self._operation: ContextVar[_SessionOperation | None] = ContextVar(
            "session_operation", default=None
        )

    @asynccontextmanager
    async def _session_operation(self, *session_ids: str):
        """Serialize one or more aggregates without blocking unrelated I/O."""

        ordered = tuple(sorted(set(session_ids)))
        if not ordered:
            raise ValueError("at least one session_id is required")
        async with self._lock:
            locks = tuple(
                self._session_locks.setdefault(session_id, asyncio.Lock())
                for session_id in ordered
            )
        acquired: list[asyncio.Lock] = []
        try:
            for lock in locks:
                await lock.acquire()
                acquired.append(lock)
            undos = (
                {
                    session_id: self._capture_session_undo_locked(session_id)
                    for session_id in ordered
                }
                if self._persistence_can_fail
                else None
            )
            operation = _SessionOperation(undos)
            token = self._operation.set(operation)
            try:
                yield
            except BaseException:
                if undos is not None:
                    self._restore_session_undos_locked(undos)
                raise
            finally:
                self._operation.reset(token)
        finally:
            for lock in reversed(acquired):
                lock.release()
        # Storage may already be durable when cancellation arrives. Finish the
        # in-memory commit and subscriber fanout before propagating it, outside
        # the rollback guard and after releasing the Session locks.
        if operation.cancellation is not None:
            raise operation.cancellation

    async def _settle_storage(self, write: Coroutine[Any, Any, None]) -> None:
        """Keep ownership until persistence/recovery settles, even on cancellation."""

        if not self._persistence_can_fail:
            await write
            return
        operation = self._operation.get()
        assert operation is not None
        task = asyncio.create_task(write)
        while True:
            try:
                await asyncio.shield(task)
                return
            except asyncio.CancelledError as exc:
                if task.cancelled():
                    raise
                # Repeated cancel() calls must not detach a filesystem thread
                # or release the lock while a transaction is still committing.
                operation.cancellation = exc

    @asynccontextmanager
    async def _session_read(self, session_id: str):
        async with self._lock:
            lock = self._session_locks.setdefault(session_id, asyncio.Lock())
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @asynccontextmanager
    async def _run_session_read(self, run_id: str):
        async with self._lock:
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            session_id = row.session_id
        async with self._session_read(session_id):
            current = self._runs.get(run_id)
            if current is None or current.session_id != session_id:
                raise self._not_found("run.not_found", run_id)
            yield

    @asynccontextmanager
    async def _run_session_operation(self, run_id: str):
        async with self._lock:
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            session_id = row.session_id
        async with self._session_operation(session_id):
            current = self._runs.get(run_id)
            if current is None or current.session_id != session_id:
                raise self._not_found("run.not_found", run_id)
            yield

    @asynccontextmanager
    async def _proposal_session_operation(self, proposal_id: str):
        async with self._lock:
            proposal = self._session_commit_proposals.get(proposal_id)
            if proposal is None:
                raise self._not_found(
                    "session.commit_proposal_not_found", proposal_id
                )
            session_id = proposal.session_id
        async with self._session_operation(session_id):
            current = self._session_commit_proposals.get(proposal_id)
            if current is None or current.session_id != session_id:
                raise self._not_found(
                    "session.commit_proposal_not_found", proposal_id
                )
            yield

    def _session_run_ids_locked(self, session_id: str) -> set[str]:
        return {
            row.run_id
            for row in self._runs.values()
            if row.session_id == session_id
        }

    def _capture_session_undo_locked(self, session_id: str) -> _SessionUndo:
        session = self._sessions.get(session_id)
        if session is None:
            return _SessionUndo(
                session_id=session_id,
                existed=False,
                session=None,
                runs={},
                run_event_lens={},
                run_event_lists={},
                session_event_len=0,
                session_events=None,
                fork_base_events={},
                start_idempotency={},
                start_idempotency_digests={},
                command_results={},
                command_digests={},
                execution_resources={},
                execution_resource_command_results={},
                execution_resource_command_digests={},
                checkpoints={},
                suspensions={},
                interactions={},
                interaction_resolutions={},
                steer_inbox={},
                proposals={},
                proposal_results={},
                proposal_digests={},
                topology_revision=self._topology_revision,
            )
        run_ids = self._session_run_ids_locked(session_id)
        interaction_ids = {
            value.interaction_id
            for value in self._interactions.values()
            if value.run_id in run_ids
        }
        proposal_ids = {
            value.proposal_id
            for value in self._session_commit_proposals.values()
            if value.session_id == session_id
        }
        start_scopes = {
            scope: run_id
            for scope, run_id in self._start_idempotency.items()
            if run_id in run_ids
        }
        command_keys = {key for key in self._command_results if key[0] in run_ids}
        resource_keys = {
            key
            for key in self._execution_resource_command_results
            if key[0] in run_ids
        }
        proposal_keys = {
            key
            for key, value in self._session_commit_command_results.items()
            if value.proposal_id in proposal_ids
        }
        return _SessionUndo(
            session_id=session_id,
            existed=True,
            session=replace(
                session, revision_sequences=dict(session.revision_sequences)
            ),
            runs={run_id: replace(self._runs[run_id]) for run_id in run_ids},
            run_event_lens={
                run_id: len(self._run_events.get(run_id, ())) for run_id in run_ids
            },
            run_event_lists={
                run_id: self._run_events[run_id]
                for run_id in run_ids
                if run_id in self._run_events
            },
            session_event_len=len(self._session_events.get(session_id, ())),
            session_events=self._session_events.get(session_id),
            fork_base_events={
                run_id: self._fork_base_events[run_id]
                for run_id in run_ids
                if run_id in self._fork_base_events
            },
            start_idempotency=dict(start_scopes),
            start_idempotency_digests={
                scope: self._start_idempotency_digests[scope] for scope in start_scopes
            },
            command_results={
                key: self._command_results[key] for key in command_keys
            },
            command_digests={
                key: self._command_digests[key] for key in command_keys
            },
            execution_resources={
                run_id: self._execution_resources[run_id]
                for run_id in run_ids
                if run_id in self._execution_resources
            },
            execution_resource_command_results={
                key: self._execution_resource_command_results[key]
                for key in resource_keys
            },
            execution_resource_command_digests={
                key: self._execution_resource_command_digests[key]
                for key in resource_keys
            },
            checkpoints={
                key: value
                for key, value in self._checkpoints.items()
                if value.run_id in run_ids
            },
            suspensions={
                key: value
                for key, value in self._suspensions.items()
                if value.run_id in run_ids
            },
            interactions={
                key: value
                for key, value in self._interactions.items()
                if value.run_id in run_ids
            },
            interaction_resolutions={
                key: value
                for key, value in self._interaction_resolutions.items()
                if key in interaction_ids
            },
            steer_inbox={
                run_id: list(self._steer_inbox[run_id])
                for run_id in run_ids
                if run_id in self._steer_inbox
            },
            proposals={
                key: value
                for key, value in self._session_commit_proposals.items()
                if key in proposal_ids
            },
            proposal_results={
                key: self._session_commit_command_results[key] for key in proposal_keys
            },
            proposal_digests={
                key: self._session_commit_command_digests[key] for key in proposal_keys
            },
            topology_revision=self._topology_revision,
        )

    def _restore_session_undos_locked(self, undos: dict[str, _SessionUndo]) -> None:
        for session_id in undos:
            self._drop_session_objects_locked(session_id)
        for undo in undos.values():
            if not undo.existed:
                continue
            assert undo.session is not None
            self._sessions[undo.session_id] = undo.session
            self._runs.update(undo.runs)
            for run_id, events in undo.run_event_lists.items():
                del events[undo.run_event_lens.get(run_id, 0) :]
                self._run_events[run_id] = events
            if undo.session_events is not None:
                del undo.session_events[undo.session_event_len :]
                self._session_events[undo.session_id] = undo.session_events
            self._fork_base_events.update(undo.fork_base_events)
            self._start_idempotency.update(undo.start_idempotency)
            self._start_idempotency_digests.update(undo.start_idempotency_digests)
            self._command_results.update(undo.command_results)
            self._command_digests.update(undo.command_digests)
            self._execution_resources.update(undo.execution_resources)
            self._execution_resource_command_results.update(
                undo.execution_resource_command_results
            )
            self._execution_resource_command_digests.update(
                undo.execution_resource_command_digests
            )
            self._checkpoints.update(undo.checkpoints)
            self._suspensions.update(undo.suspensions)
            self._interactions.update(undo.interactions)
            self._interaction_resolutions.update(undo.interaction_resolutions)
            self._steer_inbox.update(
                {run_id: list(entries) for run_id, entries in undo.steer_inbox.items()}
            )
            self._session_commit_proposals.update(undo.proposals)
            self._session_commit_command_results.update(undo.proposal_results)
            self._session_commit_command_digests.update(undo.proposal_digests)
            if undo.topology_revision < self._topology_revision:
                self._topology_revision = undo.topology_revision

    def _drop_session_objects_locked(self, session_id: str) -> None:
        run_ids = self._session_run_ids_locked(session_id)
        interaction_ids = {
            value.interaction_id
            for value in self._interactions.values()
            if value.run_id in run_ids
        }
        proposal_ids = {
            value.proposal_id
            for value in self._session_commit_proposals.values()
            if value.session_id == session_id
        }
        self._sessions.pop(session_id, None)
        self._session_events.pop(session_id, None)
        for run_id in run_ids:
            self._runs.pop(run_id, None)
            self._run_events.pop(run_id, None)
            self._fork_base_events.pop(run_id, None)
            self._execution_resources.pop(run_id, None)
            self._steer_inbox.pop(run_id, None)
        self._start_idempotency = {
            scope: run_id
            for scope, run_id in self._start_idempotency.items()
            if run_id not in run_ids
        }
        self._start_idempotency_digests = {
            scope: digest
            for scope, digest in self._start_idempotency_digests.items()
            if scope in self._start_idempotency
        }
        self._command_results = {
            key: value
            for key, value in self._command_results.items()
            if key[0] not in run_ids
        }
        self._command_digests = {
            key: value
            for key, value in self._command_digests.items()
            if key[0] not in run_ids
        }
        self._execution_resource_command_results = {
            key: value
            for key, value in self._execution_resource_command_results.items()
            if key[0] not in run_ids
        }
        self._execution_resource_command_digests = {
            key: value
            for key, value in self._execution_resource_command_digests.items()
            if key[0] not in run_ids
        }
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
        self._interaction_resolutions = {
            key: value
            for key, value in self._interaction_resolutions.items()
            if key not in interaction_ids
        }
        self._session_commit_proposals = {
            key: value
            for key, value in self._session_commit_proposals.items()
            if key not in proposal_ids
        }
        self._session_commit_command_results = {
            key: value
            for key, value in self._session_commit_command_results.items()
            if value.proposal_id not in proposal_ids
        }
        self._session_commit_command_digests = {
            key: value
            for key, value in self._session_commit_command_digests.items()
            if key in self._session_commit_command_results
        }

    def _session_mutation_locked(self, session_id: str) -> SessionStateDeltaMutation:
        """Serialize only rows and events changed since the operation watermark."""

        operation = self._operation.get()
        undo = (operation.undos or {}).get(session_id) if operation else None
        if undo is None:
            payload = self._dump_session_state_locked(session_id)
            return SessionStateDeltaMutation(
                upserts={
                    key: list(payload.get(key, ()))
                    for key in (
                        "sessions",
                        "runs",
                        "start_idempotency",
                        "command_results",
                        "execution_resources",
                        "execution_resource_command_results",
                        "checkpoints",
                        "suspensions",
                        "interactions",
                        "interaction_resolutions",
                        "session_commit_proposals",
                        "session_commit_command_results",
                    )
                    if payload.get(key)
                },
                appends={
                    key: {
                        run_id: list(rows)
                        for run_id, rows in payload.get(key, {}).items()
                        if rows
                    }
                    for key in ("run_events",)
                    if payload.get(key)
                },
                replacements={
                    key: {
                        run_id: list(rows)
                        for run_id, rows in payload.get(key, {}).items()
                        if rows
                    }
                    for key in ("fork_base_events", "steer_inbox")
                    if payload.get(key)
                },
            )
        current_run_ids = self._session_run_ids_locked(session_id)
        upserts: dict[str, list[dict[str, Any]]] = {}
        deletes: dict[str, list[list[Any]]] = {}
        appends: dict[str, dict[str, list[dict[str, Any]]]] = {}
        replacements: dict[str, dict[str, list[dict[str, Any]]]] = {}
        map_deletes: dict[str, list[str]] = {}
        session = self._sessions[session_id]
        if (
            not undo.existed
            or undo.session is None
            or undo.session != session
        ):
            upserts["sessions"] = [self._session_row_payload(session)]
        changed_runs = [
            self._run_row_payload(self._runs[run_id])
            for run_id in sorted(current_run_ids)
            if run_id not in undo.runs or undo.runs[run_id] != self._runs[run_id]
        ]
        if changed_runs:
            upserts["runs"] = changed_runs
        removed_runs = sorted(set(undo.runs) - current_run_ids)
        if removed_runs:
            deletes["runs"] = [[run_id] for run_id in removed_runs]
        event_appends: dict[str, list[dict[str, Any]]] = {}
        event_replacements: dict[str, list[dict[str, Any]]] = {}
        for run_id in current_run_ids:
            events = self._run_events.get(run_id, [])
            previous_len = undo.run_event_lens.get(run_id, 0)
            if len(events) < previous_len:
                event_replacements[run_id] = [
                    event.model_dump(mode="json") for event in events
                ]
            elif len(events) > previous_len:
                event_appends[run_id] = [
                    event.model_dump(mode="json") for event in events[previous_len:]
                ]
        if event_appends:
            appends["run_events"] = event_appends
        if event_replacements:
            replacements["run_events"] = event_replacements
        removed_event_runs = sorted(
            set(undo.run_event_lens) - current_run_ids
        )
        if removed_event_runs:
            map_deletes["run_events"] = removed_event_runs
        fork_changed = {
            run_id: [event.model_dump(mode="json") for event in events]
            for run_id, events in self._fork_base_events.items()
            if run_id in current_run_ids
            and undo.fork_base_events.get(run_id) != events
        }
        if fork_changed:
            replacements["fork_base_events"] = fork_changed
        removed_forks = sorted(set(undo.fork_base_events) - current_run_ids)
        if removed_forks:
            map_deletes.setdefault("fork_base_events", []).extend(removed_forks)
        steer_changed = {
            run_id: [entry.model_dump(mode="json") for entry in entries]
            for run_id, entries in self._steer_inbox.items()
            if run_id in current_run_ids
            and list(undo.steer_inbox.get(run_id, ())) != list(entries)
        }
        if steer_changed:
            replacements["steer_inbox"] = steer_changed
        removed_steers = sorted(set(undo.steer_inbox) - current_run_ids)
        if removed_steers:
            map_deletes.setdefault("steer_inbox", []).extend(removed_steers)

        current_start = {
            scope: run_id
            for scope, run_id in self._start_idempotency.items()
            if run_id in current_run_ids
        }
        start_changed = []
        for scope, run_id in current_start.items():
            if undo.start_idempotency.get(scope) != run_id:
                start_changed.append(
                    {
                        "tenant_id": scope[0],
                        "principal_type": scope[1].value,
                        "principal_id": scope[2],
                        "idempotency_key": scope[3],
                        "run_id": run_id,
                        "request_digest": self._start_idempotency_digests[scope],
                    }
                )
        if start_changed:
            upserts["start_idempotency"] = start_changed
        start_removed = [
            [scope[0], scope[1].value, scope[2], scope[3]]
            for scope in undo.start_idempotency
            if scope not in current_start
        ]
        if start_removed:
            deletes["start_idempotency"] = start_removed

        current_commands = {
            key: value
            for key, value in self._command_results.items()
            if key[0] in current_run_ids
        }
        command_changed = [
            {
                "run_id": key[0],
                "idempotency_key": key[1],
                "request_digest": self._command_digests[key],
                "result": {
                    "run": value.run.model_dump(mode="json"),
                    "session": value.session.model_dump(mode="json"),
                    "events": [
                        event.model_dump(mode="json") for event in value.events
                    ],
                },
            }
            for key, value in current_commands.items()
            if undo.command_results.get(key) is not value
        ]
        if command_changed:
            upserts["command_results"] = command_changed
        command_removed = [
            [key[0], key[1]]
            for key in undo.command_results
            if key not in current_commands
        ]
        if command_removed:
            deletes["command_results"] = command_removed

        current_resources = {
            run_id: self._execution_resources[run_id]
            for run_id in current_run_ids
            if run_id in self._execution_resources
        }
        resource_changed = [
            value.model_dump(mode="json")
            for run_id, value in current_resources.items()
            if undo.execution_resources.get(run_id) is not value
        ]
        if resource_changed:
            upserts["execution_resources"] = resource_changed
        resource_removed = [
            [run_id]
            for run_id in undo.execution_resources
            if run_id not in current_resources
        ]
        if resource_removed:
            deletes["execution_resources"] = resource_removed

        current_resource_results = {
            key: value
            for key, value in self._execution_resource_command_results.items()
            if key[0] in current_run_ids
        }
        resource_result_changed = [
            {
                "run_id": key[0],
                "idempotency_key": key[1],
                "request_digest": self._execution_resource_command_digests[key],
                "record": value.model_dump(mode="json"),
            }
            for key, value in current_resource_results.items()
            if undo.execution_resource_command_results.get(key) is not value
        ]
        if resource_result_changed:
            upserts["execution_resource_command_results"] = resource_result_changed
        resource_result_removed = [
            [key[0], key[1]]
            for key in undo.execution_resource_command_results
            if key not in current_resource_results
        ]
        if resource_result_removed:
            deletes["execution_resource_command_results"] = resource_result_removed

        current_checkpoints = {
            key: value
            for key, value in self._checkpoints.items()
            if value.run_id in current_run_ids
        }
        checkpoint_changed = [
            value.model_dump(mode="json")
            for key, value in current_checkpoints.items()
            if undo.checkpoints.get(key) is not value
        ]
        if checkpoint_changed:
            upserts["checkpoints"] = checkpoint_changed
        checkpoint_removed = [
            [key]
            for key in undo.checkpoints
            if key not in current_checkpoints
        ]
        if checkpoint_removed:
            deletes["checkpoints"] = checkpoint_removed

        current_suspensions = {
            key: value
            for key, value in self._suspensions.items()
            if value.run_id in current_run_ids
        }
        suspension_changed = [
            value.model_dump(mode="json")
            for key, value in current_suspensions.items()
            if undo.suspensions.get(key) is not value
        ]
        if suspension_changed:
            upserts["suspensions"] = suspension_changed
        suspension_removed = [
            [key] for key in undo.suspensions if key not in current_suspensions
        ]
        if suspension_removed:
            deletes["suspensions"] = suspension_removed

        current_interactions = {
            key: value
            for key, value in self._interactions.items()
            if value.run_id in current_run_ids
        }
        interaction_changed = [
            value.model_dump(mode="json")
            for key, value in current_interactions.items()
            if undo.interactions.get(key) is not value
        ]
        if interaction_changed:
            upserts["interactions"] = interaction_changed
        interaction_removed = [
            [key] for key in undo.interactions if key not in current_interactions
        ]
        if interaction_removed:
            deletes["interactions"] = interaction_removed

        current_resolutions = {
            key: value
            for key, value in self._interaction_resolutions.items()
            if key in {item.interaction_id for item in current_interactions.values()}
            or key in undo.interaction_resolutions
        }
        resolution_changed = [
            value.model_dump(mode="json")
            for key, value in current_resolutions.items()
            if undo.interaction_resolutions.get(key) is not value
        ]
        if resolution_changed:
            upserts["interaction_resolutions"] = resolution_changed
        resolution_removed = [
            [key]
            for key in undo.interaction_resolutions
            if key not in current_resolutions
        ]
        if resolution_removed:
            deletes["interaction_resolutions"] = resolution_removed

        current_proposals = {
            key: value
            for key, value in self._session_commit_proposals.items()
            if value.session_id == session_id
        }
        proposal_changed = [
            value.model_dump(mode="json")
            for key, value in current_proposals.items()
            if undo.proposals.get(key) is not value
        ]
        if proposal_changed:
            upserts["session_commit_proposals"] = proposal_changed
        proposal_removed = [
            [key] for key in undo.proposals if key not in current_proposals
        ]
        if proposal_removed:
            deletes["session_commit_proposals"] = proposal_removed

        current_proposal_results = {
            key: value
            for key, value in self._session_commit_command_results.items()
            if value.proposal_id in current_proposals
            or key in undo.proposal_results
        }
        proposal_result_changed = [
            {
                "target_id": key[0],
                "idempotency_key": key[1],
                "request_digest": self._session_commit_command_digests[key],
                "proposal": value.model_dump(mode="json"),
            }
            for key, value in current_proposal_results.items()
            if undo.proposal_results.get(key) is not value
        ]
        if proposal_result_changed:
            upserts["session_commit_command_results"] = proposal_result_changed
        proposal_result_removed = [
            [key[0], key[1]]
            for key in undo.proposal_results
            if key not in current_proposal_results
        ]
        if proposal_result_removed:
            deletes["session_commit_command_results"] = proposal_result_removed

        return SessionStateDeltaMutation(
            upserts=upserts,
            deletes=deletes,
            appends=appends,
            replacements=replacements,
            map_deletes=map_deletes,
        )

    def _session_row_payload(self, session: _SessionRow) -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "revision": session.revision,
            "last_sequence": session.last_sequence,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "active_serial_run_id": session.active_serial_run_id,
            "parent_session_id": session.parent_session_id,
            "owner": (
                session.owner.model_dump(mode="json")
                if session.owner is not None
                else None
            ),
            "revision_sequences": {
                str(revision): sequence
                for revision, sequence in session.revision_sequences.items()
            },
        }

    def _run_row_payload(self, row: _RunRow) -> dict[str, Any]:
        return {
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
            "request_context": (
                row.request_context.model_dump(mode="json")
                if row.request_context is not None
                else None
            ),
        }

    def _restore_session_snapshots_locked(
        self, snapshots: dict[str, dict[str, Any] | None]
    ) -> None:
        """Replace only failed aggregates, preserving concurrent commits."""

        session_ids = frozenset(snapshots)
        combined = self._dump_state_locked()
        current_run_ids = {
            row["run_id"]
            for row in combined["runs"]
            if row["session_id"] in session_ids
        }
        snapshot_run_ids = {
            row["run_id"]
            for snapshot in snapshots.values()
            if snapshot is not None
            for row in snapshot.get("runs", ())
        }
        run_ids = current_run_ids | snapshot_run_ids
        interaction_ids = {
            row["interaction_id"]
            for row in combined["interactions"]
            if row["run_id"] in run_ids
        } | {
            row["interaction_id"]
            for snapshot in snapshots.values()
            if snapshot is not None
            for row in snapshot.get("interactions", ())
        }
        proposal_ids = {
            row["proposal_id"]
            for row in combined["session_commit_proposals"]
            if row["session_id"] in session_ids
        } | {
            row["proposal_id"]
            for snapshot in snapshots.values()
            if snapshot is not None
            for row in snapshot.get("session_commit_proposals", ())
        }
        combined["sessions"] = [
            row
            for row in combined["sessions"]
            if row["session_id"] not in session_ids
        ]
        combined["runs"] = [
            row for row in combined["runs"] if row["run_id"] not in run_ids
        ]
        for key in ("run_events", "fork_base_events", "steer_inbox"):
            combined[key] = {
                run_id: values
                for run_id, values in combined[key].items()
                if run_id not in run_ids
            }
        combined["start_idempotency"] = [
            row
            for row in combined["start_idempotency"]
            if row["run_id"] not in run_ids
        ]
        combined["command_results"] = [
            row for row in combined["command_results"] if row["run_id"] not in run_ids
        ]
        for key in ("checkpoints", "suspensions", "interactions"):
            combined[key] = [
                row for row in combined[key] if row["run_id"] not in run_ids
            ]
        combined["interaction_resolutions"] = [
            row
            for row in combined["interaction_resolutions"]
            if row["interaction_id"] not in interaction_ids
        ]
        combined["session_commit_proposals"] = [
            row
            for row in combined["session_commit_proposals"]
            if row["proposal_id"] not in proposal_ids
        ]
        combined["session_commit_command_results"] = [
            row
            for row in combined["session_commit_command_results"]
            if row["proposal"]["proposal_id"] not in proposal_ids
        ]
        for snapshot in snapshots.values():
            if snapshot is None:
                continue
            for key in (
                "sessions",
                "runs",
                "start_idempotency",
                "command_results",
                "checkpoints",
                "suspensions",
                "interactions",
                "interaction_resolutions",
                "session_commit_proposals",
                "session_commit_command_results",
            ):
                combined[key].extend(snapshot.get(key, ()))
            for key in ("run_events", "fork_base_events", "steer_inbox"):
                combined[key].update(snapshot.get(key, {}))
        subscribers = self._subscribers
        derived = self._derived_state
        self._load_state_locked(combined)
        self._subscribers.update(subscribers)
        self._derived_state.update(derived)

    async def create_run(
        self, command: StartRun, context: RequestContext
    ) -> RunCreationResult:
        """Atomically accept one Run and write its initial canonical events.

        Session selection, concurrency checks, idempotency, Run identity, input
        Items, and `run.accepted`/`run.queued` must become visible together.
        """

        idempotency_scope = (
            context.actor.tenant_id,
            context.actor.principal_type,
            context.actor.principal_id,
            command.idempotency_key,
        )
        async with self._lock:
            start_lock = self._start_locks.setdefault(
                idempotency_scope, asyncio.Lock()
            )
        async with start_lock:
            async with self._lock:
                existing_run_id = self._start_idempotency.get(idempotency_scope)
                existing = (
                    self._runs.get(existing_run_id)
                    if existing_run_id is not None
                    else None
                )
            planned_session_id = (
                existing.session_id
                if existing is not None
                else new_id("session")
                if command.session_concurrency_mode == SessionConcurrencyMode.FORK
                or command.session_id is None
                else command.session_id
            )
            lock_session_ids = [planned_session_id]
            if (
                command.session_concurrency_mode == SessionConcurrencyMode.FORK
                and command.session_id is not None
            ):
                lock_session_ids.append(command.session_id)
            async with self._session_operation(*lock_session_ids):
                return await self._create_run_locked(
                    command,
                    context,
                    idempotency_scope=idempotency_scope,
                    planned_session_id=planned_session_id,
                )

    async def _create_run_locked(
        self,
        command: StartRun,
        context: RequestContext,
        *,
        idempotency_scope: tuple[str | None, PrincipalType, str, str],
        planned_session_id: str,
    ) -> RunCreationResult:
        # Keep the existing atomic state-machine body grouped while the outer
        # per-Session guard owns durability and rollback.
        with nullcontext():
            self._validate_external_input_roles(command.input, context)
            # Start idempotency is scoped to tenant + principal + key. Reusing a
            # key with a different payload is a conflict, not a duplicate.
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
                self._authorize_session_actor_locked(command.session_id, context)
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
                session_id = planned_session_id
            else:
                session_id = planned_session_id

            session = self._sessions.get(session_id)
            if session is None:
                session = _SessionRow(
                    session_id=session_id,
                    revision=0,
                    last_sequence=0,
                    created_at=now,
                    updated_at=now,
                    parent_session_id=parent_session_id,
                    owner=ActorRef(
                        tenant_id=context.actor.tenant_id,
                        principal_type=context.actor.principal_type,
                        principal_id=context.actor.principal_id,
                    ),
                )
                self._sessions[session_id] = session
            else:
                self._authorize_session_actor_locked(session_id, context)

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

            # Keep Run directories naturally ordered and make their creation
            # time visible without giving up the UUID collision guard.
            run_id = new_sortable_id("run", created_at=now)
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
                request_context=context,
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
            await self._settle_storage(self._commit_storage_locked(session_id))
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

        async with self._run_session_operation(command.run_id):
            key = (command.run_id, command.idempotency_key)
            digest = self._digest(command.model_dump(mode="json"))
            previous = self._session_commit_command_results.get(key)
            if previous is not None:
                previous_row = self._runs.get(command.run_id)
                if previous_row is None:
                    raise self._not_found("run.not_found", command.run_id)
                self._authorize_session_actor_locked(previous_row.session_id, context)
                self._require_same_idempotent_request(
                    self._session_commit_command_digests[key], digest
                )
                return previous

            row = self._runs.get(command.run_id)
            if row is None:
                raise self._not_found("run.not_found", command.run_id)
            self._authorize_session_actor_locked(row.session_id, context)
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
            await self._settle_storage(self._commit_storage_locked(row.session_id))
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
        async with self._proposal_session_operation(command.proposal_id):
            key = (command.proposal_id, command.idempotency_key)
            digest = self._digest(
                {
                    "operation": "publish" if publish else "reject",
                    **command.model_dump(mode="json"),
                }
            )
            previous = self._session_commit_command_results.get(key)
            if previous is not None:
                previous_proposal = self._session_commit_proposals.get(
                    command.proposal_id
                )
                if previous_proposal is None:
                    raise self._not_found(
                        "session.commit_proposal_not_found", command.proposal_id
                    )
                self._authorize_session_actor_locked(
                    previous_proposal.session_id, context
                )
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
            self._authorize_session_actor_locked(row.session_id, context)
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
            await self._settle_storage(self._commit_storage_locked(row.session_id))
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
        async with self._session_read(session_id):
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

        async with self._run_session_operation(run_id):
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
                self._authorize_session_actor_locked(previous.run.session_id, context)
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
            self._authorize_session_actor_locked(row.session_id, context)
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
            await self._settle_storage(self._commit_storage_locked(row.session_id))
            self._fanout_locked(run_id, events)
            return result

    async def get_run(self, run_id: str) -> RunSnapshot:
        async with self._run_session_read(run_id):
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            return self._run_snapshot(row)

    async def get_execution_resource(
        self, run_id: str
    ) -> ExecutionResourceRecord | None:
        async with self._run_session_read(run_id):
            if run_id not in self._runs:
                raise self._not_found("run.not_found", run_id)
            return self._execution_resources.get(run_id)

    async def list_pending_execution_releases(
        self,
    ) -> tuple[ExecutionResourceRecord, ...]:
        pending = {
            ExecutionResourceState.RELEASE_BLOCKED,
            ExecutionResourceState.RELEASE_REQUESTED,
            ExecutionResourceState.RELEASE_FAILED,
        }
        async with self._lock:
            return tuple(
                sorted(
                    (
                        record
                        for record in self._execution_resources.values()
                        if record.state in pending
                    ),
                    key=lambda record: (record.updated_at, record.run_id),
                )
            )

    async def list_execution_resources(
        self,
    ) -> tuple[ExecutionResourceRecord, ...]:
        async with self._lock:
            return tuple(
                sorted(
                    self._execution_resources.values(),
                    key=lambda record: (record.updated_at, record.run_id),
                )
            )

    async def commit_execution_resource(
        self,
        *,
        record: ExecutionResourceRecord,
        expected_run_revision: int,
        expected_resource_revision: int | None,
        event_type: str,
        context: RequestContext,
        idempotency_key: str,
    ) -> ExecutionResourceRecord:
        """CAS one Run's replaceable compute binding and append its lifecycle fact."""

        allowed_events = {
            "sandbox.ready",
            "sandbox.resumed",
            "sandbox.release_requested",
            "sandbox.release_blocked",
            "sandbox.release_failed",
            "sandbox.released",
            "sandbox.restore_requested",
            "sandbox.restore_failed",
        }
        if event_type not in allowed_events:
            raise ValueError(f"unsupported execution resource event {event_type!r}")
        run_id = record.run_id
        async with self._run_session_operation(run_id):
            command_key = (run_id, idempotency_key)
            command_digest = self._digest(
                {
                    "record": record.model_dump(mode="json"),
                    "expected_run_revision": expected_run_revision,
                    "expected_resource_revision": expected_resource_revision,
                    "event_type": event_type,
                }
            )
            previous_result = self._execution_resource_command_results.get(command_key)
            if previous_result is not None:
                run = self._runs.get(run_id)
                if run is None:
                    raise self._not_found("run.not_found", run_id)
                self._authorize_session_actor_locked(run.session_id, context)
                self._require_same_idempotent_request(
                    self._execution_resource_command_digests[command_key],
                    command_digest,
                )
                return previous_result

            run = self._runs.get(run_id)
            if run is None:
                raise self._not_found("run.not_found", run_id)
            self._authorize_session_actor_locked(run.session_id, context)
            if run.revision != expected_run_revision:
                raise self._conflict(
                    "run.revision_conflict",
                    f"expected run revision {expected_run_revision}, current {run.revision}",
                )
            previous = self._execution_resources.get(run_id)
            current_resource_revision = previous.revision if previous is not None else None
            if current_resource_revision != expected_resource_revision:
                raise self._conflict(
                    "sandbox.resource_revision_conflict",
                    "execution resource revision changed before commit",
                )
            if record.sandbox_ref.owner_run_id != run_id:
                raise ValueError("sandbox owner_run_id must match resource run_id")
            if (
                record.sandbox_ref.spec_hash != record.sandbox_spec.spec_hash
                or record.sandbox_ref.policy_hash != record.sandbox_spec.policy_hash
            ):
                raise ValueError("sandbox ref and resolved spec hashes must match")
            if record.run_resolved_spec_hash != run.resolved_spec_hash:
                raise self._conflict(
                    "sandbox.policy_stale",
                    "resolved sandbox spec no longer matches the accepted Run",
                )

            next_revision = (current_resource_revision or 0) + 1
            now = self._clock()
            committed = record.model_copy(
                update={"revision": next_revision, "updated_at": now}
            )
            checkpoint = committed.sandbox_checkpoint
            event = EventDraft(
                type=event_type,
                data=SandboxEventData(
                    sandbox_id=committed.sandbox_ref.sandbox_id,
                    state=committed.state.value,
                    generation=committed.generation,
                    disposition=(
                        committed.release_disposition.value
                        if committed.release_disposition is not None
                        else None
                    ),
                    checkpoint_id=(
                        checkpoint.checkpoint_id if checkpoint is not None else None
                    ),
                    compute_released=committed.compute_released,
                    blocking_job_ids=committed.blocking_job_ids,
                    blocking_child_run_ids=committed.blocking_child_run_ids,
                    retry_count=committed.retry_count,
                    error=committed.error,
                ),
            )
            session = self._sessions[run.session_id]
            events = self._prepare_events_locked(
                run,
                session,
                (event,),
                context.actor,
                context.trace.correlation_id,
            )
            run.revision += 1
            run.updated_at = now
            session.revision += 1
            session.updated_at = now
            self._execution_resources[run_id] = committed
            self._execution_resource_command_results[command_key] = committed
            self._execution_resource_command_digests[command_key] = command_digest
            self._persist_events_locked(run, session, events)
            await self._settle_storage(self._commit_storage_locked(run.session_id))
            self._fanout_locked(run_id, events)
            return committed

    async def get_run_result(self, run_id: str) -> RunResult:
        async with self._run_session_read(run_id):
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
            usage_events = 0
            reported_usage_events = 0
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
                    usage_events += 1
                    if data.usage.reported:
                        reported_usage_events += 1
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
                    reported=(
                        usage_events > 0 and reported_usage_events == usage_events
                    ),
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
        async with self._run_session_read(run_id):
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            if row.start_command is None:
                raise self._not_found("run.header_not_found", run_id)
            return row.start_command

    async def get_latest_checkpoint(self, run_id: str) -> Checkpoint:
        async with self._run_session_read(run_id):
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            if row.checkpoint_id is None:
                raise self._not_found("checkpoint.not_found_for_run", run_id)
            return self._checkpoints[row.checkpoint_id]

    async def get_session(self, session_id: str) -> SessionSnapshot:
        async with self._session_read(session_id):
            row = self._sessions.get(session_id)
            if row is None:
                raise self._not_found("session.not_found", session_id)
            return self._session_snapshot(row)

    async def authorize_session_actor(
        self, session_id: str, context: RequestContext
    ) -> None:
        """Check durable ownership without exposing aggregate internals."""

        async with self._session_read(session_id):
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            self._authorize_session_actor_locked(session_id, context)

    async def delete_session(self, session_id: str) -> None:
        for _attempt in range(3):
            async with self._lock:
                session_ids = self._session_tree_ids_locked(session_id)
            async with self._session_operation(*session_ids):
                current = self._session_tree_ids_locked(session_id)
                if current != session_ids:
                    continue
                await self._delete_session_tree_locked(session_id)
                async with self._lock:
                    self._topology_revision += 1
                    for removed_session_id in session_ids:
                        self._session_locks.pop(removed_session_id, None)
                return
        raise self._conflict(
            "session.topology_changed",
            "session tree changed repeatedly while deletion was acquiring locks",
        )

    def _session_tree_ids_locked(self, session_id: str) -> frozenset[str]:
        if session_id not in self._sessions:
            raise self._not_found("session.not_found", session_id)
        session_ids = {session_id}
        while True:
            descendants = {
                row.session_id
                for row in self._sessions.values()
                if row.parent_session_id in session_ids
                and row.session_id not in session_ids
            }
            if not descendants:
                return frozenset(session_ids)
            session_ids.update(descendants)

    async def _delete_session_tree_locked(self, session_id: str) -> None:
        with nullcontext():
            session = self._sessions.get(session_id)
            if session is None:
                raise self._not_found("session.not_found", session_id)
            session_ids = {session_id}
            while True:
                descendants = {
                    row.session_id
                    for row in self._sessions.values()
                    if row.parent_session_id in session_ids
                    and row.session_id not in session_ids
                }
                if not descendants:
                    break
                session_ids.update(descendants)
            run_ids = {
                row.run_id
                for row in self._runs.values()
                if row.session_id in session_ids
            }
            active = [
                self._runs[run_id]
                for run_id in run_ids
                if self._runs[run_id].state not in TERMINAL_RUN_STATES
            ]
            if active:
                raise ConflictError(
                    RuntimeErrorInfo(
                        code="session.active_run",
                        category=ErrorCategory.CONFLICT,
                        message=(
                            f"session tree rooted at {session_id} has an active run"
                        ),
                        retryable=False,
                        safe_to_resume=True,
                        metadata={
                            "root_session_id": session_id,
                            "active_run_ids": sorted(row.run_id for row in active),
                            "active_session_ids": sorted(
                                {row.session_id for row in active}
                            ),
                        },
                    )
                )
            removed_interactions = {
                interaction_id
                for interaction_id, value in self._interactions.items()
                if value.run_id in run_ids
            }
            for removed_session_id in session_ids:
                self._sessions.pop(removed_session_id)
                self._session_events.pop(removed_session_id, None)
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
            for run_id in run_ids:
                self._execution_resources.pop(run_id, None)
            for key in tuple(self._execution_resource_command_results):
                if key[0] in run_ids:
                    self._execution_resource_command_results.pop(key, None)
                    self._execution_resource_command_digests.pop(key, None)
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
                if value.session_id in session_ids
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
                if key[0] not in session_ids
            }
            await self._settle_storage(
                self._delete_storage_locked(session_id, frozenset(session_ids))
            )

    async def list_session_runs(self, session_id: str) -> tuple[RunSnapshot, ...]:
        async with self._session_read(session_id):
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            rows = sorted(
                (row for row in self._runs.values() if row.session_id == session_id),
                key=lambda row: (row.created_at, row.run_id),
            )
            return tuple(self._run_snapshot(row) for row in rows)

    async def list_dispatchable_runs(self) -> tuple[DispatchableRun, ...]:
        """Return root execution intents whose Scheduler work can be rebuilt."""

        async with self._lock:
            active = {
                RunState.QUEUED,
                RunState.RUNNING,
                RunState.SUSPEND_REQUESTED,
                RunState.RESUMING,
            }
            rows = sorted(
                (
                    row
                    for row in self._runs.values()
                    if row.state in active
                    and row.request_context is not None
                    and row.start_command is not None
                    and row.start_command.parent_run_id is None
                ),
                key=lambda row: (row.created_at, row.run_id),
            )
            return tuple(
                DispatchableRun(
                    run=self._run_snapshot(row),
                    context=row.request_context,
                )
                for row in rows
                if row.request_context is not None
            )

    async def list_descendant_sessions(
        self, session_id: str
    ) -> tuple[SessionSnapshot, ...]:
        async with self._lock:
            if session_id not in self._sessions:
                raise self._not_found("session.not_found", session_id)
            descendant_ids: set[str] = set()
            frontier = {session_id}
            while frontier:
                children = {
                    row.session_id
                    for row in self._sessions.values()
                    if row.parent_session_id in frontier
                    and row.session_id not in descendant_ids
                }
                descendant_ids.update(children)
                frontier = children
            rows = sorted(
                (self._sessions[value] for value in descendant_ids),
                key=lambda row: (row.created_at, row.session_id),
            )
            return tuple(self._session_snapshot(row) for row in rows)

    async def read_session_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> tuple[RuntimeEvent, ...]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        async with self._session_read(session_id):
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
        async with self._run_session_read(run_id):
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

        async with self._run_session_read(run_id):
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

    async def forget_session(self, session_id: str) -> None:
        """Forget projections without requiring authoritative Session presence."""

        async with self._lock:
            self._derived_state = {
                key: value
                for key, value in self._derived_state.items()
                if key[0] != session_id
            }

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

        async with self._run_session_operation(command.run_id):
            command_key = (command.run_id, command.idempotency_key)
            command_digest = self._digest(command.model_dump(mode="json"))
            previous = self._command_results.get(command_key)
            if previous is not None:
                self._authorize_session_actor_locked(previous.run.session_id, context)
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
            self._authorize_session_actor_locked(row.session_id, context)
            self._validate_external_input_roles(command.input, context)
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
            await self._settle_storage(self._commit_storage_locked(row.session_id))
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

        async with self._run_session_operation(run_id):
            row = self._runs.get(run_id)
            if row is None:
                raise self._not_found("run.not_found", run_id)
            self._authorize_session_actor_locked(row.session_id, context)
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
            await self._settle_storage(self._commit_storage_locked(row.session_id))
            self._fanout_locked(run_id, events)
            return SteerClaimResult(
                run=self._run_snapshot(row), entries=applied, events=events
            )

    async def list_steers(self, run_id: str) -> tuple[SteerInboxEntry, ...]:
        async with self._run_session_read(run_id):
            if run_id not in self._runs:
                raise self._not_found("run.not_found", run_id)
            return tuple(self._steer_inbox.get(run_id, ()))

    async def resolve_interaction(
        self, command: ReplyInteraction, context: RequestContext
    ) -> CommitResult:
        """Persist one answer and atomically move the suspended Run to RESUMING."""

        async with self._run_session_operation(command.run_id):
            command_key = (command.run_id, command.idempotency_key)
            command_digest = self._digest(command.model_dump(mode="json"))
            previous = self._command_results.get(command_key)
            if previous is not None:
                self._authorize_session_actor_locked(previous.run.session_id, context)
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
            self._authorize_session_actor_locked(row.session_id, context)
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
                        allowed_decisions=interaction.allowed_decisions,
                        payload=interaction.payload,
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
            await self._settle_storage(self._commit_storage_locked(row.session_id))
            self._fanout_locked(row.run_id, events)
            return result

    async def request_resume(
        self, command: ResumeRun, context: RequestContext
    ) -> CommitResult:
        """Accept explicit resume for a non-interaction suspension."""

        async with self._run_session_operation(command.run_id):
            command_key = (command.run_id, command.idempotency_key)
            command_digest = self._digest(command.model_dump(mode="json"))
            previous = self._command_results.get(command_key)
            if previous is not None:
                self._authorize_session_actor_locked(previous.run.session_id, context)
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
            self._authorize_session_actor_locked(row.session_id, context)
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
            await self._settle_storage(self._commit_storage_locked(row.session_id))
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
        async with self._run_session_read(cursor.run_id):
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
                    "owner": (
                        row.owner.model_dump(mode="json")
                        if row.owner is not None
                        else None
                    ),
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
                    "request_context": (
                        row.request_context.model_dump(mode="json")
                        if row.request_context is not None
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
                    "principal_type": scope[1].value,
                    "principal_id": scope[2],
                    "idempotency_key": scope[3],
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
            "execution_resources": [
                value.model_dump(mode="json")
                for value in self._execution_resources.values()
            ],
            "execution_resource_command_results": [
                {
                    "run_id": key[0],
                    "idempotency_key": key[1],
                    "request_digest": self._execution_resource_command_digests[key],
                    "record": value.model_dump(mode="json"),
                }
                for key, value in self._execution_resource_command_results.items()
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

    def _dump_session_state_locked(self, session_id: str) -> dict[str, Any]:
        """Serialize exactly one authoritative Session aggregate.

        Durable per-Session repositories must not serialize every loaded
        aggregate and then discard unrelated rows. Keeping this projection in
        the coordinator also prevents storage adapters from reimplementing the
        canonical ownership rules for Runs, checkpoints, and idempotency data.
        """

        session = self._sessions.get(session_id)
        if session is None:
            raise self._not_found("session.not_found", session_id)
        run_ids = {
            row.run_id for row in self._runs.values() if row.session_id == session_id
        }
        interaction_ids = {
            value.interaction_id
            for value in self._interactions.values()
            if value.run_id in run_ids
        }
        proposals = tuple(
            value
            for value in self._session_commit_proposals.values()
            if value.session_id == session_id
        )
        proposal_ids = {value.proposal_id for value in proposals}
        return {
            "session_format_version": SESSION_AGGREGATE_FORMAT,
            "sessions": [
                {
                    "session_id": session.session_id,
                    "revision": session.revision,
                    "last_sequence": session.last_sequence,
                    "created_at": session.created_at.isoformat(),
                    "updated_at": session.updated_at.isoformat(),
                    "active_serial_run_id": session.active_serial_run_id,
                    "parent_session_id": session.parent_session_id,
                    "owner": (
                        session.owner.model_dump(mode="json")
                        if session.owner is not None
                        else None
                    ),
                    "revision_sequences": {
                        str(revision): sequence
                        for revision, sequence in session.revision_sequences.items()
                    },
                }
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
                    "request_context": (
                        row.request_context.model_dump(mode="json")
                        if row.request_context is not None
                        else None
                    ),
                }
                for row in self._runs.values()
                if row.run_id in run_ids
            ],
            "run_events": {
                run_id: [event.model_dump(mode="json") for event in events]
                for run_id, events in self._run_events.items()
                if run_id in run_ids
            },
            "fork_base_events": {
                run_id: [event.model_dump(mode="json") for event in events]
                for run_id, events in self._fork_base_events.items()
                if run_id in run_ids and events
            },
            "start_idempotency": [
                {
                    "tenant_id": scope[0],
                    "principal_type": scope[1].value,
                    "principal_id": scope[2],
                    "idempotency_key": scope[3],
                    "run_id": run_id,
                    "request_digest": self._start_idempotency_digests[scope],
                }
                for scope, run_id in self._start_idempotency.items()
                if run_id in run_ids
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
                if key[0] in run_ids
            ],
            "execution_resources": [
                value.model_dump(mode="json")
                for value in self._execution_resources.values()
                if value.run_id in run_ids
            ],
            "execution_resource_command_results": [
                {
                    "run_id": key[0],
                    "idempotency_key": key[1],
                    "request_digest": self._execution_resource_command_digests[key],
                    "record": value.model_dump(mode="json"),
                }
                for key, value in self._execution_resource_command_results.items()
                if key[0] in run_ids
            ],
            "checkpoints": [
                value.model_dump(mode="json")
                for value in self._checkpoints.values()
                if value.run_id in run_ids
            ],
            "suspensions": [
                value.model_dump(mode="json")
                for value in self._suspensions.values()
                if value.run_id in run_ids
            ],
            "interactions": [
                value.model_dump(mode="json")
                for value in self._interactions.values()
                if value.run_id in run_ids
            ],
            "interaction_resolutions": [
                value.model_dump(mode="json")
                for value in self._interaction_resolutions.values()
                if value.interaction_id in interaction_ids
            ],
            "steer_inbox": {
                run_id: [entry.model_dump(mode="json") for entry in entries]
                for run_id, entries in self._steer_inbox.items()
                if run_id in run_ids
            },
            "session_commit_proposals": [
                value.model_dump(mode="json") for value in proposals
            ],
            "session_commit_command_results": [
                {
                    "target_id": key[0],
                    "idempotency_key": key[1],
                    "request_digest": self._session_commit_command_digests[key],
                    "proposal": value.model_dump(mode="json"),
                }
                for key, value in self._session_commit_command_results.items()
                if value.proposal_id in proposal_ids
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
                owner=(
                    ActorRef.model_validate(value["owner"])
                    if value.get("owner") is not None
                    else None
                ),
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
                request_context=(
                    RequestContext.model_validate(value["request_context"])
                    if value.get("request_context") is not None
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

        for session_id, session_row in sessions.items():
            if session_row.owner is None:
                session_row.owner = self._derive_session_owner(
                    session_id, runs=runs, session_events=session_events
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
                self._start_principal_type(value, runs),
                value["principal_id"],
                value["idempotency_key"],
            ): value["run_id"]
            for value in payload.get("start_idempotency", ())
        }
        self._start_idempotency_digests = {
            (
                value.get("tenant_id"),
                self._start_principal_type(value, runs),
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
        self._execution_resources = {
            value["run_id"]: ExecutionResourceRecord.model_validate(value)
            for value in payload.get("execution_resources", ())
        }
        if set(self._execution_resources) - set(runs):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session_store.corrupt_state",
                    category=ErrorCategory.CORRUPT_STATE,
                    message="execution resource references a missing Run",
                )
            )
        self._execution_resource_command_results = {}
        self._execution_resource_command_digests = {}
        for value in payload.get("execution_resource_command_results", ()):
            key = (value["run_id"], value["idempotency_key"])
            result = ExecutionResourceRecord.model_validate(value["record"])
            if result.run_id not in runs:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="session_store.corrupt_state",
                        category=ErrorCategory.CORRUPT_STATE,
                        message="execution resource command references a missing Run",
                    )
                )
            self._execution_resource_command_results[key] = result
            self._execution_resource_command_digests[key] = value["request_digest"]
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

    async def _delete_storage_locked(
        self, session_id: str, deleted_session_ids: frozenset[str]
    ) -> None:
        """Durability hook for removing one authoritative Session tree."""

    def _authorize_session_actor_locked(
        self, session_id: str, context: RequestContext
    ) -> None:
        """Enforce the durable Session owner at every context-bearing mutation.

        Older aggregates did not store a dedicated owner column, but every
        acknowledged Run stores its RequestContext or at least durable events
        with the original actor.  Deriving the owner from those facts preserves
        backwards compatibility without leaving legacy Sessions unprotected.
        """

        actor = context.actor
        if "session.admin" in actor.scopes:
            return
        session = self._sessions.get(session_id)
        owner = session.owner if session is not None else None
        if owner is None:
            owner = self._derive_session_owner(
                session_id, runs=self._runs, session_events=self._session_events
            )
        if owner is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session.owner_not_established",
                    category=ErrorCategory.AUTHORIZATION,
                    message="target Session has no verifiable durable owner",
                    safe_to_resume=False,
                )
            )
        if (
            owner.tenant_id != actor.tenant_id
            or owner.principal_type != actor.principal_type
            or owner.principal_id != actor.principal_id
        ):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session.actor_not_authorized",
                    category=ErrorCategory.AUTHORIZATION,
                    message="actor does not own the target Session",
                    safe_to_resume=True,
                )
            )

    @staticmethod
    def _derive_session_owner(
        session_id: str,
        *,
        runs: dict[str, _RunRow],
        session_events: dict[str, list[RuntimeEvent]],
    ) -> ActorRef | None:
        owner = next(
            (
                row.request_context.actor
                for row in sorted(
                    (
                        value
                        for value in runs.values()
                        if value.session_id == session_id
                        and value.request_context is not None
                    ),
                    key=lambda value: (value.created_at, value.run_id),
                )
            ),
            None,
        )
        if owner is None:
            owner = next(
                (
                    event.actor
                    for event in session_events.get(session_id, ())
                    if event.type == "run.accepted"
                ),
                None,
            )
        if owner is None:
            return None
        return ActorRef(
            tenant_id=owner.tenant_id,
            principal_type=owner.principal_type,
            principal_id=owner.principal_id,
        )

    @staticmethod
    def _start_principal_type(
        value: dict[str, Any], runs: dict[str, _RunRow]
    ) -> PrincipalType:
        configured = value.get("principal_type")
        if configured is not None:
            return PrincipalType(configured)
        run = runs.get(value["run_id"])
        if run is not None and run.request_context is not None:
            return run.request_context.actor.principal_type
        raise SageV2Error(
            RuntimeErrorInfo(
                code="session_store.owner_not_established",
                category=ErrorCategory.CORRUPT_STATE,
                message="legacy StartRun idempotency has no verifiable principal type",
                safe_to_resume=False,
            )
        )

    @staticmethod
    def _validate_external_input_roles(items, context: RequestContext) -> None:
        """Keep privileged prompt roles behind an explicit trusted-host scope."""

        privileged = tuple(
            item.role for item in items if item.role in {"system", "developer"}
        )
        if privileged and "session.trusted_input" not in context.actor.scopes:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="session.privileged_input_role_denied",
                    category=ErrorCategory.AUTHORIZATION,
                    message=(
                        "system/developer input is reserved for trusted host "
                        "context composition"
                    ),
                    safe_to_resume=True,
                    metadata={"roles": sorted(set(privileged))},
                )
            )

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

        The copy removes mutable runtime coupling between parent and child.
        ``parent_session_id`` still expresses ownership: deleting a parent
        recursively deletes every descendant Session.
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
