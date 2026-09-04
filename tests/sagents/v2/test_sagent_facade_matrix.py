from __future__ import annotations

import asyncio

import pytest

from sagents.v2 import SAgent
from sagents.v2.agent import AgentLoopEngine
from sagents.v2.model import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ScriptedModelProvider,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
from sagents.v2.runtime.execution.scheduler import InMemoryScheduler


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


def command(key="start"):
    return StartRun(
        agent_id="agent_1",
        input=(InputItem(role="user", content=(TextBlock(text="hello"),)),),
        resolved_spec_hash="sha256:agent",
        idempotency_key=key,
    )


def completed(text="done"):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="response_1", text=text, finish_reason="stop"
        ),
    )


@pytest.mark.asyncio
async def test_run_stream_returns_handle_and_individual_canonical_events_to_terminal():
    runtime = ephemeral_runtime()

    def factory(run_id):
        return AgentLoopEngine(
            runtime=runtime,
            model=ScriptedModelProvider(
                (ScriptedModelStep(events=(completed("done"),)),)
            ),
            tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}),
        )

    stream = await SAgent(runtime=runtime, driver_factory=factory).run_stream(
        command(), CONTEXT
    )
    events = [event async for event in stream.events]
    final = await stream.wait()

    assert stream.handle.run_id == final.run_id
    assert final.state == RunState.COMPLETED
    assert events[0].type == "run.accepted"
    assert events[-1].type == "run.completed"
    assert all(not isinstance(event, list) for event in events)
    assert stream.execution is stream._execution
    assert stream.execution_done() is True


@pytest.mark.asyncio
async def test_one_application_runs_one_hundred_conversations_asynchronously():
    runtime = ephemeral_runtime()
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(
        scheduler,
        max_concurrent_runs=8,
        max_concurrent_runs_per_tenant=8,
    )
    release = asyncio.Event()
    capacity_reached = asyncio.Event()
    active = 0
    peak = 0

    class Driver:
        async def execute(self, run_id, context):
            nonlocal active, peak
            run = await runtime.get_run(run_id)
            run = await runtime.start_execution(
                run_id=run_id,
                expected_revision=run.revision,
                context=context,
                idempotency_key=f"parallel-start:{run_id}",
            )
            active += 1
            peak = max(peak, active)
            if active == 8:
                capacity_reached.set()
            try:
                await release.wait()
                return await runtime.complete_run(
                    run_id=run_id,
                    expected_revision=run.revision,
                    context=context,
                    idempotency_key=f"parallel-complete:{run_id}",
                )
            finally:
                active -= 1

        async def resume(self, run_id, context):
            raise AssertionError("not used")

    agent = SAgent(
        runtime=runtime,
        driver_factory=lambda run_id: Driver(),
        dispatcher=dispatcher,
    )
    streams = await asyncio.gather(
        *(
            agent.run_stream(
                command(f"parallel-{index}").model_copy(
                    update={"session_id": f"parallel-session-{index}"}
                ),
                CONTEXT,
            )
            for index in range(100)
        )
    )
    await asyncio.wait_for(capacity_reached.wait(), timeout=2)
    assert peak == 8
    release.set()
    snapshots = await asyncio.wait_for(
        asyncio.gather(*(stream.wait() for stream in streams)), timeout=5
    )
    assert len(snapshots) == 100
    assert all(snapshot.state == RunState.COMPLETED for snapshot in snapshots)
    assert len({snapshot.session_id for snapshot in snapshots}) == 100
    await dispatcher.close()


@pytest.mark.asyncio
async def test_detach_does_not_cancel_or_suspend_the_run():
    runtime = ephemeral_runtime()
    release = asyncio.Event()

    class Driver:
        async def execute(self, run_id, context):
            run = await runtime.get_run(run_id)
            run = await runtime.start_execution(
                run_id=run_id,
                expected_revision=run.revision,
                context=context,
                idempotency_key="execute",
            )
            await release.wait()
            return await runtime.complete_run(
                run_id=run_id,
                expected_revision=run.revision,
                context=context,
                idempotency_key="complete",
            )

        async def resume(self, run_id, context):
            raise AssertionError("not used")

    stream = await SAgent(
        runtime=runtime, driver_factory=lambda run_id: Driver()
    ).run_stream(command(), CONTEXT)
    first = await anext(stream.events)
    assert first.type == "run.accepted"
    await stream.detach()
    release.set()
    final = await stream.wait()

    assert final.state == RunState.COMPLETED
    assert (await runtime.get_run(final.run_id)).state == RunState.COMPLETED


@pytest.mark.asyncio
async def test_unhandled_driver_crash_becomes_typed_terminal_failure():
    runtime = ephemeral_runtime()

    class CrashingDriver:
        async def execute(self, run_id, context):
            raise RuntimeError("boom")

        async def resume(self, run_id, context):
            raise RuntimeError("boom")

    stream = await SAgent(
        runtime=runtime, driver_factory=lambda run_id: CrashingDriver()
    ).run_stream(command(), CONTEXT)
    events = [event async for event in stream.events]
    final = await stream.wait()

    assert final.state == RunState.FAILED
    assert events[-1].type == "run.failed"
    assert events[-1].data.error.code == "agent.driver_crashed"


@pytest.mark.asyncio
async def test_scheduler_submit_failure_is_a_durable_typed_run_failure():
    runtime = ephemeral_runtime()

    class FailingDispatcher:
        async def submit(self, agent, handle, context, *, resume=False):
            del agent, handle, context, resume
            raise RuntimeError("queue unavailable")

    agent = SAgent(
        runtime=runtime,
        driver_factory=lambda run_id: None,
        dispatcher=FailingDispatcher(),
    )
    submitted = command("scheduler-submit-failure").model_copy(
        update={"session_id": "session_scheduler_submit_failure"}
    )
    with pytest.raises(RuntimeError, match="queue unavailable"):
        await agent.start_run(submitted, CONTEXT)

    runs = await runtime.session_store.list_session_runs(submitted.session_id)
    assert len(runs) == 1
    assert runs[0].state == RunState.FAILED
    result = await runtime.session_store.get_run_result(runs[0].run_id)
    assert result.error is not None
    assert result.error.code == "scheduler.submit_failed"


@pytest.mark.asyncio
async def test_exact_terminal_start_retry_does_not_resubmit_scheduler_work():
    runtime = ephemeral_runtime()
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    factory_calls = 0

    def factory(run_id):
        nonlocal factory_calls
        factory_calls += 1
        return AgentLoopEngine(
            runtime=runtime,
            model=ScriptedModelProvider(
                (ScriptedModelStep(events=(completed("done"),)),)
            ),
            tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}),
        )

    agent = SAgent(
        runtime=runtime,
        driver_factory=factory,
        dispatcher=dispatcher,
    )
    request = command("stable-retry")
    run_ids = []
    for _ in range(4):
        stream = await agent.run_stream(request, CONTEXT)
        run_ids.append(stream.handle.run_id)
        assert (await stream.wait()).state == RunState.COMPLETED
        await asyncio.sleep(0)

    assert len(set(run_ids)) == 1
    assert factory_calls == 1
    await dispatcher.close()


@pytest.mark.asyncio
async def test_completed_execution_is_removed_from_facade_task_registry():
    runtime = ephemeral_runtime()

    def factory(run_id):
        return AgentLoopEngine(
            runtime=runtime,
            model=ScriptedModelProvider(
                (ScriptedModelStep(events=(completed("done"),)),)
            ),
            tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}),
        )

    agent = SAgent(runtime=runtime, driver_factory=factory)
    stream = await agent.run_stream(command(), CONTEXT)
    assert (await stream.wait()).state == RunState.COMPLETED
    await asyncio.sleep(0)
    assert agent._tasks == {}


@pytest.mark.asyncio
async def test_close_failure_can_retry_without_reclosing_successful_resources():
    calls = []

    class Resource:
        def __init__(self, name, *, fail_once=False):
            self.name = name
            self.fail_once = fail_once

        async def close(self):
            calls.append(self.name)
            if self.fail_once:
                self.fail_once = False
                raise OSError("temporarily unavailable")

    transient = Resource("transient", fail_once=True)
    stable = Resource("stable")
    agent = SAgent(
        runtime=ephemeral_runtime(),
        driver_factory=lambda run_id: None,
        owned_resources=(transient, stable),
    )

    with pytest.raises(RuntimeError, match="failed to close"):
        await agent.close()
    with pytest.raises(SageV2Error) as closing:
        await agent.start_run(command("after-close-failure"), CONTEXT)
    assert closing.value.info.code == "agent.closing"
    await agent.close()

    assert calls == ["stable", "transient", "transient"]


@pytest.mark.asyncio
async def test_terminal_driver_cleanup_failure_does_not_replace_completed_result():
    runtime = ephemeral_runtime()

    class CleanupFailureDriver:
        def __init__(self):
            self.close_calls = 0

        async def execute(self, run_id, context):
            run = await runtime.get_run(run_id)
            run = await runtime.start_execution(
                run_id=run_id,
                expected_revision=run.revision,
                context=context,
                idempotency_key="execute-cleanup-failure",
            )
            return await runtime.complete_run(
                run_id=run_id,
                expected_revision=run.revision,
                context=context,
                idempotency_key="complete-cleanup-failure",
            )

        async def resume(self, run_id, context):
            raise AssertionError("not used")

        async def close(self):
            self.close_calls += 1
            if self.close_calls == 1:
                raise OSError("cleanup unavailable")

    driver = CleanupFailureDriver()
    agent = SAgent(
        runtime=runtime,
        driver_factory=lambda run_id: driver,
    )
    stream = await agent.run_stream(command("cleanup-failure"), CONTEXT)

    result = await stream.wait()

    assert result.state == RunState.COMPLETED
    assert (await runtime.get_run(result.run_id)).state == RunState.COMPLETED
    assert agent._drivers == {result.run_id: driver}
    await agent.close()
    assert agent._drivers == {}
    assert driver.close_calls == 2


@pytest.mark.asyncio
async def test_stream_closes_at_suspension_so_a_client_can_resume_by_cursor():
    runtime = ephemeral_runtime()

    class SuspendingDriver:
        async def execute(self, run_id, context):
            run = await runtime.get_run(run_id)
            run = await runtime.start_execution(
                run_id=run_id,
                expected_revision=run.revision,
                context=context,
                idempotency_key="execute",
            )
            from sagents.v2.agent.state import AgentLoopCheckpointState
            from sagents.v2.contracts.checkpoint import (
                Checkpoint,
                Suspension,
                SuspensionReason,
            )
            from sagents.v2.contracts.common import new_id, utc_now

            checkpoint = Checkpoint(
                checkpoint_id=new_id("checkpoint"),
                checkpoint_codec_version="test/1",
                session_id=run.session_id,
                run_id=run_id,
                run_sequence=run.last_run_sequence,
                session_revision=run.accepted_session_revision,
                state=AgentLoopCheckpointState(
                    turn_id="turn_1", step_number=1, messages=()
                ).model_dump(mode="json"),
                resolved_spec_hash=run.resolved_spec_hash,
                created_at=utc_now(),
            )
            suspension = Suspension(
                suspension_id=new_id("suspension"),
                run_id=run_id,
                reason=SuspensionReason.MANUAL_PAUSE,
                blocking_scope="run",
                checkpoint_id=checkpoint.checkpoint_id,
                checkpoint_sequence=run.last_run_sequence,
                resume_policy="explicit_resume",
                requested_at=utc_now(),
            )
            return await runtime.commit_suspension(
                run_id=run_id,
                expected_revision=run.revision,
                checkpoint=checkpoint,
                suspension=suspension,
                context=context,
                idempotency_key="suspend",
            )

        async def resume(self, run_id, context):
            raise AssertionError("not used")

    stream = await SAgent(
        runtime=runtime, driver_factory=lambda run_id: SuspendingDriver()
    ).run_stream(command(), CONTEXT)
    events = [event async for event in stream.events]

    assert events[-1].type == "run.suspended"
    assert (await stream.wait()).state == RunState.SUSPENDED
