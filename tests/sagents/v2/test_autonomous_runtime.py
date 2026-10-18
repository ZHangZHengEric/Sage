"""Scheduled recovery releases capacity and survives process resource rebuilds."""
from __future__ import annotations

import asyncio

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.state import AgentLoopCheckpointCodec
from sagents.v2.agent.policy.tool_policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.contracts.commands import CancelRun, InputItem, RunConfig, StartRun
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model import ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
from sagents.v2.runtime.execution.scheduler import FilesystemScheduler, InMemoryScheduler
from sagents.v2.runtime.session import EphemeralSessionStore, FilesystemSessionStore
from sagents.v2.sagent import SAgent
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider, ScriptedModelStep
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor, SideEffectLevel, ToolDefinition, ToolExecutionResult

CONTEXT = RequestContext(actor=ActorRef(
    principal_id="autonomous", principal_type=PrincipalType.USER, tenant_id="one-tenant",
))
ERROR = RuntimeErrorInfo(
    code="model.provider_transient", category=ErrorCategory.PROVIDER_TRANSIENT,
    message="network offline", retryable=True,
)
TOOL = ToolDefinition(name="save", description="Save", input_schema={"type": "object"}, side_effect_level=SideEffectLevel.WRITE)


def completed(text="done", calls=()):
    return ScriptedModelStep(events=(ModelStreamEvent(kind="completed", response=ModelResponse(
        response_id="response", text=text, tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
    )),))


def command(key, **config):
    return StartRun(
        agent_id="agent", input=(InputItem(role="user", content=(TextBlock(text=key),)),),
        config=RunConfig(**config), resolved_spec_hash="sha256:autonomous", idempotency_key=key,
    )


def facade(runtime, models, writes=None):
    async def save(call, context):
        if writes is not None:
            writes.append(call.operation_id)
        return ToolExecutionResult(tool_call_id=call.tool_call_id, operation_id=call.operation_id, content=(TextBlock(text="saved"),))

    def factory(run_id):
        return AgentLoopEngine(
            runtime=runtime, model=models[run_id], tool_catalog=InMemoryToolCatalog((TOOL,)),
            tool_executor=InMemoryToolExecutor({"save": TOOL}, {"save": save}),
            tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
        )
    return SAgent(runtime=runtime, driver_factory=factory)


async def wait_for_deferred(runtime, run_id):
    async def ready():
        while True:
            events = await runtime.session_store.read_events(run_id)
            if any(e.type == "step.retry_scheduled" for e in events):
                return await runtime.session_store.get_latest_checkpoint(run_id)
            await asyncio.sleep(0.005)
    return await asyncio.wait_for(ready(), 2)


@pytest.mark.asyncio
async def test_outage_releases_the_only_worker_and_tenant_slot(monkeypatch):
    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0.3)
    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1, max_concurrent_runs_per_tenant=1)
    first = await runtime.start_run(command("offline"), CONTEXT)
    second = await runtime.start_run(command("other"), CONTEXT)
    models = {
        first.run_id: ScriptedModelProvider((ScriptedModelStep(events=(), error=ERROR), completed())),
        second.run_id: ScriptedModelProvider((completed(),)),
    }
    agent = facade(runtime, models)
    dispatcher.attach_recovery_agent(agent)
    try:
        first_result = await dispatcher.submit(agent, first, CONTEXT)
        await wait_for_deferred(runtime, first.run_id)
        second_result = await dispatcher.submit(agent, second, CONTEXT)
        assert (await asyncio.wait_for(second_result, 0.2)).state == RunState.COMPLETED
        assert not first_result.done()
        assert (await asyncio.wait_for(first_result, 2)).state == RunState.COMPLETED
        assert len(models[first.run_id].requests) == 2
        assert not [e for e in await runtime.session_store.read_events(first.run_id) if e.type == "interaction.requested"]
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_stage_rollover_keeps_completed_writes_and_continues_without_approval():
    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("stages", max_steps=1), CONTEXT)
    model = ScriptedModelProvider((
        completed("", (ModelToolCall(tool_call_id="first", name="save", arguments={}),)),
        completed("", (ModelToolCall(tool_call_id="second", name="save", arguments={}),)),
        completed("all stages done"),
    ))
    writes = []
    agent = facade(runtime, {handle.run_id: model}, writes)
    dispatcher.attach_recovery_agent(agent)
    try:
        future = await dispatcher.submit(agent, handle, CONTEXT)
        assert (await asyncio.wait_for(future, 2)).state == RunState.COMPLETED
        assert len(writes) == 2 and len(set(writes)) == 2
        checkpoint = await runtime.session_store.get_latest_checkpoint(handle.run_id)
        assert AgentLoopCheckpointCodec.decode(checkpoint.state).stage_number == 3
        events = await runtime.session_store.read_events(handle.run_id)
        assert len([e for e in events if e.type == "step.retry_scheduled" and e.data.state == "stage_scheduled"]) == 2
        assert not [e for e in events if e.type == "interaction.requested"]
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_graceful_shutdown_preserves_delayed_run_and_restart_recovers(monkeypatch, tmp_path):
    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0.4)
    store = FilesystemSessionStore(tmp_path / "sessions")
    runtime = HarnessRuntime(store)
    scheduler = FilesystemScheduler(tmp_path / "scheduler")
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("restart"), CONTEXT)
    agent = facade(runtime, {handle.run_id: ScriptedModelProvider((ScriptedModelStep(events=(), error=ERROR),))})
    dispatcher.attach_recovery_agent(agent)
    future = await dispatcher.submit(agent, handle, CONTEXT)
    checkpoint = await wait_for_deferred(runtime, handle.run_id)
    due = AgentLoopCheckpointCodec.decode(checkpoint.state).automatic_resume_at
    await dispatcher.close()
    assert (await future).state == RunState.RUNNING
    assert (await runtime.get_run(handle.run_id)).state == RunState.RUNNING
    await scheduler.close()
    await store.close()

    restored_store = FilesystemSessionStore(tmp_path / "sessions")
    restored_runtime = HarnessRuntime(restored_store)
    restored_scheduler = FilesystemScheduler(tmp_path / "scheduler")
    restored = LocalWorkerDispatcher(restored_scheduler, max_concurrent_runs=1)
    model = ScriptedModelProvider((completed("recovered"),))
    restored.attach_recovery_agent(facade(restored_runtime, {handle.run_id: model}))
    try:
        await restored.start()
        # Starting the dispatcher is sufficient; no user resume command.
        async def settled():
            while (run := await restored_runtime.get_run(handle.run_id)).state != RunState.COMPLETED:
                await asyncio.sleep(0.01)
            return run
        result = await asyncio.wait_for(settled(), 2)
        assert result.updated_at >= due
        assert len(model.requests) == 1
        assert not [e for e in await restored_store.read_events(handle.run_id) if e.type == "run.failed"]
    finally:
        await restored.close()
        await restored_scheduler.close()
        await restored_store.close()


@pytest.mark.asyncio
async def test_team_child_outage_releases_root_worker_and_preserves_siblings(monkeypatch):
    from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
    from sagents.v2.agent.multi_agent import AgentDescriptor, AgentMode, AgentRegistry

    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0.4)
    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1, max_concurrent_runs_per_tenant=1)
    root = await runtime.start_run(command("team"), CONTEXT)
    other = await runtime.start_run(command("other"), CONTEXT)
    models = {
        "root": ScriptedModelProvider((completed("", (ModelToolCall(
            tool_call_id="delegate", name="sys_team_delegate_task", arguments={"tasks": [
                {"agent_id": "fast", "content": "save"}, {"agent_id": "slow", "content": "save"},
            ]},
        ),)), completed("team done"))),
        "fast": ScriptedModelProvider((completed("", (ModelToolCall(tool_call_id="save-fast", name="save", arguments={}),)), completed())),
        "slow": ScriptedModelProvider((ScriptedModelStep(events=(), error=ERROR), completed("", (ModelToolCall(tool_call_id="save-slow", name="save", arguments={}),)), completed())),
        "other": ScriptedModelProvider((completed(),)),
    }
    writes = []
    descriptors = {name: AgentDescriptor(
        agent_id=name, name=name, description=name, instructions="Complete the task",
        mode=AgentMode.TEAM if name == "root" else AgentMode.SIMPLE, tools=("save",),
    ) for name in ("root", "fast", "slow")}

    async def save(call, context):
        name = (await runtime.session_store.get_start_command(call.owner_run_id)).agent_id
        writes.append(name)
        return ToolExecutionResult(tool_call_id=call.tool_call_id, operation_id=call.operation_id, content=(TextBlock(text="saved"),))

    def build(run_id):
        def compose(descriptor, run_id, catalog, executor):
            return AgentLoopEngine(
                runtime=runtime, model=models[descriptor.agent_id], tool_catalog=catalog, tool_executor=executor,
                tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
            )
        factory = ModeAwareAgentLoopFactory(
            runtime=runtime, model_factory=lambda descriptor, _: models[descriptor.agent_id],
            base_catalog=InMemoryToolCatalog((TOOL,)), base_executor=InMemoryToolExecutor({"save": TOOL}, {"save": save}),
            registry=AgentRegistry(tuple(descriptors.values())), resolved_spec_hash="sha256:autonomous", loop_composer=compose,
        )
        return factory.create_loop(descriptors["root"], run_id)

    agent = SAgent(runtime=runtime, driver_factory=build)
    other_agent = facade(runtime, {other.run_id: models["other"]})
    dispatcher.attach_recovery_agent(agent)
    try:
        result = await dispatcher.submit(agent, root, CONTEXT)
        checkpoint = await wait_for_deferred(runtime, root.run_id)
        assert checkpoint.state["automatic_resume_reason"] == "delegation.wait"
        other_result = await dispatcher.submit(other_agent, other, CONTEXT)
        assert (await asyncio.wait_for(other_result, 0.25)).state == RunState.COMPLETED
        assert not result.done()
        assert (await asyncio.wait_for(result, 3)).state == RunState.COMPLETED
        assert sorted(writes) == ["fast", "slow"]
        sessions = await runtime.session_store.list_descendant_sessions(root.session_id)
        assert len(sessions) == 2
        assert len(models["fast"].requests) == 2
        assert len(models["slow"].requests) == 3
        assert not [e for e in await runtime.session_store.read_events(root.run_id) if e.type == "interaction.requested"]
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_cancel_during_scheduled_wait_settles_caller_without_retry(monkeypatch):
    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 60)
    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("cancel"), CONTEXT)
    model = ScriptedModelProvider((ScriptedModelStep(events=(), error=ERROR),))
    agent = facade(runtime, {handle.run_id: model})
    try:
        future = await dispatcher.submit(agent, handle, CONTEXT)
        await wait_for_deferred(runtime, handle.run_id)
        run = await runtime.get_run(handle.run_id)
        await runtime.cancel_run(CancelRun(
            run_id=run.run_id, expected_revision=run.revision, idempotency_key="user-cancel",
        ), CONTEXT)
        assert (await asyncio.wait_for(future, 2)).state == RunState.CANCELLED
        assert len(model.requests) == 1
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_pause_interrupts_a_scheduled_wait_without_waiting_for_retry(monkeypatch):
    from sagents.v2.contracts.commands import PauseRun

    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 60)
    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("pause"), CONTEXT)
    model = ScriptedModelProvider((ScriptedModelStep(events=(), error=ERROR),))
    agent = facade(runtime, {handle.run_id: model})
    dispatcher.attach_recovery_agent(agent)
    try:
        future = await dispatcher.submit(agent, handle, CONTEXT)
        await wait_for_deferred(runtime, handle.run_id)
        run = await runtime.get_run(handle.run_id)
        await runtime.pause_run(PauseRun(
            run_id=run.run_id, expected_revision=run.revision, idempotency_key="user-pause",
        ), CONTEXT)
        assert (await asyncio.wait_for(future, 3)).state == RunState.SUSPENDED
        assert len(model.requests) == 1
    finally:
        await dispatcher.close()
        await scheduler.close()


_COLD_WORKER = r'''
import asyncio, json, sys
from pathlib import Path
from tests.sagents.v2.test_autonomous_runtime import *

async def main():
    root, boundary = Path(sys.argv[1]), sys.argv[2]
    store = FilesystemSessionStore(root / "sessions")
    runtime = HarnessRuntime(store)
    scheduler = FilesystemScheduler(root / "scheduler")
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("cold", max_steps=1), CONTEXT)
    (root / "identity.json").write_text(json.dumps({"run_id": handle.run_id}))
    steps = (ScriptedModelStep(events=(), error=ERROR),) if boundary == "network" else (
        completed("", (ModelToolCall(tool_call_id="once", name="save", arguments={}),)),
    )
    model = ScriptedModelProvider(steps)
    class CrashLoop(AgentLoopEngine):
        _PROVIDER_RETRY_BASE_SECONDS = 0.8
        async def _commit_running(self, run, context, drafts, **kwargs):
            result = await super()._commit_running(run, context, drafts, **kwargs)
            state = kwargs.get("recovery_state")
            if state and state.automatic_resume_at:
                (root / "ready").write_text("checkpoint saved before scheduler release")
                await asyncio.Event().wait()
            return result
    async def save(call, context):
        with (root / "effect").open("a") as output:
            output.write("saved\n")
            output.flush()
            import os; os.fsync(output.fileno())
        return ToolExecutionResult(tool_call_id=call.tool_call_id, operation_id=call.operation_id, content=(TextBlock(text="saved"),))
    agent = SAgent(runtime=runtime, driver_factory=lambda _: CrashLoop(
        runtime=runtime, model=model, tool_catalog=InMemoryToolCatalog((TOOL,)),
        tool_executor=InMemoryToolExecutor({"save": TOOL}, {"save": save}),
        tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE),
    ))
    await (await dispatcher.submit(agent, handle, CONTEXT))
asyncio.run(main())
'''


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["network", "stage"])
async def test_hard_kill_after_checkpoint_before_lease_release_recovers(tmp_path, boundary):
    import json
    import sys

    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", _COLD_WORKER, str(tmp_path), boundary,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    try:
        async def ready():
            while not (tmp_path / "ready").exists():
                if process.returncode is not None:
                    raise AssertionError((await process.stderr.read()).decode())
                await asyncio.sleep(0.01)
        await asyncio.wait_for(ready(), 10)
        process.kill()
        await asyncio.wait_for(process.wait(), 2)
        run_id = json.loads((tmp_path / "identity.json").read_text())["run_id"]
        store = FilesystemSessionStore(tmp_path / "sessions")
        scheduler = FilesystemScheduler(tmp_path / "scheduler")
        runtime = HarnessRuntime(store)
        dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
        model = ScriptedModelProvider((completed("recovered"),))
        writes = []
        dispatcher.attach_recovery_agent(facade(runtime, {run_id: model}, writes))
        try:
            checkpoint = await store.get_latest_checkpoint(run_id)
            due = AgentLoopCheckpointCodec.decode(checkpoint.state).automatic_resume_at
            await dispatcher.start()
            async def settled():
                while (run := await runtime.get_run(run_id)).state != RunState.COMPLETED:
                    assert run.state != RunState.FAILED
                    await asyncio.sleep(0.01)
                return run
            result = await asyncio.wait_for(settled(), 5)
            assert result.updated_at >= due
            assert not writes
            assert len(model.requests) == 1
            if boundary == "stage":
                assert (tmp_path / "effect").read_text() == "saved\n"
                assert any(m.role == "tool" for m in model.requests[0].messages)
        finally:
            await dispatcher.close()
            await scheduler.close()
            await store.close()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


@pytest.mark.asyncio
async def test_explicit_stage_limit_still_requests_a_decision():
    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("bounded-stage", max_steps=1, max_stages=1), CONTEXT)
    writes = []
    model = ScriptedModelProvider((completed("", (
        ModelToolCall(tool_call_id="only", name="save", arguments={}),
    )),))
    agent = facade(runtime, {handle.run_id: model}, writes)
    try:
        future = await dispatcher.submit(agent, handle, CONTEXT)
        assert (await asyncio.wait_for(future, 2)).state == RunState.SUSPENDED
        assert len(writes) == 1
        assert len(model.requests) == 1
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_explicit_deadline_wakes_scheduled_retry_and_is_not_bypassed(monkeypatch):
    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 60)
    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("deadline", deadline_seconds=0.1), CONTEXT)
    model = ScriptedModelProvider((ScriptedModelStep(events=(), error=ERROR),))
    agent = facade(runtime, {handle.run_id: model})
    try:
        future = await dispatcher.submit(agent, handle, CONTEXT)
        run = await asyncio.wait_for(future, 2)
        assert run.state == RunState.SUSPENDED
        suspension = await runtime.session_store.get_suspension(run.suspension_id)
        interaction = await runtime.session_store.get_interaction(suspension.interaction_id)
        assert interaction.payload["reason_code"] == "budget.deadline"
        assert len(model.requests) == 1
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_initial_tool_selection_outage_retries_without_user_input(monkeypatch):
    from sagents.v2.contracts.errors import SageV2Error
    from sagents.v2.tool.plugins.selection_recent import RecentToolSelectionPolicy

    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0.01)
    class Selection(RecentToolSelectionPolicy):
        attempts = 0
        async def prepare(self, context):
            self.attempts += 1
            if self.attempts <= 2:
                raise SageV2Error(ERROR)
            await super().prepare(context)

    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("initial-selection"), CONTEXT)
    model = ScriptedModelProvider((completed(),))
    selection = Selection()
    agent = SAgent(runtime=runtime, driver_factory=lambda _: AgentLoopEngine(
        runtime=runtime, model=model, tool_catalog=InMemoryToolCatalog(()),
        tool_executor=InMemoryToolExecutor({}, {}), tool_selection_policy=selection,
    ))
    try:
        future = await dispatcher.submit(agent, handle, CONTEXT)
        assert (await asyncio.wait_for(future, 2)).state == RunState.COMPLETED
        assert selection.attempts == 3
        assert len(model.requests) == 1
        assert not [e for e in await runtime.session_store.read_events(handle.run_id) if e.type == "interaction.requested"]
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_recoverable_environment_error_defers_again_instead_of_failing_run(monkeypatch):
    from sagents.v2.contracts.errors import SageV2Error

    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0.01)
    runtime = HarnessRuntime(EphemeralSessionStore())
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    handle = await runtime.start_run(command("environment"), CONTEXT)
    model = ScriptedModelProvider((ScriptedModelStep(events=(), error=ERROR), completed()))
    agent = facade(runtime, {handle.run_id: model})
    original = agent.recover_interrupted_run
    attempts = 0
    async def restore(run_id, context):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise SageV2Error(RuntimeErrorInfo(
                code="sandbox.restore_failed", category=ErrorCategory.RESOURCE_LOST,
                message="temporary resource outage", retryable=True, safe_to_resume=True,
            ))
        return await original(run_id, context)
    monkeypatch.setattr(agent, "recover_interrupted_run", restore)
    try:
        result = await dispatcher.submit(agent, handle, CONTEXT)
        assert (await asyncio.wait_for(result, 4)).state == RunState.COMPLETED
        assert attempts == 2
        assert not [e for e in await runtime.session_store.read_events(handle.run_id) if e.type in {"run.failed", "interaction.requested"}]
    finally:
        await dispatcher.close()
        await scheduler.close()


@pytest.mark.asyncio
async def test_cancelling_worker_drains_atomic_scheduler_release():
    from datetime import timedelta
    from sagents.v2.contracts.common import utc_now
    from sagents.v2.runtime.execution.scheduler import LeaseReleaseReason, WorkItem

    class SlowReleaseScheduler(InMemoryScheduler):
        def __init__(self):
            super().__init__()
            self.entered = asyncio.Event()
            self.allow = asyncio.Event()
        async def release(self, *args, **kwargs):
            self.entered.set()
            await self.allow.wait()
            await super().release(*args, **kwargs)

    scheduler = SlowReleaseScheduler()
    await scheduler.submit(WorkItem(
        work_id="work", run_id="run", available_at=utc_now(), idempotency_key="one",
    ))
    lease = await scheduler.claim("worker", lease_duration=timedelta(seconds=60), wait_timeout=0)
    dispatcher = LocalWorkerDispatcher(scheduler)
    release = asyncio.create_task(dispatcher._release_lease(
        lease, LeaseReleaseReason.DEFERRED, requeue=True, available_at=utc_now() + timedelta(seconds=60),
    ))
    await scheduler.entered.wait()
    release.cancel()
    await asyncio.sleep(0)
    assert not release.done()
    scheduler.allow.set()
    with pytest.raises(asyncio.CancelledError):
        await release
    assert await scheduler.pending_count() == 1
    await dispatcher.close()
    await scheduler.close()
