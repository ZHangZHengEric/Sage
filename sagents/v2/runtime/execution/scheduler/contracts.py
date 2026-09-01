"""SAgents V2 module for runtime/execution/scheduler/contracts.py."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from sagents.v2.contracts.common import Identifier, StrictModel


class LeaseReleaseReason(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    WORKER_SHUTDOWN = "worker_shutdown"


class SchedulerCapabilities(StrictModel):
    api_version: Literal["2"] = "2"
    durable_across_process_restart: bool
    supports_priority: bool
    supports_delayed_work: bool
    supports_leases: bool
    supports_fencing: bool
    supports_distributed_claims: bool = False
    supports_atomic_tenant_quota: bool = False
    # The provider can keep a validated lease authoritative for the complete
    # duration of one callback.  The core does not prescribe how: an in-process
    # provider may hold a lock, while a distributed plugin may use a database
    # transaction, advisory lock, or another linearizable primitive.
    supports_atomic_fenced_mutations: bool = False
    max_pending_items: int | None = Field(default=None, gt=0)
    max_retained_terminal_items: int | None = Field(default=None, ge=0)


class SchedulerClaimPolicy(StrictModel):
    """Atomic eligibility policy applied by a Scheduler during claim."""

    max_active_per_tenant: int | None = Field(default=None, gt=0)


class WorkItem(StrictModel):
    work_id: Identifier
    run_id: Identifier
    tenant_id: Identifier | None = None
    priority: int = Field(default=0, ge=-100, le=100)
    available_at: datetime
    attempt: int = Field(default=1, ge=1)
    idempotency_key: Identifier
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkerLease(StrictModel):
    lease_id: Identifier
    work: WorkItem
    worker_id: Identifier
    fencing_token: int = Field(ge=1)
    acquired_at: datetime
    expires_at: datetime
