from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.execution.scheduler.contracts import WorkerLease

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
    assert [cast('WorkerLease', lease).work.work_id for lease in leases] == [
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
    work_ids = [cast('WorkerLease', lease).work.work_id for lease in leases]
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
    assert cast('WorkerLease', new).work.attempt == 2
    assert cast('WorkerLease', new).fencing_token == cast('WorkerLease', old).fencing_token + 1
    with pytest.raises(SageV2Error) as stale:
        await scheduler.assert_fence(cast('WorkerLease', old))
    assert stale.value.info.code == "scheduler.fence_rejected"
    await scheduler.assert_fence(cast('WorkerLease', new))


@pytest.mark.asyncio
async def test_renew_release_requeue_and_cancel_matrix():
    clock = MutableClock()
    scheduler = InMemoryScheduler(clock=clock)
    await scheduler.submit(work("1", clock))
    lease = await scheduler.claim(
        "worker", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    clock.advance(2)
    renewed = await scheduler.renew(cast('WorkerLease', lease), lease_duration=timedelta(seconds=10))
    assert renewed.expires_at == clock.now + timedelta(seconds=10)
    await scheduler.release(renewed, LeaseReleaseReason.WORKER_SHUTDOWN, requeue=True)
    retried = await scheduler.claim(
        "worker_2", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    assert cast('WorkerLease', retried).work.attempt == 2
    assert await scheduler.cancel(cast('WorkerLease', retried).work.work_id) is True
    with pytest.raises(SageV2Error):
        await scheduler.assert_fence(cast('WorkerLease', retried))
    assert await scheduler.cancel(cast('WorkerLease', retried).work.work_id) is False


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
async def test_filesystem_scheduler_poisoned_after_persistence_failure(tmp_path):
    clock = MutableClock()
    scheduler = FilesystemScheduler(tmp_path, clock=clock)

    async def fail_save(state):
        del state
        raise OSError("disk unavailable")

    setattr(scheduler._state_store, "save", fail_save)

    with pytest.raises(SageV2Error) as failed:
        await scheduler.submit(work("uncertain", clock))
    assert failed.value.info.code == "scheduler.persistence_failed"
    assert failed.value.info.safe_to_resume is False

    with pytest.raises(SageV2Error) as poisoned:
        await scheduler.submit(work("second", clock))
    assert poisoned.value.info.code == "scheduler.closed"
    await scheduler.close()


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
    # The exclusive single-host writer lock proves the old owner has exited.
    # Reclaim immediately rather than waiting for its (potentially 48h) TTL.
    new = await restored.claim(
        "worker_new", lease_duration=timedelta(seconds=5), wait_timeout=0
    )

    assert new is not None
    assert new.work.attempt == 2
    assert new.fencing_token == cast('WorkerLease', old).fencing_token + 1
    await restored.close()


@pytest.mark.asyncio
async def test_filesystem_journal_migrates_legacy_and_recovers_torn_tail(tmp_path):
    import json
    from sagents.v2.runtime.execution.scheduler.plugins.filesystem import FilesystemSchedulerStateStore

    clock = MutableClock()
    scheduler = FilesystemScheduler(tmp_path, clock=clock)
    item = work("legacy", clock)
    await scheduler.submit(item)
    state = scheduler._dump_state_locked()
    await scheduler.close()
    storage = FilesystemSchedulerStateStore(tmp_path)
    storage.path.write_text(json.dumps({
        "format": storage.format, "state": state, "checksum": storage._checksum(state),
    }))

    scheduler = FilesystemScheduler(tmp_path, clock=clock)
    lease = await scheduler.claim("first", lease_duration=timedelta(hours=1), wait_timeout=0)
    assert lease and lease.work == item
    await scheduler.release(lease, LeaseReleaseReason.COMPLETED)
    await scheduler.close()
    committed = storage.path.read_bytes()
    with storage.path.open("ab") as handle:
        handle.write(b'{"interrupted":')
    scheduler = FilesystemScheduler(tmp_path, clock=clock)
    assert not await scheduler.submit(item)
    assert await scheduler.claim("next", lease_duration=timedelta(hours=1), wait_timeout=0) is None
    assert await scheduler.submit(work("next", clock))
    await scheduler.close()
    saved = storage.path.read_bytes()
    assert saved.startswith(committed)
    assert len(storage.load()["items"]) == 1
    # A complete corrupt record must never be mistaken for an incomplete append.
    storage.path.write_bytes(saved.replace(b'work_next', b'work_bork'))
    with pytest.raises(ValueError, match="checksum"):
        FilesystemScheduler(tmp_path, clock=clock)


@pytest.mark.asyncio
async def test_journal_survives_owner_process_exit_with_completed_and_abandoned_work(tmp_path):
    import subprocess
    import sys
    import textwrap

    result = await asyncio.to_thread(subprocess.run, [
        sys.executable, "-c", textwrap.dedent("""
            import asyncio, os, sys
            from datetime import timedelta
            from sagents.v2.runtime.execution.scheduler import FilesystemScheduler, LeaseReleaseReason
            from tests.sagents.v2.test_scheduler_matrix import MutableClock, work
            async def run():
                clock = MutableClock()
                scheduler = FilesystemScheduler(sys.argv[1], clock=clock)
                for name in ("completed", "abandoned"):
                    await scheduler.submit(work(name, clock))
                first = await scheduler.claim("old", lease_duration=timedelta(days=2), wait_timeout=0)
                await scheduler.release(first, LeaseReleaseReason.COMPLETED)
                second = await scheduler.claim("old", lease_duration=timedelta(days=2), wait_timeout=0)
                print(second.fencing_token, flush=True)
                os._exit(23)
            asyncio.run(run())
        """), str(tmp_path),
    ], capture_output=True, text=True, timeout=20)
    assert result.returncode == 23, result.stderr
    clock = MutableClock()
    scheduler = FilesystemScheduler(tmp_path, clock=clock)
    try:
        assert not await scheduler.submit(work("completed", clock))
        leases = await asyncio.gather(*(scheduler.claim(
            str(i), lease_duration=timedelta(days=2), wait_timeout=0
        ) for i in range(8)))
        lease, = [candidate for candidate in leases if candidate is not None]
        assert lease.work.work_id == "work_abandoned" and lease.work.attempt == 2
        assert lease.fencing_token > int(result.stdout)
    finally:
        await scheduler.close()


@pytest.mark.asyncio
async def test_journal_replays_reschedules_expiry_receipt_retirement_and_compaction(tmp_path):
    from sagents.v2.runtime.execution.scheduler.plugins.filesystem import FilesystemSchedulerStateStore

    clock = MutableClock()
    scheduler = FilesystemScheduler(tmp_path, clock=clock, max_retained_terminal_items=2)
    reader = FilesystemSchedulerStateStore(tmp_path)

    def check_replay():
        expected = scheduler._dump_state_locked()
        actual = reader.load()
        # Reopening re-heapifies pending entries; equal priority uses the saved sequence.
        for state in (expected, actual):
            state["pending"].sort()
            state["cancelled"].sort()
            state["items"].sort(key=lambda item: item["work_id"])
            state["leases"].sort(key=lambda lease: lease["lease_id"])
        assert actual == expected

    try:
        for i in range(5):
            await scheduler.submit(work(str(i), clock))
        await scheduler.reschedule_pending("work_0", clock.now + timedelta(days=1))
        await scheduler.cancel("work_2")
        lease = await scheduler.claim("one", lease_duration=timedelta(seconds=1), wait_timeout=0)
        renewed = await scheduler.renew(lease, lease_duration=timedelta(seconds=10))
        check_replay()
        await scheduler.release(renewed, LeaseReleaseReason.COMPLETED, requeue=True)
        lease = await scheduler.claim("two", lease_duration=timedelta(seconds=1), wait_timeout=0)
        clock.advance(2)
        assert await scheduler.reap_expired() == 1
        check_replay()
        for i in range(3):
            lease = await scheduler.claim("three", lease_duration=timedelta(days=1), wait_timeout=0)
            await scheduler.release(lease, LeaseReleaseReason.COMPLETED)
        check_replay()
        assert await scheduler.restore_queued(lease.work)
        # Cross the record-count compaction boundary with a non-empty queue.
        scheduler._state_store._records = 1024
        await scheduler.submit(work("compact", clock))
        assert scheduler._state_store._records == 0
        await scheduler.cancel("work_compact")
        check_replay()
    finally:
        await scheduler.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement_committed", [False, True])
async def test_failed_checkpoint_reopens_only_one_generation(tmp_path, monkeypatch, replacement_committed):
    import os

    clock = MutableClock()
    scheduler = FilesystemScheduler(tmp_path, clock=clock)
    done = work("done", clock)
    await scheduler.submit(done)
    lease = await scheduler.claim("first", lease_duration=timedelta(minutes=1), wait_timeout=0)
    await scheduler.release(lease, LeaseReleaseReason.COMPLETED)
    scheduler._state_store._records = 1024
    replace = os.replace

    def fail(source, target):
        if replacement_committed:
            replace(source, target)
        raise OSError("interrupted checkpoint")

    next_item = work("next", clock)
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail)
        with pytest.raises(SageV2Error) as failed:
            await scheduler.submit(next_item)
        assert failed.value.info.code == "scheduler.persistence_failed"
    await scheduler.close()
    reopened = FilesystemScheduler(tmp_path, clock=clock)
    try:
        assert not await reopened.submit(done)
        assert await reopened.submit(next_item) is not replacement_committed
        lease = await reopened.claim("new", lease_duration=timedelta(minutes=1), wait_timeout=0)
        assert lease.work == next_item
        assert await reopened.claim("other", lease_duration=timedelta(minutes=1), wait_timeout=0) is None
    finally:
        await reopened.close()
