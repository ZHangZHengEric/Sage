from __future__ import annotations

import asyncio

import pytest

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.events import RunEventData
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.runtime.session import EventDraft
from sagents.v2.runtime.session.state import SessionStoreCoordinator


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="session-sharding",
        principal_type=PrincipalType.SERVICE,
        tenant_id="tenant",
    )
)


class BarrierSessionStore(SessionStoreCoordinator):
    def __init__(self) -> None:
        super().__init__()
        self.enabled = False
        self.expected_arrivals = 2
        self.arrivals: list[str] = []
        self.arrived = asyncio.Event()
        self.release = asyncio.Event()
        self.fail_session_id: str | None = None

    async def _commit_storage_locked(self, session_id: str) -> None:
        if not self.enabled:
            return
        self.arrivals.append(session_id)
        if len(self.arrivals) >= self.expected_arrivals:
            self.arrived.set()
        await self.release.wait()
        if session_id == self.fail_session_id:
            raise OSError("injected target Session write failure")


def command(key: str, session_id: str) -> StartRun:
    return StartRun(
        agent_id="agent",
        session_id=session_id,
        session_concurrency_mode=SessionConcurrencyMode.SNAPSHOT_ISOLATED,
        input=(InputItem(role="user", content=(TextBlock(text=key),)),),
        resolved_spec_hash="sha256:session-sharding",
        idempotency_key=key,
    )


async def start(store: BarrierSessionStore, key: str, session_id: str):
    return (await store.create_run(command(key, session_id), CONTEXT)).handle


async def mark_running(store: BarrierSessionStore, run_id: str, key: str):
    return await store.commit_run(
        run_id=run_id,
        expected_revision=0,
        expected_states={RunState.QUEUED},
        new_state=RunState.RUNNING,
        drafts=(
            EventDraft(type="run.started", data=RunEventData(state="running")),
        ),
        context=CONTEXT,
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_different_session_persistence_can_overlap():
    store = BarrierSessionStore()
    first = await start(store, "first", "session-a")
    second = await start(store, "second", "session-b")
    store.enabled = True

    tasks = [
        asyncio.create_task(mark_running(store, first.run_id, "commit-first")),
        asyncio.create_task(mark_running(store, second.run_id, "commit-second")),
    ]
    await asyncio.wait_for(store.arrived.wait(), timeout=1)
    assert set(store.arrivals) == {"session-a", "session-b"}
    store.release.set()
    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_same_session_mutations_never_overlap():
    store = BarrierSessionStore()
    first = await start(store, "first", "session-shared")
    second = await start(store, "second", "session-shared")
    store.enabled = True
    store.expected_arrivals = 1

    tasks = [
        asyncio.create_task(mark_running(store, first.run_id, "commit-first")),
        asyncio.create_task(mark_running(store, second.run_id, "commit-second")),
    ]
    await asyncio.wait_for(store.arrived.wait(), timeout=1)
    await asyncio.sleep(0.05)
    assert store.arrivals == ["session-shared"]
    store.release.set()
    await asyncio.gather(*tasks)
    assert store.arrivals == ["session-shared", "session-shared"]


@pytest.mark.asyncio
async def test_write_failure_rolls_back_only_target_session():
    store = BarrierSessionStore()
    failed = await start(store, "failed", "session-failed")
    healthy = await start(store, "healthy", "session-healthy")
    store.enabled = True
    store.fail_session_id = "session-failed"

    tasks = [
        asyncio.create_task(mark_running(store, failed.run_id, "commit-failed")),
        asyncio.create_task(mark_running(store, healthy.run_id, "commit-healthy")),
    ]
    await asyncio.wait_for(store.arrived.wait(), timeout=1)
    store.release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)

    assert isinstance(results[0], OSError)
    assert not isinstance(results[1], BaseException)
    assert (await store.get_run(failed.run_id)).state == RunState.QUEUED
    assert (await store.get_run(healthy.run_id)).state == RunState.RUNNING


@pytest.mark.asyncio
async def test_cancelled_multi_session_lock_acquisition_releases_partial_locks():
    store = BarrierSessionStore()
    await start(store, "first", "session-a")
    await start(store, "second", "session-b")
    second_lock = store._session_locks["session-b"]
    await second_lock.acquire()

    async def acquire_both():
        async with store._session_operation("session-a", "session-b"):
            raise AssertionError("blocked operation unexpectedly acquired both locks")

    task = asyncio.create_task(acquire_both())
    await asyncio.sleep(0)
    assert store._session_locks["session-a"].locked()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not store._session_locks["session-a"].locked()
    second_lock.release()
