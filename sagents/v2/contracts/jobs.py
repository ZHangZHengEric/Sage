"""SAgents V2 module for contracts/jobs.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel
from sagents.v2.contracts.errors import RuntimeErrorInfo
from sagents.v2.contracts.items import ArtifactRef, UsageSummary


class JobState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    STOPPING = "stopping"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"
    ORPHANED = "orphaned"


class JobPauseBehavior(str, Enum):
    CONTINUE = "continue"
    SUSPEND = "suspend"
    DETACH = "detach"
    CANCEL = "cancel"


class JobCursor(StrictModel):
    job_id: Identifier
    offset: int = Field(default=0, ge=0)


class JobHandle(StrictModel):
    job_id: Identifier
    owner_run_id: Identifier
    kind: Identifier
    state: JobState
    pause_behavior: JobPauseBehavior = JobPauseBehavior.DETACH
    output_cursor: JobCursor
    external_handle_ref: str | None = None


class JobSnapshot(JobHandle):
    created_at: datetime
    updated_at: datetime
    exit_code: int | None = None
    output_artifacts: tuple[ArtifactRef, ...] = ()
    usage: UsageSummary = Field(default_factory=UsageSummary)
    error: RuntimeErrorInfo | None = None


class JobRuntimeCapabilities(StrictModel):
    api_version: Literal["2"] = "2"
    durable_across_process_restart: bool
    supports_reconnect: bool
    supports_adoption: bool
    supports_suspend: bool
    supports_output_cursor: bool
    max_concurrent_jobs: int | None = Field(default=None, gt=0)


class JobSpec(StrictModel):
    owner_run_id: Identifier
    kind: Identifier
    payload: dict[str, Any] = Field(default_factory=dict)
    pause_behavior: JobPauseBehavior = JobPauseBehavior.DETACH
    idempotency_key: Identifier
    max_output_bytes: int | None = Field(default=None, gt=0)


class JobOutputChunk(StrictModel):
    job_id: Identifier
    stream: Literal["stdout", "stderr", "progress"]
    offset: int = Field(ge=0)
    next_offset: int = Field(ge=0)
    data: bytes
    occurred_at: datetime


class JobCompletion(StrictModel):
    exit_code: int = 0
    usage: UsageSummary = Field(default_factory=UsageSummary)
