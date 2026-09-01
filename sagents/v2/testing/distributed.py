"""Reusable conformance probes for distributed-capable v2 providers."""

from __future__ import annotations

import inspect
import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.common import new_id, utc_now
from sagents.v2.contracts.events import RunEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.execution.scheduler import (
    LeaseReleaseReason,
    Scheduler,
    SchedulerClaimPolicy,
    WorkItem,
)
from sagents.v2.runtime.session import EventDraft, SessionStore


async def run_scheduler_conformance(scheduler: Scheduler) -> None:
    """Assert exclusive Run claims, stale fencing, and global tenant quota."""

    prefix = new_id("conformance")
    lease_duration = timedelta(seconds=30)
    same_run = f"{prefix}-same-run"
    for suffix in ("one", "two"):
        await scheduler.submit(
            WorkItem(
                work_id=f"{prefix}-{suffix}",
                run_id=same_run,
                tenant_id="tenant-exclusive",
                available_at=utc_now(),
                idempotency_key=f"{prefix}-{suffix}",
            )
        )
    first = await scheduler.claim(
        f"{prefix}-worker-one",
        lease_duration=timedelta(seconds=0.05),
        wait_timeout=0,
    )
    competing = await scheduler.claim(
        f"{prefix}-worker-two",
        lease_duration=lease_duration,
        wait_timeout=0,
    )
    if first is None or competing is not None:
        raise AssertionError("two Workers acquired the same Run concurrently")

    # Let the authoritative provider replace an expired lease; the old Worker
    # must be fenced even if it retained the complete original token.
    await asyncio.sleep(0.06)
    replacement = await scheduler.claim(
        f"{prefix}-worker-replacement",
        lease_duration=timedelta(seconds=0.05),
        wait_timeout=0,
    )
    if replacement is None:
        raise AssertionError("requeued work could not obtain a replacement lease")
    try:
        await scheduler.assert_fence(first)
    except Exception:
        pass
    else:
        raise AssertionError("stale Worker lease remained authoritative")
    await scheduler.release(replacement, LeaseReleaseReason.COMPLETED)
    remaining = await scheduler.claim(
        f"{prefix}-worker-drain",
        lease_duration=lease_duration,
        wait_timeout=0,
    )
    if remaining is not None:
        await scheduler.release(remaining, LeaseReleaseReason.COMPLETED)

    policy = SchedulerClaimPolicy(max_active_per_tenant=1)
    for suffix, tenant in (
        ("a-one", "tenant-a"),
        ("a-two", "tenant-a"),
        ("b-one", "tenant-b"),
    ):
        await scheduler.submit(
            WorkItem(
                work_id=f"{prefix}-{suffix}",
                run_id=f"{prefix}-run-{suffix}",
                tenant_id=tenant,
                available_at=utc_now(),
                idempotency_key=f"{prefix}-quota-{suffix}",
            )
        )
    tenant_a = await scheduler.claim(
        f"{prefix}-quota-one",
        lease_duration=lease_duration,
        policy=policy,
        wait_timeout=0,
    )
    other_tenant = await scheduler.claim(
        f"{prefix}-quota-two",
        lease_duration=lease_duration,
        policy=policy,
        wait_timeout=0,
    )
    if (
        tenant_a is None
        or tenant_a.work.tenant_id != "tenant-a"
        or other_tenant is None
        or other_tenant.work.tenant_id != "tenant-b"
    ):
        raise AssertionError("atomic tenant quota blocked or exceeded eligibility")
    await scheduler.release(tenant_a, LeaseReleaseReason.COMPLETED)
    await scheduler.release(other_tenant, LeaseReleaseReason.COMPLETED)


async def run_session_store_recovery_conformance(
    factory: Callable[[], SessionStore | Awaitable[SessionStore]],
    context: RequestContext,
) -> None:
    """Assert mutation/outbox atomicity and durable cursor recovery on restart."""

    async def create_store() -> SessionStore:
        value = factory()
        if inspect.isawaitable(value):
            value = await value
        return value

    store = await create_store()
    created = await store.create_run(
        StartRun(
            agent_id="conformance-agent",
            input=(InputItem(role="user", content=(TextBlock(text="probe"),)),),
            resolved_spec_hash="sha256:distributed-conformance",
            idempotency_key=new_id("conformance-start"),
        ),
        context,
    )
    committed = await store.commit_run(
        run_id=created.handle.run_id,
        expected_revision=0,
        expected_states={RunState.QUEUED},
        new_state=RunState.RUNNING,
        drafts=(
            EventDraft(type="run.started", data=RunEventData(state="running")),
        ),
        context=context,
        idempotency_key=new_id("conformance-commit"),
    )
    replay = await store.read_events(created.handle.run_id, after_sequence=0)
    if tuple(event.event_id for event in replay[-len(committed.events) :]) != tuple(
        event.event_id for event in committed.events
    ):
        raise AssertionError("Session mutation and Outbox events partially committed")
    cursor = replay[-1].run_sequence
    close = getattr(store, "close", None)
    if callable(close):
        await close()

    reopened = await create_store()
    restored = await reopened.get_run(created.handle.run_id)
    if restored.state != RunState.RUNNING:
        raise AssertionError("Run state was not durable across provider restart")
    resumed = await reopened.read_events(
        created.handle.run_id, after_sequence=cursor - 1
    )
    if not resumed or resumed[0].run_sequence != cursor:
        raise AssertionError("durable cursor could not resume after provider restart")
    close = getattr(reopened, "close", None)
    if callable(close):
        await close()
