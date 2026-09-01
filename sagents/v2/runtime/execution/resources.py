"""Durable state for one Run's replaceable execution binding."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.runtime.execution.sandbox import (
    ResolvedSandboxSpec,
    SandboxCheckpointRef,
    SandboxRef,
    SandboxReleaseDisposition,
)


class ExecutionResourceState(str, Enum):
    ACTIVE = "active"
    RELEASE_BLOCKED = "release_blocked"
    RELEASE_REQUESTED = "release_requested"
    RELEASE_FAILED = "release_failed"
    RELEASED = "released"
    RESTORE_REQUESTED = "restore_requested"


class ExecutionResourceRecord(StrictModel):
    run_id: Identifier
    generation: int = Field(ge=1)
    sandbox_ref: SandboxRef
    sandbox_spec: ResolvedSandboxSpec
    run_resolved_spec_hash: str
    state: ExecutionResourceState
    revision: int = Field(default=0, ge=0)
    release_disposition: SandboxReleaseDisposition | None = None
    sandbox_checkpoint: SandboxCheckpointRef | None = None
    suspension_id: Identifier | None = None
    suspension_reason: str | None = None
    blocking_job_ids: tuple[Identifier, ...] = ()
    blocking_child_run_ids: tuple[Identifier, ...] = ()
    release_idempotency_key: Identifier | None = None
    release_requested_at: datetime | None = None
    released_at: datetime | None = None
    compute_released: bool = False
    retry_count: int = Field(default=0, ge=0)
    next_retry_at: datetime | None = None
    error: RuntimeErrorInfo | None = None
    updated_at: datetime


class ExecutionLifecycleMetrics(StrictModel):
    active_sandboxes: int = Field(ge=0)
    retained_sandboxes: int = Field(ge=0)
    pending_releases: int = Field(ge=0)
    release_failure_count: int = Field(ge=0)
    release_retry_count: int = Field(ge=0)
    max_blocked_age_seconds: float = Field(ge=0)
    average_release_latency_seconds: float = Field(ge=0)


__all__ = [
    "ExecutionLifecycleMetrics",
    "ExecutionResourceRecord",
    "ExecutionResourceState",
]
