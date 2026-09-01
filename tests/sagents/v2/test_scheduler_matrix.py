from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.runtime.execution.scheduler.contracts import (
    LeaseReleaseReason,
    SchedulerClaimPolicy,
    WorkItem,
)
from sagents.v2.runtime.execution.scheduler import (
    FilesystemScheduler,
    InMemoryScheduler,
    SchedulerInUseError,
)
from sagents.v2.contracts.errors import SageV2Error


class MutableClock:
    def __init__(self):
        self.now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds: float):
        self.now += timedelta(seconds=seconds)


def work(
    name: str,
    clock: MutableClock,
    *,
    run_id: str | None = None,
    priority: int = 0,
    delay: float = 0,
    key: str | None = None,
    tenant_id: str | None = None,
):
    return WorkItem(
        work_id=f"work_{name}",
        run_id=run_id or f"run_{name}",
        priority=priority,
        available_at=clock.now + timedelta(seconds=delay),
        idempotency_key=key or f"key_{name}",
        tenant_id=tenant_id,
    )


@pytest.mark.asyncio
async def test_capability_contract_explicitly_marks_in_memory_durability():
    scheduler = InMemoryScheduler()
    capabilities = await scheduler.capabilities()
    assert capabilities.api_version == "2"
    assert capabilities.durable_across_process_restart is False
    assert capabilities.supports_leases is True
    assert capabilities.supports_fencing is True
    assert capabilities.supports_atomic_fenced_mutations is True
    assert capabilities.supports_atomic_tenant_quota is True


@pytest.mark.asyncio
async def test_atomic_tenant_quota_skips_saturated_tenant_without_blocking_others():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    policy = SchedulerClaimPolicy(max_active_per_tenant=1)
    await scheduler.submit(work("a-first", clock, tenant_id="tenant-a"))
    await scheduler.submit(work("a-second", clock, tenant_id="tenant-a"))
    await scheduler.submit(work("b-first", clock, tenant_id="tenant-b"))

    first = await scheduler.claim(
        "worker-1",
        lease_duration=timedelta(seconds=30),
        policy=policy,
        wait_timeout=0,
    )
    second = await scheduler.claim(
        "worker-2",
        lease_duration=timedelta(seconds=30),
        policy=policy,
        wait_timeout=0,
    )

    assert first is not None and first.work.work_id == "work_a-first"
    assert second is not None and second.work.work_id == "work_b-first"
    await scheduler.release(first, LeaseReleaseReason.COMPLETED)
    third = await scheduler.claim(
        "worker-3",
        lease_duration=timedelta(seconds=30),
        policy=policy,
        wait_timeout=0,
    )
    assert third is not None and third.work.work_id == "work_a-second"


@pytest.mark.asyncio
async def test_submit_idempotency_and_bounded_backpressure():
    clock = MutableClock()
    scheduler = InMemoryScheduler(max_pending_items=1, clock=clock)
    first = work("1", clock)
    assert await scheduler.submit(first) is True
    assert await scheduler.submit(first) is False
    with pytest.raises(SageV2Error) as full:
        await scheduler.submit(work("2", clock))
    assert full.value.info.code == "scheduler.queue_full"
    assert full.value.info.retryable is True


@pytest.mark.asyncio
async def test_same_work_id_with_different_key_is_conflict():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    await scheduler.submit(work("1", clock, key="first"))
    with pytest.raises(SageV2Error) as conflict:
        await scheduler.submit(work("1", clock, key="second"))
    assert conflict.value.info.code == "scheduler.work_id_conflict"


@pytest.mark.asyncio
async def test_terminal_scheduler_metadata_is_bounded_without_per_run_fence_growth():
    clock = MutableClock()
    scheduler = InMemoryScheduler(
        clock=clock,
        max_retained_terminal_items=4,
    )

    for index in range(10):
        await scheduler.submit(work(str(index), clock))
        lease = await scheduler.claim(
            "worker", lease_duration=timedelta(seconds=30), wait_timeout=0
        )
        assert lease is not None
        await scheduler.release(lease, LeaseReleaseReason.COMPLETED)

    assert await scheduler.pending_count() == 0
    assert len(scheduler._idempotency) == 4
    assert len(scheduler._terminal_idempotency_keys) == 4
    assert scheduler._fence_sequence == 10


@pytest.mark.asyncio
async def test_cancelled_delayed_work_does_not_leave_an_unbounded_heap():
    clock = MutableClock()
    scheduler = InMemoryScheduler(
        clock=clock,
        max_retained_terminal_items=2,
    )

    for index in range(10):
        item = work(str(index), clock, delay=60)
        await scheduler.submit(item)
        assert await scheduler.cancel(item.work_id) is True

    assert scheduler._pending == []
    assert len(scheduler._idempotency) == 2
    assert len(scheduler._cancelled) == 2


@pytest.mark.asyncio
async def test_claim_orders_all_available_work_by_priority_then_fifo():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    await scheduler.submit(work("low_old", clock, priority=-1))
    clock.advance(1)
    await scheduler.submit(work("high_first", clock, priority=10))
    await scheduler.submit(work("high_second", clock, priority=10))

    leases = [
        await scheduler.claim(
            f"worker_{index}", lease_duration=timedelta(seconds=30), wait_timeout=0
        )
        for index in range(3)
    ]
    assert [lease.work.work_id for lease in leases] == [
        "work_high_first",
        "work_high_second",
        "work_low_old",
    ]


@pytest.mark.asyncio
async def test_delayed_work_not_claimed_before_available_time():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    await scheduler.submit(work("later", clock, delay=10))
    assert (
        await scheduler.claim(
            "worker", lease_duration=timedelta(seconds=30), wait_timeout=0
        )
        is None
    )
    clock.advance(10)
    lease = await scheduler.claim(
        "worker", lease_duration=timedelta(seconds=30), wait_timeout=0
    )
    assert lease is not None and lease.work.work_id == "work_later"


@pytest.mark.asyncio
async def test_concurrent_workers_claim_each_work_item_exactly_once():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    for index in range(20):
        await scheduler.submit(work(str(index), clock))

    leases = await asyncio.gather(
        *(
            scheduler.claim(
                f"worker_{index}",
                lease_duration=timedelta(seconds=30),
                wait_timeout=0,
            )
            for index in range(20)
        )
    )
    work_ids = [lease.work.work_id for lease in leases]
    assert len(work_ids) == len(set(work_ids)) == 20


@pytest.mark.asyncio
async def test_same_run_never_has_two_live_leases():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    await scheduler.submit(work("1", clock, run_id="run_same"))
    await scheduler.submit(work("2", clock, run_id="run_same"))
    first = await scheduler.claim(
        "worker_1", lease_duration=timedelta(seconds=30), wait_timeout=0
    )
    assert first is not None
    assert (
        await scheduler.claim(
            "worker_2", lease_duration=timedelta(seconds=30), wait_timeout=0
        )
        is None
    )
    await scheduler.release(first, LeaseReleaseReason.COMPLETED)
    second = await scheduler.claim(
        "worker_2", lease_duration=timedelta(seconds=30), wait_timeout=0
    )
    assert second is not None and second.work.work_id == "work_2"


@pytest.mark.asyncio
async def test_expired_lease_requeues_with_new_attempt_and_fencing_token():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    await scheduler.submit(work("1", clock))
    old = await scheduler.claim(
        "worker_old", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    clock.advance(6)
    assert await scheduler.reap_expired() == 1
    new = await scheduler.claim(
        "worker_new", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    assert new.work.attempt == 2
    assert new.fencing_token == old.fencing_token + 1
    with pytest.raises(SageV2Error) as stale:
        await scheduler.assert_fence(old)
    assert stale.value.info.code == "scheduler.fence_rejected"
    await scheduler.assert_fence(new)


@pytest.mark.asyncio
async def test_renew_release_requeue_and_cancel_matrix():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    await scheduler.submit(work("1", clock))
    lease = await scheduler.claim(
        "worker", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    clock.advance(2)
    renewed = await scheduler.renew(lease, lease_duration=timedelta(seconds=10))
    assert renewed.expires_at == clock.now + timedelta(seconds=10)
    await scheduler.release(renewed, LeaseReleaseReason.WORKER_SHUTDOWN, requeue=True)
    retried = await scheduler.claim(
        "worker_2", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    assert retried.work.attempt == 2
    assert await scheduler.cancel(retried.work.work_id) is True
    with pytest.raises(SageV2Error):
        await scheduler.assert_fence(retried)
    assert await scheduler.cancel(retried.work.work_id) is False


@pytest.mark.asyncio
async def test_close_wakes_waiting_claimers_with_typed_error():
    scheduler = InMemoryScheduler()
    waiting = asyncio.create_task(
        scheduler.claim("worker", lease_duration=timedelta(seconds=5))
    )
    await asyncio.sleep(0)
    await scheduler.close()
    with pytest.raises(SageV2Error) as closed:
        await waiting
    assert closed.value.info.code == "scheduler.closed"


@pytest.mark.asyncio
async def test_filesystem_scheduler_restores_pending_work(tmp_path):
    clock = MutableClock()
    first = FilesystemScheduler(tmp_path, clock=clock)
    item = work("durable", clock)
    assert await first.submit(item) is True
    await first.close()

    restored = FilesystemScheduler(tmp_path, clock=clock)
    capabilities = await restored.capabilities()
    lease = await restored.claim(
        "worker_restored",
        lease_duration=timedelta(seconds=30),
        wait_timeout=0,
    )

    assert capabilities.durable_across_process_restart is True
    assert lease is not None and lease.work == item
    await restored.close()


@pytest.mark.asyncio
async def test_filesystem_scheduler_enforces_one_writer_per_root(tmp_path):
    first = FilesystemScheduler(tmp_path)
    with pytest.raises(SchedulerInUseError) as caught:
        FilesystemScheduler(tmp_path)
    assert caught.value.info.code == "scheduler.in_use"

    await first.close()
    replacement = FilesystemScheduler(tmp_path)
    await replacement.close()


@pytest.mark.asyncio
async def test_filesystem_scheduler_restores_lease_and_monotonic_fence(tmp_path):
    clock = MutableClock()
    first = FilesystemScheduler(tmp_path, clock=clock)
    await first.submit(work("leased", clock))
    old = await first.claim(
        "worker_old", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    await first.close()

    restored = FilesystemScheduler(tmp_path, clock=clock)
    assert (
        await restored.claim(
            "worker_early", lease_duration=timedelta(seconds=5), wait_timeout=0
        )
        is None
    )
    clock.advance(6)
    assert await restored.reap_expired() == 1
    new = await restored.claim(
        "worker_new", lease_duration=timedelta(seconds=5), wait_timeout=0
    )

    assert new is not None
    assert new.work.attempt == 2
    assert new.fencing_token == old.fencing_token + 1
    await restored.close()
