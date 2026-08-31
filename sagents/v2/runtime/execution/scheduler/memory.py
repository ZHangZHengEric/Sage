"""In-process reference Scheduler for priority, quota, leases, and fencing."""

from __future__ import annotations

import asyncio
import heapq
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Protocol

from sagents.v2.runtime.execution.scheduler.contracts import (
    LeaseReleaseReason,
    SchedulerCapabilities,
    WorkItem,
    WorkerLease,
)
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)


class InMemoryScheduler:
    """Deterministic single-process scheduler used to prove the async contract.

    Leases and quotas are real within this object but are not coordinated across
    processes. A production worker fleet requires a durable distributed lease
    provider implementing the same port. Claims are monotonically fenced and
    concurrency is bounded here so the reference still exercises those rules.
    """

    api_version = "2"

    def __init__(
        self,
        *,
        max_pending_items: int = 1024,
        clock: Callable[[], datetime] = utc_now,
        state_store: "SchedulerStateStore | None" = None,
    ) -> None:
        if max_pending_items < 1:
            raise ValueError("max_pending_items must be positive")
        self._max_pending = max_pending_items
        self._clock = clock
        self._condition = asyncio.Condition()
        self._pending: list[tuple[float, int, int, str]] = []
        self._items: dict[str, WorkItem] = {}
        self._idempotency: dict[str, str] = {}
        self._leases: dict[str, WorkerLease] = {}
        self._work_lease: dict[str, str] = {}
        self._run_lease: dict[str, str] = {}
        self._fence_counters: dict[str, int] = {}
        self._cancelled: set[str] = set()
        self._sequence = 0
        self._closed = False
        self._state_store = state_store
        if state_store is not None:
            restored = state_store.load()
            if restored is not None:
                self._load_state(restored)

    async def capabilities(self) -> SchedulerCapabilities:
        return SchedulerCapabilities(
            durable_across_process_restart=False,
            supports_priority=True,
            supports_delayed_work=True,
            supports_leases=True,
            supports_fencing=True,
            max_pending_items=self._max_pending,
        )

    async def submit(self, work: WorkItem) -> bool:
        async with self._condition:
            self._ensure_open()
            if work.idempotency_key in self._idempotency:
                return False
            if work.work_id in self._items:
                raise self._error(
                    "scheduler.work_id_conflict",
                    ErrorCategory.CONFLICT,
                    "work_id already exists with another idempotency key",
                )
            active_pending = sum(
                1
                for work_id in self._items
                if work_id not in self._work_lease and work_id not in self._cancelled
            )
            if active_pending >= self._max_pending:
                raise self._error(
                    "scheduler.queue_full",
                    ErrorCategory.RATE_LIMITED,
                    "scheduler pending queue is full",
                    retryable=True,
                )
            self._items[work.work_id] = work
            self._idempotency[work.idempotency_key] = work.work_id
            self._push_locked(work)
            await self._persist_locked()
            self._condition.notify_all()
            return True

    async def claim(
        self,
        worker_id: str,
        *,
        lease_duration: timedelta,
        wait_timeout: float | None = None,
    ) -> WorkerLease | None:
        if lease_duration.total_seconds() <= 0:
            raise ValueError("lease_duration must be positive")

        async def wait_for_claim() -> WorkerLease | None:
            async with self._condition:
                while True:
                    self._ensure_open()
                    reaped = self._reap_expired_locked()
                    work = self._pop_available_locked()
                    if work is not None:
                        now = self._clock()
                        token = self._fence_counters.get(work.run_id, 0) + 1
                        self._fence_counters[work.run_id] = token
                        lease = WorkerLease(
                            lease_id=new_id("lease"),
                            work=work,
                            worker_id=worker_id,
                            fencing_token=token,
                            acquired_at=now,
                            expires_at=now + lease_duration,
                        )
                        self._leases[lease.lease_id] = lease
                        self._work_lease[work.work_id] = lease.lease_id
                        self._run_lease[work.run_id] = lease.lease_id
                        await self._persist_locked()
                        return lease
                    if reaped:
                        await self._persist_locked()
                    delay = self._seconds_until_next_locked()
                    if delay is None:
                        await self._condition.wait()
                    else:
                        try:
                            await asyncio.wait_for(
                                self._condition.wait(), timeout=max(delay, 0.001)
                            )
                        except asyncio.TimeoutError:
                            pass

        if wait_timeout is None:
            return await wait_for_claim()
        if wait_timeout < 0:
            raise ValueError("wait_timeout must be non-negative")
        if wait_timeout == 0:
            async with self._condition:
                self._ensure_open()
                reaped = self._reap_expired_locked()
                work = self._pop_available_locked()
                if work is None:
                    if reaped:
                        await self._persist_locked()
                    return None
                now = self._clock()
                token = self._fence_counters.get(work.run_id, 0) + 1
                self._fence_counters[work.run_id] = token
                lease = WorkerLease(
                    lease_id=new_id("lease"),
                    work=work,
                    worker_id=worker_id,
                    fencing_token=token,
                    acquired_at=now,
                    expires_at=now + lease_duration,
                )
                self._leases[lease.lease_id] = lease
                self._work_lease[work.work_id] = lease.lease_id
                self._run_lease[work.run_id] = lease.lease_id
                await self._persist_locked()
                return lease
        try:
            return await asyncio.wait_for(wait_for_claim(), timeout=wait_timeout)
        except asyncio.TimeoutError:
            return None

    async def renew(
        self, lease: WorkerLease, *, lease_duration: timedelta
    ) -> WorkerLease:
        if lease_duration.total_seconds() <= 0:
            raise ValueError("lease_duration must be positive")
        async with self._condition:
            current = self._assert_fence_locked(lease)
            now = self._clock()
            if current.expires_at <= now:
                self._expire_lease_locked(current)
                raise self._error(
                    "scheduler.lease_expired",
                    ErrorCategory.CONFLICT,
                    "worker lease has expired",
                )
            renewed = current.model_copy(update={"expires_at": now + lease_duration})
            self._leases[lease.lease_id] = renewed
            await self._persist_locked()
            return renewed

    async def release(
        self,
        lease: WorkerLease,
        reason: LeaseReleaseReason,
        *,
        requeue: bool = False,
    ) -> None:
        async with self._condition:
            self._assert_fence_locked(lease)
            self._leases.pop(lease.lease_id, None)
            self._work_lease.pop(lease.work.work_id, None)
            self._run_lease.pop(lease.work.run_id, None)
            if requeue and lease.work.work_id not in self._cancelled:
                retry = lease.work.model_copy(
                    update={"attempt": lease.work.attempt + 1}
                )
                self._items[retry.work_id] = retry
                self._push_locked(retry)
            else:
                self._items.pop(lease.work.work_id, None)
            await self._persist_locked()
            self._condition.notify_all()

    async def assert_fence(self, lease: WorkerLease) -> None:
        async with self._condition:
            reaped = self._reap_expired_locked()
            if reaped:
                await self._persist_locked()
            self._assert_fence_locked(lease)

    async def cancel(self, work_id: str) -> bool:
        async with self._condition:
            if work_id not in self._items:
                return False
            self._cancelled.add(work_id)
            lease_id = self._work_lease.pop(work_id, None)
            if lease_id is not None:
                lease = self._leases.pop(lease_id, None)
                if lease is not None:
                    self._run_lease.pop(lease.work.run_id, None)
            self._items.pop(work_id, None)
            await self._persist_locked()
            self._condition.notify_all()
            return True

    async def reap_expired(self) -> int:
        async with self._condition:
            count = self._reap_expired_locked()
            if count:
                await self._persist_locked()
                self._condition.notify_all()
            return count

    async def pending_count(self) -> int:
        async with self._condition:
            return sum(
                1
                for work_id in self._items
                if work_id not in self._work_lease and work_id not in self._cancelled
            )

    async def close(self) -> None:
        async with self._condition:
            self._closed = True
            self._condition.notify_all()

    async def _persist_locked(self) -> None:
        if self._state_store is not None:
            await self._state_store.save(self._dump_state_locked())

    def _dump_state_locked(self) -> dict[str, Any]:
        return {
            "format": "sage.scheduler-state/v1",
            "pending": [list(value) for value in self._pending],
            "items": [
                value.model_dump(mode="json") for value in self._items.values()
            ],
            "idempotency": dict(self._idempotency),
            "leases": [
                value.model_dump(mode="json") for value in self._leases.values()
            ],
            "fence_counters": dict(self._fence_counters),
            "cancelled": sorted(self._cancelled),
            "sequence": self._sequence,
        }

    def _load_state(self, state: dict[str, Any]) -> None:
        if state.get("format") != "sage.scheduler-state/v1":
            raise ValueError("unsupported Scheduler state format")
        self._pending = [tuple(value) for value in state.get("pending", ())]
        heapq.heapify(self._pending)
        self._items = {
            value.work_id: value
            for row in state.get("items", ())
            for value in (WorkItem.model_validate(row),)
        }
        self._idempotency = {
            str(key): str(value)
            for key, value in dict(state.get("idempotency") or {}).items()
        }
        self._leases = {
            value.lease_id: value
            for row in state.get("leases", ())
            for value in (WorkerLease.model_validate(row),)
        }
        self._work_lease = {
            lease.work.work_id: lease.lease_id for lease in self._leases.values()
        }
        self._run_lease = {
            lease.work.run_id: lease.lease_id for lease in self._leases.values()
        }
        self._fence_counters = {
            str(key): int(value)
            for key, value in dict(state.get("fence_counters") or {}).items()
        }
        self._cancelled = {str(value) for value in state.get("cancelled", ())}
        self._sequence = int(state.get("sequence") or 0)

    def _push_locked(self, work: WorkItem) -> None:
        self._sequence += 1
        heapq.heappush(
            self._pending,
            (
                work.available_at.timestamp(),
                -work.priority,
                self._sequence,
                work.work_id,
            ),
        )

    def _pop_available_locked(self) -> WorkItem | None:
        now_timestamp = self._clock().timestamp()
        eligible: list[tuple[float, int, int, str]] = []
        skipped: list[tuple[float, int, int, str]] = []
        while self._pending:
            entry = heapq.heappop(self._pending)
            available_at, _, _, work_id = entry
            if work_id not in self._items or work_id in self._cancelled:
                continue
            if work_id in self._work_lease:
                continue
            if available_at > now_timestamp:
                skipped.append(entry)
                break
            if self._items[work_id].run_id in self._run_lease:
                skipped.append(entry)
                continue
            eligible.append(entry)
        if not eligible:
            for entry in skipped:
                heapq.heappush(self._pending, entry)
            return None
        selected_entry = min(eligible, key=lambda value: (value[1], value[2]))
        for entry in (*skipped, *eligible):
            if entry == selected_entry:
                continue
            heapq.heappush(self._pending, entry)
        return self._items[selected_entry[3]]

    def _seconds_until_next_locked(self) -> float | None:
        candidates = [
            available_at
            for available_at, _, _, work_id in self._pending
            if work_id in self._items
            and work_id not in self._work_lease
            and work_id not in self._cancelled
            and self._items[work_id].run_id not in self._run_lease
        ]
        if not candidates:
            return None
        return max(0.0, min(candidates) - self._clock().timestamp())

    def _reap_expired_locked(self) -> int:
        now = self._clock()
        expired = [lease for lease in self._leases.values() if lease.expires_at <= now]
        for lease in expired:
            self._expire_lease_locked(lease)
        return len(expired)

    def _expire_lease_locked(self, lease: WorkerLease) -> None:
        current = self._leases.get(lease.lease_id)
        if current is None:
            return
        self._leases.pop(lease.lease_id, None)
        self._work_lease.pop(lease.work.work_id, None)
        self._run_lease.pop(lease.work.run_id, None)
        if (
            lease.work.work_id in self._items
            and lease.work.work_id not in self._cancelled
        ):
            retry = lease.work.model_copy(update={"attempt": lease.work.attempt + 1})
            self._items[retry.work_id] = retry
            self._push_locked(retry)

    def _assert_fence_locked(self, lease: WorkerLease) -> WorkerLease:
        current = self._leases.get(lease.lease_id)
        if (
            current is None
            or current.work.work_id != lease.work.work_id
            or current.work.run_id != lease.work.run_id
            or current.worker_id != lease.worker_id
            or current.fencing_token != lease.fencing_token
            or self._work_lease.get(lease.work.work_id) != lease.lease_id
        ):
            raise self._error(
                "scheduler.fence_rejected",
                ErrorCategory.CONFLICT,
                "lease is stale or no longer owns the work item",
            )
        if self._fence_counters.get(lease.work.run_id) != lease.fencing_token:
            raise self._error(
                "scheduler.fence_rejected",
                ErrorCategory.CONFLICT,
                "a newer worker fencing token exists for this run",
            )
        return current

    def _ensure_open(self) -> None:
        if self._closed:
            raise self._error(
                "scheduler.closed",
                ErrorCategory.CANCELLED,
                "scheduler is closed",
            )

    @staticmethod
    def _error(
        code: str,
        category: ErrorCategory,
        message: str,
        *,
        retryable: bool = False,
    ) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=message,
                retryable=retryable,
                safe_to_resume=True,
            )
        )


class SchedulerStateStore(Protocol):
    def load(self) -> dict[str, Any] | None: ...

    async def save(self, state: dict[str, Any]) -> None: ...
