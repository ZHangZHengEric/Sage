"""Checksummed records used by :class:`FilesystemSessionStore`.

Version 1 appended a complete Session aggregate for every accepted mutation.
Version 2 atomically replaced that aggregate on every mutation. Version 3 used
a compact snapshot plus an untyped delta journal. Version 4 keeps the compact
layout but validates typed aggregate rows and discriminated mutations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.commands import StartRun, SteerInboxEntry
from sagents.v2.contracts.events import RuntimeEvent
from sagents.v2.contracts.run_state import (
    RunSnapshot,
    RunState,
    SessionConcurrencyMode,
    SessionSnapshot,
)
from sagents.v2.contracts.checkpoint import Checkpoint, Suspension
from sagents.v2.contracts.interactions import InteractionRequest, InteractionResolution
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.session_commit import SessionCommitProposal
from sagents.v2.runtime.execution.resources import ExecutionResourceRecord


FILESYSTEM_SESSION_STORE_FORMAT_V1: Literal["sage.filesystem-session-store/v1"] = (
    "sage.filesystem-session-store/v1"
)
FILESYSTEM_SESSION_STORE_FORMAT_V2: Literal["sage.filesystem-session-store/v2"] = (
    "sage.filesystem-session-store/v2"
)
FILESYSTEM_SESSION_STORE_FORMAT_V3: Literal["sage.filesystem-session-store/v3"] = (
    "sage.filesystem-session-store/v3"
)
FILESYSTEM_SESSION_STORE_FORMAT: Literal["sage.filesystem-session-store/v4"] = (
    "sage.filesystem-session-store/v4"
)

SESSION_AGGREGATE_SNAPSHOT_FORMAT = "sage.session-aggregate/v2"


class SessionRowSnapshot(StrictModel):
    session_id: str
    revision: int
    last_sequence: int
    created_at: datetime
    updated_at: datetime
    active_serial_run_id: str | None = None
    parent_session_id: str | None = None
    owner: ActorRef | None = None
    revision_sequences: dict[str, int]


class RunRowSnapshot(StrictModel):
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


class StartIdempotencySnapshot(StrictModel):
    tenant_id: str | None = None
    principal_type: PrincipalType | None = None
    principal_id: str
    idempotency_key: str
    run_id: str
    request_digest: str


class CommandResultValue(StrictModel):
    run: RunSnapshot
    session: SessionSnapshot
    events: tuple[RuntimeEvent, ...]


class CommandResultSnapshot(StrictModel):
    run_id: str
    idempotency_key: str
    request_digest: str
    result: CommandResultValue


class SessionCommitCommandResultSnapshot(StrictModel):
    target_id: str
    idempotency_key: str
    request_digest: str
    proposal: SessionCommitProposal


class CoordinatorCommandSnapshot(StrictModel):
    idempotency_key: str
    request_digest: str
    result_revision: int


class ExecutionResourceCommandResultSnapshot(StrictModel):
    run_id: str
    idempotency_key: str
    request_digest: str
    record: ExecutionResourceRecord


class SessionAggregateSnapshotV2(StrictModel):
    """Typed, transport-independent state for exactly one Session aggregate."""

    session_format_version: Literal["sage.session-aggregate/v2"] = (
        SESSION_AGGREGATE_SNAPSHOT_FORMAT
    )
    sessions: tuple[SessionRowSnapshot, ...]
    runs: tuple[RunRowSnapshot, ...] = ()
    run_events: dict[str, tuple[RuntimeEvent, ...]] = {}
    fork_base_events: dict[str, tuple[RuntimeEvent, ...]] = {}
    start_idempotency: tuple[StartIdempotencySnapshot, ...] = ()
    command_results: tuple[CommandResultSnapshot, ...] = ()
    execution_resources: tuple[ExecutionResourceRecord, ...] = ()
    execution_resource_command_results: tuple[
        ExecutionResourceCommandResultSnapshot, ...
    ] = ()
    checkpoints: tuple[Checkpoint, ...] = ()
    suspensions: tuple[Suspension, ...] = ()
    interactions: tuple[InteractionRequest, ...] = ()
    interaction_resolutions: tuple[InteractionResolution, ...] = ()
    steer_inbox: dict[str, tuple[SteerInboxEntry, ...]] = {}
    session_commit_proposals: tuple[SessionCommitProposal, ...] = ()
    session_commit_command_results: tuple[SessionCommitCommandResultSnapshot, ...] = ()
    coordinator_command_results: tuple[CoordinatorCommandSnapshot, ...] = ()


class SessionCommitEnvelope(StrictModel):
    """Legacy v1 append-only full-state record, used only for migration."""

    format: Literal["sage.filesystem-session-store/v1"] = (
        FILESYSTEM_SESSION_STORE_FORMAT_V1
    )
    transaction_id: str
    journal_sequence: int
    previous_session_revision: int
    current_session_revision: int
    state: dict[str, Any]
    checksum: str


class SessionSnapshotEnvelope(StrictModel):
    """Compact v4 base state for one Session."""

    format: Literal["sage.filesystem-session-store/v4"] = (
        FILESYSTEM_SESSION_STORE_FORMAT
    )
    write_id: str
    current_session_revision: int
    state: SessionAggregateSnapshotV2
    checksum: str


class SessionSnapshotEnvelopeV2(StrictModel):
    """Legacy v2 atomically replaced aggregate, used for forward migration."""

    format: Literal["sage.filesystem-session-store/v2"] = (
        FILESYSTEM_SESSION_STORE_FORMAT_V2
    )
    write_id: str
    current_session_revision: int
    state: dict[str, Any]
    checksum: str


class SessionSnapshotEnvelopeV3(StrictModel):
    """Legacy v3 compact base state, retained for read compatibility."""

    format: Literal["sage.filesystem-session-store/v3"] = (
        FILESYSTEM_SESSION_STORE_FORMAT_V3
    )
    write_id: str
    current_session_revision: int
    state: dict[str, Any]
    checksum: str


class SessionStateDeltaMutation(StrictModel):
    kind: Literal["state_delta"] = "state_delta"
    upserts: dict[str, list[dict[str, Any]]] = {}
    deletes: dict[str, list[list[Any]]] = {}
    appends: dict[str, dict[str, list[dict[str, Any]]]] = {}
    replacements: dict[str, dict[str, list[dict[str, Any]]]] = {}
    map_deletes: dict[str, list[str]] = {}


class SessionMutationEnvelope(StrictModel):
    """One revision-contiguous, discriminated v4 mutation."""

    format: Literal["sage.filesystem-session-journal/v4"] = (
        "sage.filesystem-session-journal/v4"
    )
    mutation_id: str
    previous_session_revision: int
    current_session_revision: int
    mutation: SessionStateDeltaMutation
    checksum: str


class SessionMutationEnvelopeV3(StrictModel):
    """Legacy v3 untyped delta, retained for read compatibility."""

    format: Literal["sage.filesystem-session-journal/v3"] = (
        "sage.filesystem-session-journal/v3"
    )
    mutation_id: str
    previous_session_revision: int
    current_session_revision: int
    delta: dict[str, Any]
    checksum: str
