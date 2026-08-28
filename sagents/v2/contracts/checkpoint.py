"""SAgents V2 module for contracts/checkpoint.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel


class SuspensionReason(str, Enum):
    APPROVAL_REQUIRED = "approval_required"
    PERMISSION_REQUIRED = "permission_required"
    INPUT_REQUIRED = "input_required"
    MANUAL_PAUSE = "manual_pause"
    EXTERNAL_EVENT = "external_event"
    RESOURCE_WAIT = "resource_wait"
    POLICY_HOLD = "policy_hold"


class SuspensionStatus(str, Enum):
    PENDING = "pending"
    RESOLVING = "resolving"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class Checkpoint(StrictModel):
    """Versioned driver state required to continue the same Run safely.

    Payloads are driver-specific. `checkpoint_codec_version` tells a resumer
    whether `state` belongs to Agent Loop, Flow, or another Run driver.
    """

    checkpoint_id: Identifier
    checkpoint_codec_version: str
    session_id: Identifier
    run_id: Identifier
    run_sequence: int = Field(ge=0)
    session_revision: int = Field(ge=0)
    state: dict[str, Any]
    resolved_spec_hash: str
    created_at: datetime


class Suspension(StrictModel):
    """Durable reason and resume barrier associated with a Checkpoint."""

    suspension_id: Identifier
    run_id: Identifier
    reason: SuspensionReason
    status: SuspensionStatus = SuspensionStatus.PENDING
    blocking_scope: str
    checkpoint_id: Identifier
    checkpoint_sequence: int = Field(ge=0)
    interaction_id: Identifier | None = None
    expected_revision: int = Field(default=0, ge=0)
    resume_policy: str
    requested_at: datetime
    expires_at: datetime | None = None
