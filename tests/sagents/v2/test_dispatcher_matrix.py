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
from sagents.v2.contracts.run_state import RunState
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
from sagents.v2.runtime.session import EphemeralSessionStore, LeaseFencedSessionStore
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
