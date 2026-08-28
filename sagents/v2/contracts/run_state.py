"""SAgents V2 module for contracts/run_state.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import AsyncIterator, Protocol

from pydantic import Field, model_validator

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.items import ArtifactRef, ItemSnapshot, UsageSummary


# A Session is the long-lived context boundary; a Run is one execution against
# that context. This mode controls consistency when the Run is accepted. It is
# unrelated to Python task scheduling or the number of event subscribers.
class SessionConcurrencyMode(str, Enum):
    """Consistency rule used when accepting a Run into a Session."""

    # The normal conversation mode: one non-terminal writer on the latest
    # Session revision.
    SERIAL = "serial"
    # Execute from a stable base. Publishing is a separate explicit
    # SessionCommitProposal operation with conflict inspection and Session CAS.
    SNAPSHOT_ISOLATED = "snapshot_isolated"
    # Create a child Session. Delegated agents use this mode to isolate their
    # model/tool transcript from the parent conversation.
    FORK = "fork"


class RunState(str, Enum):
    """Durable lifecycle of one execution request.

    `SUSPENDED` is intentionally non-terminal. Stream EOF, observer detach, and
    execution termination are separate concepts.
    """

    QUEUED = "queued"
    RUNNING = "running"
    # A pause command was accepted; the driver still needs to reach a safe point
    # and write a complete Checkpoint.
    SUSPEND_REQUESTED = "suspend_requested"
    SUSPENDED = "suspended"
    # Resume was accepted; a driver must restore the Checkpoint and mark the Run
    # RUNNING before it executes another Step.
    RESUMING = "resuming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATES = frozenset(
    {RunState.COMPLETED, RunState.FAILED, RunState.CANCELLED}
)


class EventCursor(StrictModel):
    """Exclusive replay cursor for one Run event stream."""

    run_id: Identifier
    # Subscribers receive events whose sequence is strictly greater than this.
    run_sequence: int = Field(default=0, ge=0)


class RunHandle(StrictModel):
    """Stable identity and acceptance metadata returned before execution ends."""

    session_id: Identifier
    run_id: Identifier
    state: RunState
    run_revision: int = Field(ge=0)
    concurrency_mode: SessionConcurrencyMode
    base_session_revision: int = Field(ge=0)
    # Stable event boundary used to build this Run's initial model history. A
    # revision alone is not replayable because one SessionStore transaction can
    # append several canonical events.
    base_session_sequence: int = Field(ge=0)
    accepted_session_revision: int = Field(ge=0)
    event_cursor: EventCursor
    resolved_spec_hash: str


class SessionSnapshot(StrictModel):
    """Current metadata for the long-lived canonical context container."""

    session_id: Identifier
    revision: int = Field(ge=0)
    last_sequence: int = Field(ge=0)
    active_serial_run_id: Identifier | None = None
    parent_session_id: Identifier | None = None
    created_at: datetime
    updated_at: datetime


class RunSnapshot(StrictModel):
    """Current durable state of one execution inside a Session."""

    session_id: Identifier
    run_id: Identifier
    state: RunState
    revision: int = Field(ge=0)
    last_run_sequence: int = Field(ge=0)
    concurrency_mode: SessionConcurrencyMode
    base_session_revision: int = Field(ge=0)
    base_session_sequence: int = Field(ge=0)
    accepted_session_revision: int = Field(ge=0)
    resolved_spec_hash: str
    suspension_id: Identifier | None = None
    checkpoint_id: Identifier | None = None
    created_at: datetime
    updated_at: datetime


class RunResult(StrictModel):
    """Terminal projection for a completed, failed, or cancelled Run."""

    session_id: Identifier
    run_id: Identifier
    outcome: RunState
    final_items: tuple[ItemSnapshot, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    usage: UsageSummary = Field(default_factory=UsageSummary)
    error: RuntimeErrorInfo | None = None
    completed_at: datetime
    final_cursor: EventCursor

    @model_validator(mode="after")
    def validate_terminal_outcome(self) -> "RunResult":
        if self.outcome not in TERMINAL_RUN_STATES:
            raise ValueError("RunResult outcome must be terminal")
        if self.outcome == RunState.FAILED and self.error is None:
            raise ValueError("failed RunResult requires error")
        return self


class RunStream(Protocol):
    handle: RunHandle
    events: AsyncIterator["RuntimeEvent"]

    async def detach(self) -> None: ...


from sagents.v2.contracts.events import RuntimeEvent  # noqa: E402
