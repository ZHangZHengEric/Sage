from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from sagents.v2._concurrency import bounded_to_thread
from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.jobs import JobCompletion, JobSpec, JobState
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
from sagents.v2.runtime.execution.jobs import InMemoryJobRuntime
from sagents.v2.runtime.execution.scheduler import (
    FilesystemScheduler,
    InMemoryScheduler,
    WorkItem,
)
from sagents.v2.session_memory import SqliteBm25SessionMemoryProvider
from sagents.v2.memory import FilesystemBm25MemoryProvider


def spec(key, **kwargs):
    return JobSpec(owner_run_id="run", kind="probe", idempotency_key=key, **kwargs)


@pytest.mark.asyncio
async def test_job_admission_is_atomic_and_duplicate_is_allowed_when_full():
    release = asyncio.Event()

    async def runner(*args):
        await release.wait()
        return JobCompletion()

    jobs = InMemoryJobRuntime(
        {"probe": runner}, max_concurrent_jobs=1, max_admitted_jobs=3
    )
    try:
        results = await asyncio.gather(
            *(jobs.submit(spec(str(i))) for i in range(50)), return_exceptions=True
        )
        handles = [r for r in results if not isinstance(r, Exception)]
        errors = [r for r in results if isinstance(r, Exception)]
        assert len(handles) == 3
        assert all(
            isinstance(e, SageV2Error)
            and e.info.code == "job.queue_full"
            and e.info.retryable
            for e in errors
        )
        assert (await jobs.submit(spec("0"))).job_id == handles[0].job_id
        await jobs.cancel(handles[-1].job_id)
        replacement = await jobs.submit(spec("replacement"))
        assert replacement.job_id != handles[-1].job_id
        assert (await jobs.capabilities()).max_admitted_jobs == 3
    finally:
        release.set()
        await jobs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested,byte_limit,chunk_limit,expected",
    [(None, 5, 10, 5), (100, 5, 10, 5), (3, 5, 10, 3), (None, 100, 2, 4)],
)
async def test_job_output_ceilings_are_observable(
    requested, byte_limit, chunk_limit, expected
):
    async def runner(spec, emit, cancelled):
        for _ in range(10):
            await emit("stdout", b"ab")
        return JobCompletion()

    jobs = InMemoryJobRuntime(
        {"probe": runner},
        max_job_output_bytes=byte_limit,
        max_job_output_chunks=chunk_limit,
    )
    try:
        handle = await jobs.submit(spec("output", max_output_bytes=requested))
        result = await jobs.wait(handle.job_id)
        chunks = await jobs.read_output(handle.output_cursor)
        assert sum(len(c.data) for c in chunks) == expected
        assert len(chunks) <= chunk_limit
        assert result.output_truncated is True
    finally:
        await jobs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_registered_job_waiter_survives_immediate_terminal_eviction(cancel):
    release = asyncio.Event()

    async def runner(*args):
        await release.wait()
        return JobCompletion()

    jobs = InMemoryJobRuntime(
        {"probe": runner},
        max_retained_terminal_jobs=0,
        output_reconnect_window_seconds=0,
    )
    handle = await jobs.submit(spec("eviction"))
    waiter = asyncio.create_task(jobs.wait(handle.job_id))
    await asyncio.sleep(0)
    if cancel:
        assert (await jobs.cancel(handle.job_id)).state == JobState.KILLED
    else:
        release.set()
    result = await asyncio.wait_for(waiter, 2)
    assert result.state == (JobState.KILLED if cancel else JobState.COMPLETED)
    assert handle.job_id not in jobs._rows
    await jobs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_type,method",
    [
        (SqliteBm25SessionMemoryProvider, "_forget_session"),
        (FilesystemBm25MemoryProvider, "_record_count"),
    ],
)
async def test_cancelled_memory_io_keeps_lock_until_thread_finishes(
    tmp_path, monkeypatch, provider_type, method
):
    provider = provider_type(tmp_path)
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    release = threading.Event()
    calls = 0

    def operation(*args):
        nonlocal calls
        calls += 1
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        return 0

    monkeypatch.setattr(provider, method, operation)

    async def invoke():
        if isinstance(provider, SqliteBm25SessionMemoryProvider):
            return await provider.forget_session("session")
        return await provider.health()

    first = asyncio.create_task(invoke())
    second = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert provider._lock.locked()
        second = asyncio.create_task(invoke())
        await asyncio.sleep(0.02)
        assert calls == 1
    finally:
        release.set()
        await asyncio.gather(
            first, *([second] if second else []), return_exceptions=True
        )
    assert not provider._lock.locked()


@pytest.mark.asyncio
async def test_cancelled_capacity_waiter_releases_provider_lock():
    release = threading.Event()
    loop = asyncio.get_running_loop()
    entered = asyncio.Queue()

    def operation():
        loop.call_soon_threadsafe(entered.put_nowait, True)
        assert release.wait(5)

    tasks = [
        asyncio.create_task(bounded_to_thread("memory-io", operation)) for _ in range(8)
    ]
    lock = asyncio.Lock()
    waiting = None
    try:
        for _ in range(8):
            await asyncio.wait_for(entered.get(), 2)
        waiting = asyncio.create_task(
            bounded_to_thread("memory-io", lambda: None, lock=lock)
        )
        await asyncio.sleep(0)
        assert lock.locked()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert not lock.locked()
    finally:
        release.set()
        await asyncio.gather(
            *tasks, *([waiting] if waiting else []), return_exceptions=True
        )


@pytest.mark.asyncio
async def test_cancelled_scheduler_write_retains_writer_ownership(
    tmp_path, monkeypatch
):
    scheduler = FilesystemScheduler(tmp_path)
    entered = asyncio.Event()
    loop = asyncio.get_running_loop()
    release = threading.Event()
    original = scheduler._state_store._write

    def write(state):
        loop.call_soon_threadsafe(entered.set)
        assert release.wait(5)
        original(state)

    monkeypatch.setattr(scheduler._state_store, "_write", write)
    submit = asyncio.create_task(
        scheduler.submit(
            WorkItem(
                work_id="work",
                run_id="run",
                idempotency_key="key",
                available_at=utc_now(),
            )
        )
    )
    closing = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        submit.cancel()
        await asyncio.sleep(0)
        submit.cancel()
        closing = asyncio.create_task(scheduler.close())
        await asyncio.sleep(0.02)
        assert not closing.done()
        with pytest.raises(SageV2Error):
            FilesystemScheduler(tmp_path)
    finally:
        release.set()
        await asyncio.gather(
            submit, *([closing] if closing else []), return_exceptions=True
        )
        await scheduler.close()
    reopened = FilesystemScheduler(tmp_path)
    assert "work" in reopened._items
    await reopened.close()


class Agent:
    def __init__(self):
        self.executed = 0

    def ensure_execution(self, *args, **kwargs):
        async def execute():
            self.executed += 1
            return SimpleNamespace(state=RunState.COMPLETED)

        return asyncio.create_task(execute())


@pytest.mark.asyncio
@pytest.mark.parametrize("transient", [True, False])
async def test_dispatcher_claim_failure_recovers_or_settles_caller(transient):
    class Scheduler(InMemoryScheduler):
        calls = 0

        async def claim(self, *args, **kwargs):
            self.calls += 1
            if self.calls <= 2:
                raise (
                    OSError("temporarily unavailable")
                    if transient
                    else ValueError("invalid scheduler")
                )
            return await super().claim(*args, **kwargs)

    scheduler = Scheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    context = RequestContext(
        actor=ActorRef(principal_id="test", principal_type=PrincipalType.SERVICE)
    )
    agent = Agent()
    try:
        result = await dispatcher.submit(
            agent, SimpleNamespace(run_id="run", revision=0), context
        )
        if transient:
            assert (await asyncio.wait_for(result, 2)).state == RunState.COMPLETED
            assert agent.executed == 1
            assert not dispatcher._workers[0].done()
        else:
            with pytest.raises(ValueError, match="invalid scheduler"):
                await asyncio.wait_for(result, 2)
            with pytest.raises(ValueError, match="invalid scheduler"):
                await dispatcher.submit(
                    agent, SimpleNamespace(run_id="next", revision=0), context
                )
            assert agent.executed == 0
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("byte_limit,chunk_limit,expected", [(5, 100, 5), (100, 2, 4)])
async def test_global_job_output_budget_is_shared_and_reclaimed(
    byte_limit, chunk_limit, expected
):
    async def runner(spec, emit, cancelled):
        await emit("stdout", b"ab")
        await emit("stdout", b"cd")
        return JobCompletion()

    jobs = InMemoryJobRuntime(
        {"probe": runner},
        max_buffered_output_bytes=byte_limit,
        max_buffered_output_chunks=chunk_limit,
    )
    try:
        a = await jobs.submit(spec("a"))
        await jobs.wait(a.job_id)
        b = await jobs.submit(spec("b"))
        result = await jobs.wait(b.job_id)
        assert result.output_truncated
        assert jobs._buffered_output_bytes == expected
        assert jobs._buffered_output_chunks <= chunk_limit
        await jobs.purge_terminal(owner_run_id="run")
        assert jobs._buffered_output_bytes == jobs._buffered_output_chunks == 0
        c = await jobs.submit(spec("c"))
        assert not (await jobs.wait(c.job_id)).output_truncated
    finally:
        await jobs.close()


@pytest.mark.asyncio
async def test_reconnect_protection_does_not_allow_unbounded_job_metadata():
    async def runner(*args):
        return JobCompletion()

    jobs = InMemoryJobRuntime(
        {"probe": runner}, max_admitted_jobs=1, max_retained_terminal_jobs=1
    )
    try:
        for key in ("a", "b"):
            handle = await jobs.submit(spec(key))
            await jobs.wait(handle.job_id)
            await asyncio.sleep(0)
        with pytest.raises(SageV2Error, match="capacity"):
            await jobs.submit(spec("c"))
        assert len(jobs._rows) == 2
        await jobs.purge_terminal(owner_run_id="run")
        await jobs.submit(spec("c"))
    finally:
        await jobs.close()


@pytest.mark.asyncio
async def test_bad_recovery_payload_and_release_failure_do_not_kill_worker():
    class Scheduler(InMemoryScheduler):
        orphan_release_attempted = False

        async def release(self, lease, reason, *, requeue=False):
            if lease.work.work_id == "orphan":
                self.orphan_release_attempted = True
                raise OSError("release unavailable")
            return await super().release(lease, reason, requeue=requeue)

    scheduler = Scheduler()
    await scheduler.submit(
        WorkItem(
            work_id="orphan",
            run_id="orphan-run",
            available_at=utc_now(),
            idempotency_key="orphan",
            payload={"request_context": {"invalid": True}},
        )
    )
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    agent = Agent()
    dispatcher.attach_recovery_agent(agent)
    context = RequestContext(
        actor=ActorRef(principal_id="test", principal_type=PrincipalType.SERVICE)
    )
    try:
        result = await dispatcher.submit(
            agent, SimpleNamespace(run_id="normal", revision=0), context
        )
        assert (await asyncio.wait_for(result, 2)).state == RunState.COMPLETED
        assert scheduler.orphan_release_attempted
        assert not dispatcher._workers[0].done()
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_permanent_claim_failure_does_not_fail_already_running_work():
    started = asyncio.Event()
    finish = asyncio.Event()
    fail_claim = asyncio.Event()

    class Scheduler(InMemoryScheduler):
        async def claim(self, worker_id, **kwargs):
            if worker_id == "local-1":
                await fail_claim.wait()
                raise ValueError("claim backend failed")
            return await super().claim(worker_id, **kwargs)

    class BlockingAgent:
        def ensure_execution(self, *args, **kwargs):
            async def execute():
                started.set()
                await finish.wait()
                return SimpleNamespace(state=RunState.COMPLETED)

            return asyncio.create_task(execute())

    scheduler = Scheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=2)
    context = RequestContext(
        actor=ActorRef(principal_id="test", principal_type=PrincipalType.SERVICE)
    )
    try:
        active = await dispatcher.submit(
            BlockingAgent(), SimpleNamespace(run_id="active", revision=0), context
        )
        await asyncio.wait_for(started.wait(), 2)
        pending = await dispatcher.submit(
            Agent(), SimpleNamespace(run_id="pending", revision=0), context
        )
        fail_claim.set()
        with pytest.raises(ValueError, match="claim backend failed"):
            await asyncio.wait_for(pending, 2)
        assert not active.done()
        finish.set()
        assert (await asyncio.wait_for(active, 2)).state == RunState.COMPLETED
    finally:
        finish.set()
        await dispatcher.close()
        await scheduler.close()
