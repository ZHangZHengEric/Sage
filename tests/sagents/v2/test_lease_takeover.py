"""Lease loss continues the same durable Run and inline Team tree."""

import asyncio
from datetime import timedelta

import pytest

from sagents.v2.contracts.common import utc_now
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.execution.dispatcher import (
    DEFAULT_LEASE_SECONDS,
    LocalWorkerDispatcher,
)
from sagents.v2.runtime.execution.scheduler import (
    InMemoryScheduler,
    FilesystemScheduler,
    WorkItem,
)
from sagents.v2.runtime.session import FilesystemSessionStore, LeaseFencedSessionStore
from sagents.v2.sagent import SAgent
from tests.sagents.v2.test_process_restart_recovery import CONTEXT, Model, team_factory


class Clock:
    offset = timedelta()

    def __call__(self):
        return utc_now() + self.offset


class RecordingScheduler(InMemoryScheduler):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.claimed = []

    async def renew(self, lease, **kwargs):
        if getattr(self, "cancel_next_renewal", False):
            self.cancel_next_renewal = False
            raise asyncio.CancelledError()
        return await super().renew(lease, **kwargs)

    async def claim(self, *args, **kwargs):
        lease = await super().claim(*args, **kwargs)
        if lease is not None:
            self.claimed.append(lease)
        return lease


async def wait_until(predicate):
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "losses,trigger",
    [
        (1, "renewal"),
        (2, "renewal"),
        (1, "commit"),
        (2, "commit"),
        (1, "renewer_cancelled"),
        (1, "local_cancel"),
        (1, "user_cancel"),
        (1, "shutdown"),
    ],
)
async def test_expired_lease_recovers_same_team_and_saved_results(
    tmp_path, losses, trigger
):
    clock = Clock()
    scheduler = RecordingScheduler(clock=clock)
    store = FilesystemSessionStore(tmp_path / "store")
    fenced = LeaseFencedSessionStore(store, scheduler)
    runtime = HarnessRuntime(store)
    executor_runtime = HarnessRuntime(fenced)
    generations = []
    before = {}
    active_slow_streams = 0
    maximum_slow_streams = 0

    class ObservedModel(Model):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.allow_commit = asyncio.Event()

        async def stream(self, request):
            nonlocal active_slow_streams, maximum_slow_streams
            name = (await store.get_start_command(request.run_id)).agent_id
            if name == "slow":
                active_slow_streams += 1
                maximum_slow_streams = max(maximum_slow_streams, active_slow_streams)
            try:
                if (
                    trigger == "commit"
                    and self.crash
                    and name == "slow"
                    and any(m.role == "tool" for m in request.messages)
                ):
                    from tests.sagents.v2.test_process_restart_recovery import (
                        completion,
                    )

                    await wait_until(lambda: (tmp_path / "fast-completed").exists())
                    (tmp_path / "ready").write_text("old worker about to commit")
                    await self.allow_commit.wait()
                    yield completion("stale response must not commit")
                else:
                    async for event in super().stream(request):
                        yield event
            finally:
                if name == "slow":
                    # Give another worker time to claim the expired lease while
                    # this generation is still draining its cancelled model.
                    if self.crash:
                        await asyncio.sleep(0.08)
                    active_slow_streams -= 1

    def driver_factory(run_id):
        generation = len(generations)
        model = ObservedModel(tmp_path, store, team=True, crash=generation < losses)
        generations.append(model)
        factory, descriptor = team_factory(
            tmp_path, executor_runtime, model, crash=True
        )
        return factory.create_loop(descriptor, run_id)

    agent = SAgent(runtime=runtime, driver_factory=driver_factory)
    dispatcher = LocalWorkerDispatcher(
        scheduler,
        max_concurrent_runs=2,
        max_concurrent_runs_per_tenant=2,
        lease_seconds=0.15
        if trigger in {"renewal", "renewer_cancelled"}
        else DEFAULT_LEASE_SECONDS,
        lease_scope_factory=fenced.lease_scope,
        preserve_runs_on_shutdown=trigger != "shutdown",
    )
    agent.attach_dispatcher(dispatcher)
    handle = await agent.start_run(
        StartRun(
            agent_id="root",
            input=(InputItem(role="user", content=(TextBlock(text="original task"),)),),
            resolved_spec_hash="sha256:restart",
            idempotency_key="start",
        ),
        CONTEXT,
    )
    # Submit returns the existing caller's Future; a takeover must keep it pending.
    future = await dispatcher.submit(agent, handle, CONTEXT)
    try:
        for attempt in range(losses):
            await wait_until(lambda: (tmp_path / "ready").exists())
            (tmp_path / "ready").unlink()
            if attempt == 0:
                baseline_sessions = [
                    handle.session_id,
                    *[
                        child.session_id
                        for child in await store.list_descendant_sessions(
                            handle.session_id
                        )
                    ],
                ]
                for sid in baseline_sessions:
                    for original in await store.list_session_runs(sid):
                        before[original.run_id] = [
                            e.event_id for e in await store.read_events(original.run_id)
                        ]
            assert not future.done()
            if trigger == "shutdown":
                await dispatcher.close()
            elif trigger == "renewer_cancelled":
                scheduler.cancel_next_renewal = True
            elif trigger in {"local_cancel", "user_cancel"}:
                if trigger == "user_cancel":
                    from sagents.v2.contracts.commands import CancelRun

                    current = await runtime.get_run(handle.run_id)
                    await runtime.cancel_run(
                        CancelRun(
                            run_id=handle.run_id,
                            expected_revision=current.revision,
                            idempotency_key="user-stop",
                        ),
                        CONTEXT,
                    )
                agent._tasks[handle.run_id].cancel()
            else:
                clock.offset += timedelta(hours=49)
                if trigger == "commit":
                    generations[-1].allow_commit.set()
            if trigger != "shutdown":
                await wait_until(lambda: len(generations) >= attempt + 2)
        result = await asyncio.wait_for(asyncio.shield(future), 5)
        expected_state = {
            "user_cancel": RunState.CANCELLED,
            "shutdown": RunState.FAILED,
        }.get(trigger, RunState.COMPLETED)
        assert result.state == expected_state
        assert result.run_id == handle.run_id
        sessions = [
            handle.session_id,
            *[
                s.session_id
                for s in await store.list_descendant_sessions(handle.session_id)
            ],
        ]
        runs = [r for sid in sessions for r in await store.list_session_runs(sid)]
        assert len(runs) == 4
        if trigger == "shutdown":
            assert sum(r.state == RunState.FAILED for r in runs) == 1
            assert sum(r.state == RunState.CANCELLED for r in runs) == 2
            assert sum(r.state == RunState.COMPLETED for r in runs) == 1
        elif trigger == "user_cancel":
            assert sum(r.state == RunState.CANCELLED for r in runs) == 3
            assert sum(r.state == RunState.COMPLETED for r in runs) == 1
        else:
            assert all(r.state == RunState.COMPLETED for r in runs)
        for r in runs:
            events = await store.read_events(r.run_id)
            assert [e.event_id for e in events[: len(before[r.run_id])]] == before[
                r.run_id
            ]
            if trigger != "shutdown" or r.run_id != handle.run_id:
                assert not any(e.type == "run.failed" for e in events)
        for name in ("fast", "slow"):
            assert (tmp_path / f"effect-{name}").read_text() == "applied\n"
        assert maximum_slow_streams == 1
        assert len(generations) == (1 if trigger == "shutdown" else losses + 1)
        if trigger not in {"local_cancel", "user_cancel", "shutdown"}:
            assert len(scheduler.claimed) >= losses + 1
            with pytest.raises(SageV2Error) as stale:
                await scheduler.assert_fence(scheduler.claimed[0])
            assert stale.value.info.code == "scheduler.fence_rejected"
        for model in generations[1:]:
            names = [
                (await store.get_start_command(r.run_id)).agent_id
                for r in model.requests
            ]
            assert "fast" not in names
        assert not dispatcher._requests
    finally:
        await dispatcher.close()
        await agent.close()
        await scheduler.close()
        await store.close()


@pytest.mark.asyncio
async def test_default_lease_is_48_hours_and_reopen_does_not_wait_for_it(tmp_path):
    assert DEFAULT_LEASE_SECONDS == 172800
    dispatcher = LocalWorkerDispatcher(InMemoryScheduler())
    assert dispatcher.lease_duration == timedelta(hours=48)
    await dispatcher.close()
    scheduler = FilesystemScheduler(tmp_path)
    work = WorkItem(
        work_id="original-work",
        run_id="original-run",
        available_at=utc_now(),
        idempotency_key="original",
    )
    await scheduler.submit(work)
    old = await scheduler.claim(
        "old", lease_duration=timedelta(hours=48), wait_timeout=0
    )
    assert old.expires_at > utc_now() + timedelta(hours=47)
    await scheduler.close()
    restored = FilesystemScheduler(tmp_path)
    try:
        new = await restored.claim(
            "new", lease_duration=timedelta(hours=48), wait_timeout=0
        )
        assert new is not None
        assert new.work.run_id == old.work.run_id
        assert new.work.work_id == old.work.work_id
        assert new.fencing_token > old.fencing_token
        with pytest.raises(SageV2Error):
            await restored.assert_fence(old)
    finally:
        await restored.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("reconcilable", [True, False])
async def test_lease_loss_with_remote_tool_in_flight_does_not_replay_it(
    tmp_path, reconcilable
):
    from sagents.v2.contracts.commands import ReplyInteraction
    from sagents.v2.tool import (
        InMemoryToolCatalog,
        ReconcileResult,
        ReconcileState,
        ToolExecutionResult,
    )
    from tests.sagents.v2.test_process_restart_recovery import DEFINITION

    clock = Clock()
    scheduler = RecordingScheduler(clock=clock)
    store = FilesystemSessionStore(tmp_path / "store")
    fenced = LeaseFencedSessionStore(store, scheduler)
    runtime = HarnessRuntime(store)
    worker_runtime = HarnessRuntime(fenced)
    remote_applied = asyncio.Event()
    generation = 0
    effects = []

    class Executor:
        async def execute(self, call, context):
            if call.tool_name != "save_value":
                from sagents.v2.contracts.errors import RuntimeErrorInfo, ErrorCategory

                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="tool.not_found",
                        category=ErrorCategory.VALIDATION,
                        message="not handled",
                        safe_to_resume=True,
                    )
                )
            name = (await store.get_start_command(call.owner_run_id)).agent_id
            effects.append(name)
            if name == "slow":
                remote_applied.set()
                await asyncio.Event().wait()  # remote applied, reply not delivered
            return ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=(TextBlock(text="saved fast receipt"),),
            )

        async def reconcile(self, operation_id, context):
            # Recovery receives the original call via reconcile_call below.
            raise AssertionError("must use the original call")

        async def reconcile_call(self, call, context):
            if call.tool_name != "save_value":
                return ReconcileResult(
                    operation_id=call.operation_id, state=ReconcileState.UNKNOWN
                )
            return ReconcileResult(
                operation_id=call.operation_id,
                state=ReconcileState.SUCCEEDED,
                result=ToolExecutionResult(
                    tool_call_id=call.tool_call_id,
                    operation_id=call.operation_id,
                    content=(TextBlock(text="checked remote receipt"),),
                ),
            )

    def build(run_id):
        nonlocal generation
        generation += 1
        factory, descriptor = team_factory(
            tmp_path, worker_runtime, Model(tmp_path, store, team=True), crash=True
        )
        definition = DEFINITION.model_copy(
            update={"supports_reconciliation": reconcilable}
        )
        factory.base_catalog = InMemoryToolCatalog((definition,))
        factory.base_executor = Executor()
        return factory.create_loop(descriptor, run_id)

    agent = SAgent(runtime=runtime, driver_factory=build)
    dispatcher = LocalWorkerDispatcher(
        scheduler,
        max_concurrent_runs=2,
        lease_seconds=0.15,
        lease_scope_factory=fenced.lease_scope,
    )
    agent.attach_dispatcher(dispatcher)
    handle = await agent.start_run(
        StartRun(
            agent_id="root",
            idempotency_key="start",
            input=(InputItem(role="user", content=(TextBlock(text="original"),)),),
            resolved_spec_hash="sha256:restart",
        ),
        CONTEXT,
    )
    future = await dispatcher.submit(agent, handle, CONTEXT)
    try:
        await asyncio.wait_for(remote_applied.wait(), 3)
        await wait_until(lambda: (tmp_path / "fast-completed").exists())
        clock.offset += timedelta(hours=49)
        result = await asyncio.wait_for(asyncio.shield(future), 5)
        if not reconcilable:
            assert result.state == RunState.SUSPENDED
            suspension = await store.get_suspension(result.suspension_id)
            interaction = await store.get_interaction(suspension.interaction_id)
            assert interaction.payload["delegated"] is True
            receipt = await runtime.reply_interaction(
                ReplyInteraction(
                    run_id=handle.run_id,
                    suspension_id=suspension.suspension_id,
                    interaction_id=interaction.interaction_id,
                    expected_revision=result.revision,
                    expected_suspension_revision=suspension.expected_revision,
                    expected_interaction_revision=interaction.expected_revision,
                    decision="confirm_succeeded",
                    payload={"result_text": "checked remote receipt"},
                    idempotency_key="checked",
                ),
                CONTEXT,
            )
            assert receipt.decision.value == "accepted"
            resumed = await runtime.get_run(handle.run_id)
            continuation = await dispatcher.submit(agent, resumed, CONTEXT, resume=True)
            await asyncio.wait_for(asyncio.shield(continuation), 5)
            async with asyncio.timeout(5):
                while (await store.get_run(handle.run_id)).state != RunState.COMPLETED:
                    await asyncio.sleep(0.01)
        else:
            assert result.state == RunState.COMPLETED
        sessions = [
            handle.session_id,
            *[
                s.session_id
                for s in await store.list_descendant_sessions(handle.session_id)
            ],
        ]
        runs = [r for sid in sessions for r in await store.list_session_runs(sid)]
        assert len(runs) == 4
        assert all(r.state == RunState.COMPLETED for r in runs)
        assert sorted(effects) == ["fast", "slow"]
        for r in runs:
            assert not any(
                e.type == "run.failed" for e in await store.read_events(r.run_id)
            )
    finally:
        await dispatcher.close()
        await agent.close()
        await scheduler.close()
        await store.close()


@pytest.mark.asyncio
async def test_transient_renewal_failure_retries_without_restarting_driver():
    from types import SimpleNamespace
    from tests.sagents.v2.test_dispatcher_matrix import FakeAgent

    class Scheduler(RecordingScheduler):
        attempts = 0

        async def renew(self, lease, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("temporary heartbeat outage")
            return await super().renew(lease, **kwargs)

    scheduler = Scheduler()
    dispatcher = LocalWorkerDispatcher(
        scheduler, max_concurrent_runs=1, lease_seconds=0.3
    )
    try:
        future = await dispatcher.submit(
            FakeAgent(delay=0.35),
            SimpleNamespace(run_id="same-run", run_revision=0),
            CONTEXT,
        )
        assert (await asyncio.wait_for(future, 2)).state == RunState.COMPLETED
        assert scheduler.attempts >= 2
        assert len(scheduler.claimed) == 1
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_hard_kill_reclaims_a_live_48_hour_lease_immediately(tmp_path):
    import subprocess
    import sys

    source = """
import asyncio,sys
from pathlib import Path
from datetime import timedelta
from sagents.v2.runtime.execution.scheduler import FilesystemScheduler,WorkItem
from sagents.v2.contracts.common import utc_now
async def main():
 root=Path(sys.argv[1]); scheduler=FilesystemScheduler(root)
 await scheduler.submit(WorkItem(work_id="same-work",run_id="same-run",available_at=utc_now(),idempotency_key="same"))
 lease=await scheduler.claim("old",lease_duration=timedelta(hours=48))
 (root/"ready").write_text(str(lease.fencing_token))
 await asyncio.Event().wait()
asyncio.run(main())
"""
    process = subprocess.Popen([sys.executable, "-c", source, str(tmp_path)])
    try:
        await wait_until(lambda: (tmp_path / "ready").exists())
        old_token = int((tmp_path / "ready").read_text())
    finally:
        process.kill()
        await asyncio.to_thread(process.wait, 5)
    scheduler = FilesystemScheduler(tmp_path)
    try:
        lease = await scheduler.claim(
            "replacement", lease_duration=timedelta(hours=48), wait_timeout=0
        )
        assert lease is not None
        assert lease.work.work_id == "same-work"
        assert lease.work.run_id == "same-run"
        assert lease.fencing_token > old_token
    finally:
        await scheduler.close()
