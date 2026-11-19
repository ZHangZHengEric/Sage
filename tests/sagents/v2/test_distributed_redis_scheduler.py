"""Distributed Scheduler contracts using two independent Redis clients.

Existing scheduler matrices cover one provider instance and local quota groups.
These cases establish shared admission, claims, quotas, expiry, and lifecycle
semantics across instances without requiring a live Redis deployment.
"""

from typing import cast

import asyncio
from datetime import timedelta
import json
from unittest.mock import patch

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

    def create(*, queue_ids=("default", "default"), release_ids=None, **options):
        pair = []
        for queue_id, release_id in zip(queue_ids, release_ids or (None,) * len(queue_ids), strict=True):
            value = RedisDistributedScheduler(
                redis_url="redis://unused/0", key_prefix=f"scheduler-test-{len(pairs)}",
                queue_id=queue_id, release_id=release_id, **options)
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
async def test_release_handoff_allows_active_replicas_and_preserves_inflight_lease(scheduler_pair):
    old, first, second = scheduler_pair(queue_ids=("server",) * 3,
                                        release_ids=("blue", "green", "green"))
    key = old.active_release_key(old.key_prefix)
    await old.submit(work("inflight"))
    assert await claim(old) is None
    await old._redis.set(key, "blue")
    lease = await claim(old, "old")
    await old.submit(work("queued"))
    assert await claim(first) is None
    await old._redis.set(key, "green")
    assert await claim(old) is None
    renewed = await old.renew(lease, lease_duration=timedelta(seconds=60))
    assert renewed.expires_at > lease.expires_at
    await old.release(renewed, LeaseReleaseReason.COMPLETED)

    leases = await asyncio.gather(claim(first, "green-a"), claim(second, "green-b"))
    assert [row.work.work_id for row in leases if row] == ["work-queued"]
    await first.submit(work("another"))
    idle_replica = second if leases[0] else first
    assert (await claim(idle_replica)).work.work_id == "work-another"


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", (False, True))
async def test_handoff_rejects_claim_that_was_already_in_progress(scheduler_pair, fallback):
    old, new = scheduler_pair(queue_ids=("managed_agent",) * 2, release_ids=("old", "new"))
    key = old.active_release_key(old.key_prefix)
    await old._redis.set(key, "old")
    item = work("racing")
    await old.submit(item)
    watch = old._watch_claim

    async def switch_after_check(pipe, state_key):
        eligible = await watch(pipe, state_key)
        if eligible:
            await new._redis.set(key, "new")
        return eligible

    with patch.object(old, "_watch_claim", side_effect=switch_after_check) as watched:
        if fallback:
            with patch.object(old, "_try_claim", return_value=NotImplemented):
                assert await claim(old) is None
        else:
            assert await claim(old) is None
    assert watched.await_count >= 1
    assert (await claim(new)).work == item


@pytest.mark.asyncio
async def test_indexed_claim_reads_only_due_work_and_repairs_legacy_state(scheduler_pair):
    first, second = scheduler_pair()
    for i in range(12):
        assert await first.submit(work(f"later-{i}", available_at=utc_now() + timedelta(hours=1)))
    with patch.object(second, "_mutate", side_effect=AssertionError("full queue read during idle poll")):
        assert await claim(second) is None

    ready = work("ready")
    assert await first.submit(ready)
    state_key = first.key_prefix + ":state"
    base = await first._redis.get(state_key)
    with (
        patch.object(second, "_reference", wraps=second._reference) as reference,
        patch.object(second, "_mutate", side_effect=AssertionError("full snapshot used for ready claim")),
    ):
        lease = await claim(second)
    assert lease is not None and lease.work == ready
    snapshot = reference.call_args.args[1]
    assert [item["work_id"] for item in snapshot["items"]] == [ready.work_id]
    stored = json.loads(await first._redis.get(state_key))
    assert stored["leases"][0]["lease_id"] == lease.lease_id
    assert stored["items"] == json.loads(base)["items"]
    assert len(await first.existing_work_ids()) == 13

    # Reopen the previous journal format with its in-flight lease. After
    # initialization even a plain JSON reader must observe the same fence.
    await first._redis.set(state_key, base + "\x1e" + json.dumps({"lease": stored["leases"][0]}))
    await first._mutate(lambda queue: queue.pending_count())
    restored = json.loads(await first._redis.get(state_key))
    assert restored["leases"] == stored["leases"]
    await second.assert_fence(lease)
    assert await claim(second) is None
    await first.release(lease, LeaseReleaseReason.COMPLETED)
    ready = work("legacy")
    assert await first.submit(ready)
    key = first.key_prefix + ":state"
    legacy = json.loads(await first._redis.get(key))
    legacy.pop("claim_epoch")
    await first._redis.set(key, json.dumps(legacy))
    await first._redis.delete(first._claim_due_key("default"))
    lease = await claim(second)
    assert lease is not None and lease.work == ready
    assert await first._redis.zcard(first._claim_due_key("default")) == 12


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
    old = await claim(first, "old-worker", duration=cast('int', 0.08))
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
    old = await claim(first, "old-worker", duration=cast('int', 0.08))
    assert old is not None
    entered, finish = asyncio.Event(), asyncio.Event()

    async def operation():
        entered.set()
        await finish.wait()
        return "committed"

    task = asyncio.create_task(first.execute_fenced(old, operation))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert await claim(second, "competing-worker", wait=cast('int', 0.16)) is None
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


@pytest.mark.asyncio
async def test_restore_queued_reopens_retired_receipt_atomically_and_respects_leases(scheduler_pair):
    first, second = scheduler_pair()
    item = work("orphan")
    assert await first.submit(item)
    lease = await claim(first)
    assert lease is not None
    assert not await second.restore_queued(item)
    assert not await second.restore_queued(work("another-item", run_id=item.run_id))
    await first.release(lease, LeaseReleaseReason.CANCELLED)
    assert not await first.submit(item)
    assert sorted(await asyncio.gather(first.restore_queued(item), second.restore_queued(item))) == [False, True]
    active = await claim(second)
    assert active is not None and active.fencing_token > lease.fencing_token
    assert await claim(first) is None
    await second.release(active, LeaseReleaseReason.COMPLETED)

    cancelled = work("cancelled")
    assert await first.submit(cancelled)
    assert await first.cancel(cancelled.work_id)
    assert not await second.restore_queued(cancelled)


@pytest.mark.asyncio
@pytest.mark.parametrize("retention", [0, 2])
async def test_incremental_lease_updates_preserve_v1_arrays_and_receipts(scheduler_pair, retention):
    owner, peer = scheduler_pair(max_retained_terminal_items=retention)
    items = [work(str(i), tenant=str(i)) for i in range(5)]
    for item in items:
        await owner.submit(item)
    leases = [await claim(owner) for _ in items]
    with patch.object(peer, "_mutate", side_effect=AssertionError("full registry read")):
        for index in (2, 0, 1, 4, 3):
            lease = await peer.renew(leases[index], lease_duration=timedelta(seconds=60))
            await peer.release(lease, LeaseReleaseReason.DEFERRED, requeue=True)
            retry = await claim(peer)
            assert retry.work.attempt == lease.work.attempt + 1
            await peer.release(retry, LeaseReleaseReason.COMPLETED)
            raw = json.loads(await owner._redis.get(owner.key_prefix + ":state"))
            assert retry.work.work_id not in {row["work_id"] for row in raw["items"]}
            assert len(raw["terminal_idempotency_keys"]) <= retention
    assert set(raw["idempotency"]) == set(raw["terminal_idempotency_keys"])


@pytest.mark.asyncio
async def test_claim_fallback_uses_one_canonical_value_after_legacy_rewrite(scheduler_pair):
    producer, reader = scheduler_pair()
    item = work("legacy-rewrite")
    await producer.submit(item)
    key = producer.key_prefix + ":state"

    async def legacy_write(_operation):
        state = json.loads(await producer._redis.get(key))
        state.pop("claim_epoch")
        await producer._redis.set(key, json.dumps(state))
        return NotImplemented

    with (
        patch.object(reader, "_try_claim", side_effect=legacy_write),
        patch.object(reader, "_indexed_claim", side_effect=AssertionError("retried stale byte ranges")),
    ):
        lease = await claim(reader)
    assert lease.work == item
    await producer.assert_fence(lease)
    assert await claim(producer) is None
    await reader.release(lease, LeaseReleaseReason.COMPLETED)


@pytest.mark.asyncio
async def test_existing_ids_follow_cancellation_release_and_legacy_overwrite(scheduler_pair):
    first, reader = scheduler_pair()
    ready, cancelled = work("ready"), work("cancelled")
    await first.submit(ready)
    await first.submit(cancelled)
    await first.cancel(cancelled.work_id)
    key = first.key_prefix + ":state"
    with patch.object(reader._redis, "get", side_effect=AssertionError("full queue read")):
        assert await reader.existing_work_ids() == {ready.work_id, cancelled.work_id}
        lease = await claim(first)
        assert lease and lease.work == ready
        assert await reader.existing_work_ids() == {ready.work_id, cancelled.work_id}
        await first.release(lease, LeaseReleaseReason.COMPLETED)
        assert await reader.existing_work_ids() == {cancelled.work_id}

    # A pre-index writer replaces the document and leaves the old index behind.
    legacy = json.loads(await first._redis.get(key))
    legacy.pop("claim_epoch")
    legacy["cancelled"] = ["legacy-id"]
    await first._redis.set(key, json.dumps(legacy))
    assert await reader.existing_work_ids() == {"legacy-id"}
