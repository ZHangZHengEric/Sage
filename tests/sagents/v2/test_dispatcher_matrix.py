from __future__ import annotations

import asyncio
from contextvars import ContextVar
from types import SimpleNamespace

import pytest

from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.items import TextBlock
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
from sagents.v2.runtime.execution.scheduler import (
    FilesystemScheduler,
    InMemoryScheduler,
    WorkItem,
)
from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.session import (
    EphemeralSessionStore,
    FilesystemSessionStore,
    LeaseFencedSessionStore,
)
from sagents.v2.sagent import SAgent


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="worker", principal_type=PrincipalType.WORKER)
)


class FakeAgent:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.scope_active: ContextVar[bool] | None = None

    def _ensure_execution(self, run_id, context, *, resume):
        del run_id, context, resume

        async def execute():
            try:
                self.started.set()
                if self.scope_active is not None:
                    assert self.scope_active.get() is True
                await asyncio.sleep(self.delay)
                return SimpleNamespace(state=RunState.COMPLETED)
            finally:
                self.cancelled.set()

        return asyncio.create_task(execute())

    async def _fail_driver_crash(self, run_id, error, context):
        del run_id, error, context
        return SimpleNamespace(state=RunState.FAILED)


class RecoveryAgent(FakeAgent):
    def __init__(self, runtime: HarnessRuntime) -> None:
        super().__init__()
        self.runtime = runtime
        self.executions: list[tuple[str, bool]] = []

    def _ensure_execution(self, run_id, context, *, resume):
        async def execute():
            self.executions.append((run_id, resume))
            current = await self.runtime.get_run(run_id)
            return await self.runtime.fail_run(
                run_id=run_id,
                expected_revision=current.revision,
                error=RuntimeErrorInfo(
                    code="test.recovered_execution",
                    category=ErrorCategory.INTERNAL,
                    message="recovered execution reached the driver",
                ),
                context=context,
                idempotency_key=f"test-recovered:{run_id}",
            )

        return asyncio.create_task(execute())


def start_command(idempotency_key: str) -> StartRun:
    return StartRun(
        agent_id="agent",
        input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
        resolved_spec_hash="sha256:test",
        idempotency_key=idempotency_key,
    )


async def wait_for_terminal(runtime: HarnessRuntime, run_id: str):
    async with asyncio.timeout(2):
        while True:
            snapshot = await runtime.get_run(run_id)
            if snapshot.state in {RunState.FAILED, RunState.COMPLETED}:
                return snapshot
            await asyncio.sleep(0.01)


async def persist_dispatch_work(root, handle, *, resume: bool = False) -> None:
    scheduler = FilesystemScheduler(root)
    await scheduler.submit(
        WorkItem(
            work_id=f"work-{handle.run_id}",
            run_id=handle.run_id,
            available_at=utc_now(),
            idempotency_key=f"dispatch:{handle.run_id}",
            payload={
                "resume": resume,
                "request_context": CONTEXT.model_dump(mode="json"),
            },
        )
    )
    await scheduler.close()


@pytest.mark.asyncio
async def test_execution_survives_lease_renewal_and_worker_remains_available():
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(
        scheduler,
        max_concurrent_runs=1,
        lease_seconds=0.3,
    )
    agent = FakeAgent(delay=0.4)
    first = await dispatcher.submit(
        agent,
        SimpleNamespace(run_id="run-1", run_revision=0),
        CONTEXT,
    )
    assert (await asyncio.wait_for(first, timeout=2)).state == RunState.COMPLETED

    second = await dispatcher.submit(
        agent,
        SimpleNamespace(run_id="run-2", run_revision=0),
        CONTEXT,
    )
    assert (await asyncio.wait_for(second, timeout=2)).state == RunState.COMPLETED
    assert len(dispatcher._workers) == 1
    assert not dispatcher._workers[0].done()
    await dispatcher.close()


@pytest.mark.asyncio
async def test_second_resume_uses_the_new_run_revision():
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    agent = FakeAgent()
    first = await dispatcher.submit(
        agent,
        SimpleNamespace(run_id="run-resume", revision=2),
        CONTEXT,
        resume=True,
    )
    await asyncio.wait_for(first, timeout=1)
    second = await dispatcher.submit(
        agent,
        SimpleNamespace(run_id="run-resume", revision=4),
        CONTEXT,
        resume=True,
    )
    await asyncio.wait_for(second, timeout=1)
    await dispatcher.close()


@pytest.mark.asyncio
async def test_close_cancels_execution_before_requeueing_work():
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    agent = FakeAgent(delay=60)
    result = await dispatcher.submit(
        agent,
        SimpleNamespace(run_id="run-close", run_revision=0),
        CONTEXT,
    )
    await asyncio.wait_for(agent.started.wait(), timeout=1)
    await dispatcher.close()
    assert agent.cancelled.is_set()
    assert (await result).state == RunState.FAILED
    assert (
        await scheduler.claim(
            "replacement", lease_duration=dispatcher.lease_duration, wait_timeout=0
        )
        is None
    )


@pytest.mark.asyncio
async def test_shutdown_failure_recording_error_still_completes_result_future():
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)

    class UnavailableStoreAgent(FakeAgent):
        async def _fail_driver_crash(self, run_id, error, context):
            del run_id, error, context
            raise OSError("store unavailable")

    agent = UnavailableStoreAgent(delay=60)
    result = await dispatcher.submit(
        agent,
        SimpleNamespace(run_id="run-close-store-failure", run_revision=0),
        CONTEXT,
    )
    await asyncio.wait_for(agent.started.wait(), timeout=1)

    await dispatcher.close()

    with pytest.raises(OSError, match="store unavailable"):
        await asyncio.wait_for(result, timeout=1)
    assert dispatcher._requests == {}


@pytest.mark.asyncio
async def test_execution_task_inherits_the_worker_lease_scope():
    scheduler = InMemoryScheduler()
    active = ContextVar("active-test-lease", default=False)

    class Scope:
        async def __aenter__(self):
            self.token = active.set(True)

        async def __aexit__(self, exc_type, exc, traceback):
            active.reset(self.token)

    dispatcher = LocalWorkerDispatcher(
        scheduler,
        max_concurrent_runs=1,
        lease_scope_factory=lambda lease: Scope(),
    )
    agent = FakeAgent()
    agent.scope_active = active
    result = await dispatcher.submit(
        agent,
        SimpleNamespace(run_id="run-fenced", run_revision=0),
        CONTEXT,
    )
    await asyncio.wait_for(result, timeout=1)
    await dispatcher.close()


@pytest.mark.asyncio
async def test_shutdown_records_a_typed_terminal_failure_instead_of_requeueing():
    scheduler = InMemoryScheduler()
    store = EphemeralSessionStore()
    fenced = LeaseFencedSessionStore(store, scheduler)
    control_runtime = HarnessRuntime(store)
    started = asyncio.Event()
    closed = asyncio.Event()

    class SlowDriver:
        async def execute(self, run_id, context):
            started.set()
            await asyncio.Event().wait()

        async def resume(self, run_id, context):
            return await self.execute(run_id, context)

        async def close(self):
            closed.set()

    driver = SlowDriver()
    agent = SAgent(runtime=control_runtime, driver_factory=lambda run_id: driver)
    dispatcher = LocalWorkerDispatcher(
        scheduler,
        max_concurrent_runs=1,
        lease_scope_factory=fenced.lease_scope,
    )
    agent.attach_dispatcher(dispatcher)
    stream = await agent.run_stream(
        StartRun(
            agent_id="agent",
            input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            resolved_spec_hash="sha256:test",
            idempotency_key="shutdown-run",
        ),
        CONTEXT,
    )
    await asyncio.wait_for(started.wait(), timeout=1)

    await dispatcher.close()

    result = await stream.wait()
    assert result.state == RunState.FAILED
    terminal = await control_runtime.get_run_result(result.run_id)
    assert terminal.error is not None
    assert terminal.error.code == "scheduler.worker_shutdown"
    assert closed.is_set()
    await agent.close()
    await scheduler.close()


@pytest.mark.asyncio
async def test_dispatcher_restores_queued_work_after_process_restart(tmp_path):
    runtime = HarnessRuntime(EphemeralSessionStore())
    handle = await runtime.start_run(start_command("recover-queued"), CONTEXT)
    await persist_dispatch_work(tmp_path, handle)

    scheduler = FilesystemScheduler(tmp_path)
    agent = RecoveryAgent(runtime)
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    dispatcher.attach_recovery_agent(agent)
    await dispatcher.start()

    snapshot = await wait_for_terminal(runtime, handle.run_id)
    assert snapshot.state == RunState.FAILED
    assert agent.executions == [(handle.run_id, False)]
    assert await scheduler.pending_count() == 0
    await dispatcher.close()


@pytest.mark.asyncio
async def test_dispatcher_rebuilds_missing_scheduler_work_from_durable_run(tmp_path):
    store_path = tmp_path / "sessions"
    first_store = FilesystemSessionStore(store_path)
    first_runtime = HarnessRuntime(first_store)
    handle = await first_runtime.start_run(
        start_command("recover-missing-scheduler-work"), CONTEXT
    )
    await first_store.close()

    restored_store = FilesystemSessionStore(store_path)
    restored_runtime = HarnessRuntime(restored_store)
    scheduler = InMemoryScheduler()
    agent = RecoveryAgent(restored_runtime)
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    dispatcher.attach_recovery_agent(agent)
    await dispatcher.start()

    snapshot = await wait_for_terminal(restored_runtime, handle.run_id)
    assert snapshot.state == RunState.FAILED
    assert agent.executions == [(handle.run_id, False)]
    await dispatcher.close()
    await restored_store.close()


@pytest.mark.asyncio
async def test_dispatcher_does_not_replay_uncheckpointed_running_work(tmp_path):
    runtime = HarnessRuntime(EphemeralSessionStore())
    handle = await runtime.start_run(start_command("recover-running"), CONTEXT)
    running = await runtime.start_execution(
        run_id=handle.run_id,
        expected_revision=handle.run_revision,
        context=CONTEXT,
        idempotency_key="recover-running:start",
    )
    assert running.state == RunState.RUNNING
    await persist_dispatch_work(tmp_path, handle)

    scheduler = FilesystemScheduler(tmp_path)
    agent = RecoveryAgent(runtime)
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    dispatcher.attach_recovery_agent(agent)
    await dispatcher.start()

    snapshot = await wait_for_terminal(runtime, handle.run_id)
    result = await runtime.get_run_result(handle.run_id)
    assert snapshot.state == RunState.FAILED
    assert result.error is not None
    assert result.error.code == "execution.worker_restarted"
    assert agent.executions == []
    assert await scheduler.pending_count() == 0
    await dispatcher.close()


@pytest.mark.asyncio
async def test_recovery_fails_active_inline_child_with_parent_worker(tmp_path):
    runtime = HarnessRuntime(EphemeralSessionStore())
    parent = await runtime.start_run(start_command("recover-tree-parent"), CONTEXT)
    parent_running = await runtime.start_execution(
        run_id=parent.run_id,
        expected_revision=parent.run_revision,
        context=CONTEXT,
        idempotency_key="recover-tree-parent:start",
    )
    child = await runtime.start_run(
        StartRun(
            session_id=parent.session_id,
            agent_id="child-agent",
            input=(InputItem(role="user", content=(TextBlock(text="child work"),)),),
            session_concurrency_mode=SessionConcurrencyMode.FORK,
            resolved_spec_hash="sha256:test",
            idempotency_key="recover-tree-child",
            parent_run_id=parent.run_id,
        ),
        CONTEXT,
    )
    await runtime.start_execution(
        run_id=child.run_id,
        expected_revision=child.run_revision,
        context=CONTEXT,
        idempotency_key="recover-tree-child:start",
    )
    await persist_dispatch_work(tmp_path, parent)

    scheduler = FilesystemScheduler(tmp_path)
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    dispatcher.attach_recovery_agent(RecoveryAgent(runtime))
    await dispatcher.start()

    await wait_for_terminal(runtime, parent_running.run_id)
    child_result = await runtime.get_run_result(child.run_id)
    assert child_result.outcome == RunState.FAILED
    assert child_result.error is not None
    assert child_result.error.code == "execution.parent_worker_restarted"
    await dispatcher.close()
