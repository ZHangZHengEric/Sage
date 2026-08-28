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
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime import HarnessRuntime


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
    runtime = HarnessRuntime()

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


@pytest.mark.asyncio
async def test_detach_does_not_cancel_or_suspend_the_run():
    runtime = HarnessRuntime()
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
    runtime = HarnessRuntime()

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
async def test_completed_execution_is_removed_from_facade_task_registry():
    runtime = HarnessRuntime()

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
async def test_stream_closes_at_suspension_so_a_client_can_resume_by_cursor():
    runtime = HarnessRuntime()

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
