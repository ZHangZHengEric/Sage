"""Explicit publication contract for snapshot-isolated Session Runs.

Snapshot isolation is useful only when its output can remain private until a
caller deliberately publishes it.  These contracts make that second phase a
first-class, optimistic-CAS operation instead of silently changing Session
history when a background Run happens to finish.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel


class SessionCommitProposalStatus(str, Enum):
    """Durable lifecycle of one snapshot publication proposal."""

    PENDING = "pending"
    PUBLISHED = "published"
    REJECTED = "rejected"


class SessionMergeStrategy(str, Enum):
    """How publication treats Session facts committed after the snapshot base."""

    # Safe default: publication succeeds only when no other Run wrote durable
    # facts after the snapshot's base boundary.
    REQUIRE_UNCHANGED_BASE = "require_unchanged_base"
    # Explicit conversational merge: retain current canonical history and make
    # the snapshot transcript visible as an additional branch result.
    APPEND_AFTER_CURRENT = "append_after_current"


class SessionCommitProposal(StrictModel):
    """Immutable snapshot content plus the mutable publication decision."""

    proposal_id: Identifier
    session_id: Identifier
    source_run_id: Identifier
    source_run_revision: int = Field(ge=0)
    revision: int = Field(default=0, ge=0)
    status: SessionCommitProposalStatus = SessionCommitProposalStatus.PENDING
    base_session_revision: int = Field(ge=0)
    base_session_sequence: int = Field(ge=0)
    # The Session boundary at which the proposal itself was recorded. A later
    # publish/reject command still supplies an exact current Session CAS.
    proposed_session_revision: int = Field(ge=0)
    proposed_session_sequence: int = Field(ge=0)
    proposed_event_ids: tuple[Identifier, ...]
    proposed_event_digest: str
    conflicting_run_ids: tuple[Identifier, ...] = ()
    merge_strategy: SessionMergeStrategy | None = None
    published_session_revision: int | None = Field(default=None, ge=0)
    published_session_sequence: int | None = Field(default=None, ge=0)
    rejection_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class ProposeSessionCommit(StrictModel):
    """Create an auditable proposal for one completed snapshot Run."""

    run_id: Identifier
    expected_run_revision: int = Field(ge=0)
    idempotency_key: Identifier


class PublishSessionCommit(StrictModel):
    """Publish a pending proposal with Session and proposal CAS guards."""

    proposal_id: Identifier
    expected_proposal_revision: int = Field(ge=0)
    expected_session_revision: int = Field(ge=0)
    merge_strategy: SessionMergeStrategy = SessionMergeStrategy.REQUIRE_UNCHANGED_BASE
    idempotency_key: Identifier


class RejectSessionCommit(StrictModel):
    """Record that a pending proposal must never enter canonical history."""

    proposal_id: Identifier
    expected_proposal_revision: int = Field(ge=0)
    expected_session_revision: int = Field(ge=0)
    idempotency_key: Identifier
    reason: str = "rejected_by_user"
