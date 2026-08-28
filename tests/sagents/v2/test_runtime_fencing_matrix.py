from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sagents.v2.runtime.execution.scheduler import InMemoryScheduler, WorkItem
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import (
    EphemeralSessionStore,
    LeaseFencedSessionStore,
)


class Clock:
    def __init__(self):
        self.now = datetime(2026, 8, 25, tzinfo=timezone.utc)

    def __call__(self):
        return self.now


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="worker_1", principal_type=PrincipalType.WORKER)
)


async def setup():
    clock = Clock()
    scheduler = InMemoryScheduler(clock=clock)
    base = EphemeralSessionStore(clock=clock)
    fenced = LeaseFencedSessionStore(base, scheduler)
    runtime = HarnessRuntime(fenced)
    handle = await runtime.start_run(
        StartRun(
            agent_id="agent_1",
            input=(InputItem(role="user", content=(TextBlock(text="run"),)),),
            resolved_spec_hash="sha256:agent",
            idempotency_key="start",
        ),
        CONTEXT,
    )
    await scheduler.submit(
        WorkItem(
            work_id="work_1",
            run_id=handle.run_id,
            available_at=clock.now,
            idempotency_key="work_1",
        )
    )
    return clock, scheduler, fenced, runtime, handle


@pytest.mark.asyncio
async def test_executor_write_without_worker_lease_is_rejected():
    _, _, _, runtime, handle = await setup()
    with pytest.raises(SageV2Error) as caught:
        await runtime.start_execution(
            run_id=handle.run_id,
            expected_revision=handle.run_revision,
            context=CONTEXT,
            idempotency_key="execute",
        )
    assert caught.value.info.code == "scheduler.worker_lease_required"


@pytest.mark.asyncio
async def test_expired_old_worker_cannot_commit_after_new_fencing_token_exists():
    clock, scheduler, fenced, runtime, handle = await setup()
    old = await scheduler.claim(
        "old", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    scope = fenced.lease_scope(old)
    await scope.__aenter__()
    clock.now += timedelta(seconds=6)
    await scheduler.reap_expired()
    new = await scheduler.claim(
        "new", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    with pytest.raises(SageV2Error) as stale:
        await runtime.start_execution(
            run_id=handle.run_id,
            expected_revision=handle.run_revision,
            context=CONTEXT,
            idempotency_key="old_execute",
        )
    assert stale.value.info.code == "scheduler.fence_rejected"
    await scope.__aexit__(None, None, None)

    async with fenced.lease_scope(new):
        run = await runtime.start_execution(
            run_id=handle.run_id,
            expected_revision=handle.run_revision,
            context=CONTEXT,
            idempotency_key="new_execute",
        )
    assert run.state == RunState.RUNNING
    assert [event.type for event in await fenced.read_events(handle.run_id)].count(
        "run.started"
    ) == 1


@pytest.mark.asyncio
async def test_lease_for_another_run_cannot_mutate_target_run():
    clock, scheduler, fenced, runtime, handle = await setup()
    other = WorkItem(
        work_id="work_other",
        run_id="run_other",
        available_at=clock.now,
        idempotency_key="work_other",
    )
    await scheduler.submit(other)
    first = await scheduler.claim(
        "worker", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    second = await scheduler.claim(
        "worker", lease_duration=timedelta(seconds=5), wait_timeout=0
    )
    wrong = second if second.work.run_id == "run_other" else first
    async with fenced.lease_scope(wrong):
        with pytest.raises(SageV2Error) as caught:
            await runtime.start_execution(
                run_id=handle.run_id,
                expected_revision=handle.run_revision,
                context=CONTEXT,
                idempotency_key="wrong_execute",
            )
    assert caught.value.info.code == "scheduler.fence_rejected"
