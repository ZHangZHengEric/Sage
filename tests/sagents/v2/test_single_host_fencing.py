from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.runtime.execution.scheduler import (
    FilesystemScheduler,
    InMemoryScheduler,
    LeaseReleaseReason,
    SchedulerClaimPolicy,
    WorkItem,
)


@pytest.fixture(params=[InMemoryScheduler, FilesystemScheduler])
def scheduler(request, tmp_path):
    cls = request.param
    return cls(tmp_path) if cls is FilesystemScheduler else cls()


async def claim(scheduler, name, *, seconds=30):
    await scheduler.submit(
        WorkItem(
            work_id=name, run_id=name, available_at=utc_now(), idempotency_key=name
        )
    )
    return await scheduler.claim(
        name, lease_duration=timedelta(seconds=seconds), wait_timeout=0
    )


@pytest.mark.asyncio
async def test_unrelated_fenced_mutations_and_renewals_overlap(scheduler):
    first = await claim(scheduler, "first")
    second = await claim(scheduler, "second")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow():
        entered.set()
        await release.wait()

    task = asyncio.create_task(scheduler.execute_fenced(first, slow))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert (
            await asyncio.wait_for(
                scheduler.execute_fenced(
                    second, lambda: asyncio.sleep(0, result="done")
                ),
                2,
            )
            == "done"
        )
        await asyncio.wait_for(
            scheduler.renew(first, lease_duration=timedelta(seconds=30)), 2
        )
        third = await asyncio.wait_for(claim(scheduler, "third"), 2)
        assert third is not None
    finally:
        release.set()
        await task
        await scheduler.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["release", "cancel", "close", "same-run"])
async def test_conflicting_operations_wait_for_existing_fenced_commit(
    scheduler, action
):
    lease = await claim(scheduler, "first")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow():
        entered.set()
        await release.wait()

    task = asyncio.create_task(scheduler.execute_fenced(lease, slow))
    blocked = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        operation = {
            "release": lambda: scheduler.release(lease, LeaseReleaseReason.COMPLETED),
            "cancel": lambda: scheduler.cancel(lease.work.work_id),
            "close": scheduler.close,
            "same-run": lambda: scheduler.execute_fenced(
                lease, lambda: asyncio.sleep(0)
            ),
        }[action]
        blocked = asyncio.create_task(operation())
        await asyncio.sleep(0.02)
        assert not blocked.done()
        assert lease.work.run_id in scheduler._fenced_runs
        release.set()
        await asyncio.wait_for(asyncio.gather(task, blocked), 2)
        assert not scheduler._fenced_runs
    finally:
        release.set()
        await asyncio.gather(
            task, *([blocked] if blocked else []), return_exceptions=True
        )
        await scheduler.close()


@pytest.mark.asyncio
async def test_expired_pinned_lease_keeps_quota_and_cannot_be_reclaimed(scheduler):
    lease = await claim(scheduler, "first")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def slow():
        entered.set()
        await release.wait()

    task = asyncio.create_task(scheduler.execute_fenced(lease, slow))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        scheduler._clock = lambda: lease.expires_at + timedelta(seconds=1)
        assert await scheduler.reap_expired() == 0
        await scheduler.submit(
            WorkItem(
                work_id="next",
                run_id="next",
                available_at=utc_now(),
                idempotency_key="next",
            )
        )
        assert (
            await scheduler.claim(
                "other",
                lease_duration=timedelta(seconds=30),
                policy=SchedulerClaimPolicy(max_active_per_tenant=1),
                wait_timeout=0,
            )
            is None
        )
        # Ownership was continuously pinned; a heartbeat can still extend it.
        await scheduler.renew(lease, lease_duration=timedelta(seconds=30))
        release.set()
        await task
        scheduler._clock = lambda: lease.expires_at + timedelta(seconds=60)
        assert await scheduler.reap_expired() == 1
        with pytest.raises(SageV2Error):
            await scheduler.execute_fenced(lease, lambda: asyncio.sleep(0))
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await scheduler.close()


@pytest.mark.asyncio
async def test_waiting_claim_wakes_on_expiration_without_external_notification(
    scheduler,
):
    await claim(scheduler, "first", seconds=0.05)
    lease = await asyncio.wait_for(
        scheduler.claim("replacement", lease_duration=timedelta(seconds=30)), 2
    )
    assert lease.work.run_id == "first"
    assert lease.fencing_token > 1
    await scheduler.close()


@pytest.mark.asyncio
async def test_repeated_cancellation_during_unpin_does_not_leak_pin(scheduler):
    lease = await claim(scheduler, "first")
    entered = asyncio.Event()

    async def slow():
        entered.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(scheduler.execute_fenced(lease, slow))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        async with scheduler._condition:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert not scheduler._fenced_runs
        assert await scheduler.cancel(lease.work.work_id)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await scheduler.close()


@pytest.mark.asyncio
async def test_dispatcher_parallel_session_commits_remain_bounded_and_ordered():
    from sagents.v2.contracts.commands import StartRun, InputItem
    from sagents.v2.contracts.items import TextBlock
    from sagents.v2.runtime.session.state import SessionStoreCoordinator
    from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
    from sagents.v2.contracts.events import RunEventData
    from sagents.v2.contracts.run_state import RunState
    from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
    from sagents.v2.runtime.session import (
        EventDraft,
        LeaseFencedSessionStore,
    )

    release = asyncio.Event()
    all_slots_busy = asyncio.Event()

    class Store(SessionStoreCoordinator):
        measure = False
        active = peak = 0

        async def _commit_storage_locked(self, session_id):
            if not self.measure:
                return
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 16:
                all_slots_busy.set()
            try:
                await release.wait()
                await asyncio.sleep(0.001)
            finally:
                self.active -= 1

    store = Store(persistence_can_fail=False)
    scheduler = InMemoryScheduler()
    fenced = LeaseFencedSessionStore(store, scheduler)
    dispatcher = LocalWorkerDispatcher(
        scheduler,
        max_concurrent_runs=16,
        max_concurrent_runs_per_tenant=2,
        lease_scope_factory=fenced.lease_scope,
    )

    class Agent:
        def ensure_execution(self, run_id, context, *, resume):
            async def execute():
                revision = 0
                for before, after, event_type in (
                    (RunState.QUEUED, RunState.RUNNING, "run.started"),
                    (RunState.RUNNING, RunState.COMPLETED, "run.completed"),
                ):
                    result = await fenced.commit_run(
                        run_id=run_id,
                        expected_revision=revision,
                        expected_states={before},
                        new_state=after,
                        drafts=(
                            EventDraft(
                                type=event_type, data=RunEventData(state=after.value)
                            ),
                        ),
                        context=context,
                        idempotency_key=f"{run_id}:{event_type}",
                    )
                    revision = result.run.revision
                return result.run

            return asyncio.create_task(execute())

    runs = []
    for i in range(64):
        context = RequestContext(
            actor=ActorRef(
                principal_id=f"user-{i % 8}",
                principal_type=PrincipalType.USER,
                tenant_id=f"user-{i % 8}",
            )
        )
        created = await store.create_run(
            StartRun(
                agent_id="main",
                input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
                resolved_spec_hash="hash",
                idempotency_key=f"start-{i}",
            ),
            context,
        )
        runs.append((created.handle, context))
    store.measure = True
    results = []
    try:
        for handle, context in runs:
            results.append(await dispatcher.submit(Agent(), handle, context))
        await asyncio.wait_for(all_slots_busy.wait(), 3)
        assert store.peak == 16
        release.set()
        snapshots = await asyncio.wait_for(asyncio.gather(*results), 5)
        assert all(run.state == RunState.COMPLETED for run in snapshots)
        for run in snapshots:
            events = await store.read_session_events(run.session_id)
            assert [e.session_sequence for e in events] == list(
                range(1, len(events) + 1)
            )
        assert store.active == 0
        assert not scheduler._fenced_runs
    finally:
        release.set()
        await dispatcher.close()
        await scheduler.close()
        await asyncio.gather(*results, return_exceptions=True)
