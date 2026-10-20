"""Distributed Scheduler contracts using two independent Redis clients.

Existing scheduler matrices cover one provider instance and local quota groups.
These cases establish shared admission, claims, quotas, expiry, and lifecycle
semantics across instances without requiring a live Redis deployment.
"""

import asyncio
from datetime import timedelta

import fakeredis
import fakeredis.aioredis
import pytest
import pytest_asyncio

from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.execution.scheduler.contracts import LeaseReleaseReason, WorkItem
from sagents.v2.runtime.execution.scheduler.plugins.redis_distributed import RedisDistributedScheduler


def work(name, *, run_id=None, tenant="tenant-a", available_at=None, key=None):
    return WorkItem(
        work_id=f"work-{name}", run_id=run_id or f"run-{name}",
        tenant_id=tenant, available_at=available_at or utc_now(),
        idempotency_key=key or f"key-{name}",
    )


@pytest_asyncio.fixture
async def scheduler_pair():
    server = fakeredis.FakeServer()
    pairs = []

    def create(*, queue_ids=("default", "default"), **options):
        pair = []
        for queue_id in queue_ids:
            value = RedisDistributedScheduler(
                redis_url="redis://unused/0", key_prefix=f"scheduler-test-{len(pairs)}",
                queue_id=queue_id, **options)
            value._redis = fakeredis.aioredis.FakeRedis(server=server, decode_responses=True)
            pair.append(value)
        pairs.append(pair)
        return tuple(pair)

    yield create
    for pair in pairs:
        for value in pair:
            await value.close()


async def claim(scheduler, worker="worker", *, duration=30, wait=0):
    return await scheduler.claim(
        worker, lease_duration=timedelta(seconds=duration), wait_timeout=wait)


@pytest.mark.asyncio
async def test_submit_and_claim_are_shared_and_idempotent_between_instances(scheduler_pair):
    first, second = scheduler_pair()
    item = work("one")
    assert sorted(await asyncio.gather(first.submit(item), second.submit(item))) == [False, True]
    leases = await asyncio.gather(claim(first, "worker-a"), claim(second, "worker-b"))
    assert sum(value is not None for value in leases) == 1
    lease = next(value for value in leases if value is not None)
    assert lease.work == item
    await second.assert_fence(lease)
    await second.release(lease, LeaseReleaseReason.COMPLETED)
    assert await claim(first) is None


@pytest.mark.asyncio
async def test_distinct_work_for_one_run_cannot_have_two_live_leases(scheduler_pair):
    first, second = scheduler_pair()
    await first.submit(work("one", run_id="shared-run"))
    await second.submit(work("two", run_id="shared-run"))
    leases = await asyncio.gather(claim(first, "worker-a"), claim(second, "worker-b"))
    assert sum(value is not None for value in leases) == 1
    active = next(value for value in leases if value is not None)
    await second.release(active, LeaseReleaseReason.COMPLETED)
    following = await claim(first)
    assert following is not None
    assert following.work.run_id == active.work.run_id
    assert following.work.work_id != active.work.work_id


@pytest.mark.asyncio
async def test_expired_lease_is_reclaimed_with_higher_fence_and_rejects_old_owner(scheduler_pair):
    first, second = scheduler_pair()
    await first.submit(work("expiry"))
    old = await claim(first, "old-worker", duration=0.08)
    assert old is not None
    replacement = await asyncio.wait_for(claim(second, "new-worker", wait=1), 2)
    assert replacement is not None
    assert replacement.work.work_id == old.work.work_id
    assert replacement.work.attempt == old.work.attempt + 1
    assert replacement.fencing_token > old.fencing_token
    for operation in (
        lambda: first.assert_fence(old),
        lambda: first.renew(old, lease_duration=timedelta(seconds=30)),
        lambda: first.release(old, LeaseReleaseReason.COMPLETED),
    ):
        with pytest.raises(SageV2Error):
            await operation()
    await second.assert_fence(replacement)
    assert await claim(first) is None


@pytest.mark.asyncio
async def test_global_and_tenant_limits_apply_across_instances(scheduler_pair):
    first, second = scheduler_pair(max_concurrent_runs=2, max_concurrent_runs_per_tenant=1)
    await first.submit(work("a-one"))
    await second.submit(work("a-two"))
    await first.submit(work("b-one", tenant="tenant-b"))
    a_lease = await claim(first)
    b_lease = await claim(second)
    assert a_lease is not None and a_lease.work.tenant_id == "tenant-a"
    assert b_lease is not None and b_lease.work.tenant_id == "tenant-b"
    assert await claim(first) is None
    await second.release(a_lease, LeaseReleaseReason.COMPLETED)
    following = await claim(second)
    assert following is not None and following.work.work_id == "work-a-two"


@pytest.mark.asyncio
async def test_queue_backpressure_is_shared_and_rejection_does_not_enqueue(scheduler_pair):
    first, second = scheduler_pair(max_pending_items=1)
    item = work("one")
    assert await first.submit(item)
    assert not await second.submit(item)
    with pytest.raises(SageV2Error) as full:
        await second.submit(work("overflow"))
    assert full.value.info.code == "scheduler.queue_full"
    active = await claim(second)
    assert active is not None and active.work == item
    await first.release(active, LeaseReleaseReason.COMPLETED)
    assert await claim(second) is None


@pytest.mark.asyncio
async def test_release_requeues_with_delay_and_cancel_is_visible_to_other_instances(scheduler_pair):
    first, second = scheduler_pair()
    item = work("retry")
    await first.submit(item)
    original = await claim(second)
    assert original is not None
    await first.release(
        original, LeaseReleaseReason.DEFERRED, requeue=True,
        available_at=utc_now() + timedelta(seconds=0.08))
    assert await claim(second) is None
    retry = await asyncio.wait_for(claim(first, wait=1), 2)
    assert retry is not None and retry.work.work_id == item.work_id
    assert retry.fencing_token > original.fencing_token
    await second.release(retry, LeaseReleaseReason.COMPLETED)
    cancelled = work("cancelled", available_at=utc_now() + timedelta(seconds=10))
    await first.submit(cancelled)
    assert await second.cancel(cancelled.work_id)
    assert not await first.reschedule_pending(cancelled.work_id, utc_now())
    assert await claim(first) is None


@pytest.mark.asyncio
async def test_closing_a_node_preserves_pending_shared_work(scheduler_pair):
    first, second = scheduler_pair()
    item = work("survivor")
    await first.submit(item)
    await first.close()
    lease = await claim(second)
    assert lease is not None and lease.work == item
    await second.release(lease, LeaseReleaseReason.COMPLETED)


@pytest.mark.asyncio
async def test_fenced_callback_keeps_expired_lease_authoritative_until_callback_finishes(scheduler_pair):
    first, second = scheduler_pair()
    await first.submit(work("pinned"))
    old = await claim(first, "old-worker", duration=0.08)
    assert old is not None
    entered, finish = asyncio.Event(), asyncio.Event()

    async def operation():
        entered.set()
        await finish.wait()
        return "committed"

    task = asyncio.create_task(first.execute_fenced(old, operation))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert await claim(second, "competing-worker", wait=0.16) is None
        assert utc_now() > old.expires_at
        finish.set()
        assert await asyncio.wait_for(task, 1) == "committed"
        replacement = await asyncio.wait_for(claim(second, "replacement", wait=1), 2)
        assert replacement is not None
        assert replacement.work.run_id == old.work.run_id
        assert replacement.fencing_token > old.fencing_token
        with pytest.raises(SageV2Error):
            await first.assert_fence(old)
    finally:
        finish.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_distinct_queues_only_claim_their_work_but_share_concurrency_limits(scheduler_pair):
    first, second = scheduler_pair(queue_ids=("queue-a", "queue-b"),
                                   max_concurrent_runs=1, max_concurrent_runs_per_tenant=1)
    await first.submit(work("a", tenant="tenant-a"))
    await second.submit(work("b", tenant="tenant-b"))
    b_lease = await claim(second)
    assert b_lease is not None and b_lease.work.work_id == "work-b"
    assert await claim(first) is None
    await second.release(b_lease, LeaseReleaseReason.COMPLETED)
    assert await claim(second) is None
    a_lease = await claim(first)
    assert a_lease is not None and a_lease.work.work_id == "work-a"


@pytest.mark.asyncio
async def test_tenant_capacity_is_shared_between_distinct_queues(scheduler_pair):
    first, second = scheduler_pair(queue_ids=("queue-a", "queue-b"),
                                   max_concurrent_runs=2, max_concurrent_runs_per_tenant=1)
    await first.submit(work("a"))
    await second.submit(work("b"))
    a_lease = await claim(first)
    assert a_lease is not None
    assert await claim(second) is None
    await first.release(a_lease, LeaseReleaseReason.COMPLETED)
    b_lease = await claim(second)
    assert b_lease is not None and b_lease.work.work_id == "work-b"
