import asyncio
from datetime import timedelta

import pytest

from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.execution.scheduler.contracts import (
    WorkItem,
    LeaseReleaseReason,
)
from sagents.v2.runtime.execution.scheduler.plugins.ephemeral import (
    InMemoryScheduler,
    SchedulerQuotaGroup,
)


def work(name, tenant="a"):
    return WorkItem(
        work_id=name,
        run_id=name,
        tenant_id=tenant,
        available_at=utc_now(),
        idempotency_key=name,
    )


@pytest.mark.asyncio
async def test_shared_scheduler_limits_and_routing():
    group = SchedulerQuotaGroup(max_active=2, max_per_tenant=1, max_pending=2)
    a, b = [InMemoryScheduler(quota_group=group) for _ in range(2)]
    try:
        await a.submit(work("a"))
        first = await a.claim(
            "worker", lease_duration=timedelta(seconds=10), wait_timeout=0
        )
        await b.submit(work("b"))
        assert (
            await b.claim(
                "worker", lease_duration=timedelta(seconds=10), wait_timeout=0
            )
            is None
        )
        await b.submit(work("c", "other"))
        with pytest.raises(SageV2Error, match="queue is full"):
            await a.submit(work("overflow"))
        second = await b.claim(
            "worker", lease_duration=timedelta(seconds=10), wait_timeout=0
        )
        assert second.work.run_id == "c"
        waiter = asyncio.create_task(
            b.claim("worker", lease_duration=timedelta(seconds=10), wait_timeout=1)
        )
        await asyncio.sleep(0.01)
        assert not waiter.done()
        await a.release(first, reason=LeaseReleaseReason.COMPLETED)
        third = await waiter
        assert third.work.run_id == "b"
        assert len(group.leases()) == 2
        await b.release(second, reason=LeaseReleaseReason.COMPLETED)
        await b.release(third, reason=LeaseReleaseReason.COMPLETED)
        assert not group.leases()
    finally:
        await a.close()
        await b.close()


@pytest.mark.asyncio
async def test_cancelled_waiter_and_closed_member_do_not_consume_group_capacity():
    group = SchedulerQuotaGroup(max_active=1, max_per_tenant=1, max_pending=2)
    a, b = [InMemoryScheduler(quota_group=group) for _ in range(2)]
    try:
        await a.submit(work("a"))
        lease = await a.claim(
            "worker", lease_duration=timedelta(seconds=10), wait_timeout=0
        )
        await b.submit(work("b"))
        waiter = asyncio.create_task(
            b.claim("worker", lease_duration=timedelta(seconds=10))
        )
        await asyncio.sleep(0.01)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        await a.release(lease, reason=LeaseReleaseReason.COMPLETED)
        await a.close()
        claimed = await b.claim(
            "worker", lease_duration=timedelta(seconds=10), wait_timeout=0
        )
        assert claimed.work.run_id == "b"
        await b.release(claimed, reason=LeaseReleaseReason.COMPLETED)
    finally:
        await a.close()
        await b.close()
