"""SAgents V2 module for runtime/session/fencing.py."""

from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar

from sagents.v2.runtime.execution.scheduler import Scheduler, WorkerLease
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)


_ACTIVE_LEASE: ContextVar[WorkerLease | None] = ContextVar(
    "sage_v2_active_worker_lease", default=None
)


class LeaseFencedSessionStore:
    """SessionStore decorator that rejects writes from stale executor leases."""

    def __init__(self, session_store, scheduler: Scheduler) -> None:
        self.session_store = session_store
        self.scheduler = scheduler

    @property
    def capabilities(self):
        return {**self.session_store.capabilities, "requires_worker_fence": True}

    def __getattr__(self, name):
        return getattr(self.session_store, name)

    @asynccontextmanager
    async def lease_scope(self, lease: WorkerLease):
        await self.scheduler.assert_fence(lease)
        token = _ACTIVE_LEASE.set(lease)
        try:
            yield self
        finally:
            _ACTIVE_LEASE.reset(token)

    async def commit_run(self, *args, **kwargs):
        run_id = kwargs.get("run_id") or (args[0] if args else None)
        await self._assert_active_fence(run_id)
        return await self.session_store.commit_run(*args, **kwargs)

    async def claim_steers(self, *args, **kwargs):
        run_id = kwargs.get("run_id") or (args[0] if args else None)
        await self._assert_active_fence(run_id)
        return await self.session_store.claim_steers(*args, **kwargs)

    async def _assert_active_fence(self, run_id):
        lease = _ACTIVE_LEASE.get()
        if lease is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="scheduler.worker_lease_required",
                    category=ErrorCategory.AUTHORIZATION,
                    message="executor mutation requires an active worker lease",
                    safe_to_resume=True,
                )
            )
        if lease.work.run_id != run_id:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="scheduler.fence_rejected",
                    category=ErrorCategory.CONFLICT,
                    message="worker lease does not own this run",
                    safe_to_resume=True,
                )
            )
        await self.scheduler.assert_fence(lease)
