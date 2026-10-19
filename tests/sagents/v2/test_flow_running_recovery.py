"""Running Flow cursors and branch receipts survive driver/store replacement."""

import asyncio

import pytest

from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import RunState
from sagents.v2.flow import FlowRuntime
from sagents.v2.flow.contracts import FlowExecutionState
from sagents.v2.package.manifest.flows import FlowDefinition, FlowEdge, FlowNode
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import FilesystemSessionStore
from tests.sagents.v2.test_flow_runtime_matrix import CONTEXT, FakeNode, sequential_flow


async def start(store):
    runtime = HarnessRuntime(store)
    handle = await runtime.start_run(
        StartRun(
            agent_id="flow",
            input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            resolved_spec_hash="sha256:flow",
            idempotency_key="flow",
        ),
        CONTEXT,
    )
    return runtime, handle


async def stop_worker(task):
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["during_next_node", "before_edge"])
async def test_sequential_flow_recovers_saved_results_without_repeating_completed_node(
    tmp_path, boundary
):
    store = FilesystemSessionStore(tmp_path)
    runtime, handle = await start(store)
    ready = asyncio.Event()
    identities = []
    inspector = FakeNode({"finding": "saved"})

    class WaitingNode:
        async def run(self, context):
            identities.append(context.node_execution_id)
            ready.set()
            await asyncio.Event().wait()

    class CrashFlow(FlowRuntime):
        async def _advance_node(self, run, state, context):
            if boundary == "before_edge":
                ready.set()
                await asyncio.Event().wait()
            return await super()._advance_node(run, state, context)

    flow = sequential_flow()
    engine = CrashFlow(
        runtime=runtime,
        flows={"main": flow},
        agent_nodes={"inspector": inspector, "verifier": WaitingNode()},
    )
    worker = asyncio.create_task(engine.execute(handle.run_id, "main", CONTEXT))
    await asyncio.wait_for(ready.wait(), 10)
    await stop_worker(worker)
    await store.close()
    restored_store = FilesystemSessionStore(tmp_path)
    restored_runtime = HarnessRuntime(restored_store)
    verifier = FakeNode({"verified": True})
    restored = FlowRuntime(
        runtime=restored_runtime,
        flows={"main": flow},
        agent_nodes={"inspector": inspector, "verifier": verifier},
    )
    try:
        result = await restored.recover_interrupted(handle.run_id, CONTEXT)
        assert result.state == RunState.COMPLETED
        assert len(inspector.calls) == len(verifier.calls) == 1
        assert verifier.calls[0].prior_results == {"inspect": {"finding": "saved"}}
        if identities:
            assert verifier.calls[0].node_execution_id == identities[0]
    finally:
        await restored_store.close()


@pytest.mark.asyncio
async def test_parallel_flow_recovers_only_unfinished_branches(tmp_path):
    store = FilesystemSessionStore(tmp_path)
    runtime, handle = await start(store)
    waiting = asyncio.Event()
    fast = FakeNode({"saved": True})

    class Slow:
        async def run(self, context):
            waiting.set()
            await asyncio.Event().wait()

    flow = FlowDefinition(
        version="1",
        start="batch",
        nodes=(
            FlowNode(
                id="batch", type="parallel", config={"branches": ["fast", "slow"]}
            ),
            FlowNode(id="fast", type="agent", agent="fast"),
            FlowNode(id="slow", type="agent", agent="slow"),
        ),
        edges=(FlowEdge(**{"from": "batch", "to": "end"}),),
    )
    engine = FlowRuntime(
        runtime=runtime,
        flows={"main": flow},
        agent_nodes={"fast": fast, "slow": Slow()},
    )
    worker = asyncio.create_task(engine.execute(handle.run_id, "main", CONTEXT))
    await asyncio.wait_for(waiting.wait(), 10)

    async def saved():
        while True:
            checkpoint = await store.get_latest_checkpoint(handle.run_id)
            branches = checkpoint.state.get("pending_parallel", {}).get("branches", [])
            if any(
                branch["node_id"] == "fast" and branch["outcome"] == "completed"
                for branch in branches
            ):
                return
            await asyncio.sleep(0.01)

    await asyncio.wait_for(saved(), 10)
    await stop_worker(worker)
    await store.close()
    restored_store = FilesystemSessionStore(tmp_path)
    slow = FakeNode({"recovered": True})
    engine = FlowRuntime(
        runtime=HarnessRuntime(restored_store),
        flows={"main": flow},
        agent_nodes={"fast": fast, "slow": slow},
    )
    try:
        assert (
            await engine.recover_interrupted(handle.run_id, CONTEXT)
        ).state == RunState.COMPLETED
        assert len(fast.calls) == len(slow.calls) == 1
    finally:
        await restored_store.close()


@pytest.mark.asyncio
async def test_flow_does_not_replay_a_tool_with_unknown_side_effect(tmp_path):
    store = FilesystemSessionStore(tmp_path)
    runtime, handle = await start(store)
    applied = asyncio.Event()
    calls = []

    class Tool:
        async def run(self, context):
            calls.append(context.node_execution_id)
            applied.set()
            await asyncio.Event().wait()

    flow = FlowDefinition(
        version="1",
        start="write",
        nodes=(FlowNode(id="write", type="tool", tool="write"),),
        edges=(FlowEdge(**{"from": "write", "to": "end"}),),
    )
    engine = FlowRuntime(
        runtime=runtime,
        flows={"main": flow},
        agent_nodes={},
        tool_nodes={"write": Tool()},
    )
    worker = asyncio.create_task(engine.execute(handle.run_id, "main", CONTEXT))
    await asyncio.wait_for(applied.wait(), 10)
    await stop_worker(worker)
    restored = FlowRuntime(
        runtime=runtime,
        flows={"main": flow},
        agent_nodes={},
        tool_nodes={"write": Tool()},
    )
    try:
        assert (
            await restored.recover_interrupted(handle.run_id, CONTEXT)
        ).state == RunState.SUSPENDED
        assert len(calls) == 1
        checkpoint = await store.get_latest_checkpoint(handle.run_id)
        assert checkpoint.state["pending_error"]["code"] == "flow.tool_outcome_unknown"
        changed = flow.model_copy(update={"version": "2"})
        with pytest.raises(SageV2Error, match="changed graph"):
            state = FlowExecutionState.model_validate(checkpoint.state)
            FlowRuntime(
                runtime=runtime, flows={"main": changed}, agent_nodes={}
            )._validate_definition(state)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_native_flow_defers_child_outage_and_releases_the_only_worker(
    monkeypatch,
):
    from sagents.v2.agent import AgentLoopEngine
    from sagents.v2.agent.multi_agent import AgentDescriptor
    from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor
    from sagents.v2.flow.driver import AgentFlowDriver
    from sagents.v2.flow.plugins.agent import NativeAgentFlowNode
    from sagents.v2.runtime.execution.dispatcher import LocalWorkerDispatcher
    from sagents.v2.runtime.execution.scheduler import InMemoryScheduler
    from sagents.v2.runtime.session import EphemeralSessionStore
    from sagents.v2.sagent import SAgent
    from sagents.v2.testing.plugins.scripted_model import (
        ScriptedModelProvider,
        ScriptedModelStep,
    )
    from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor
    from tests.sagents.v2.test_autonomous_runtime import ERROR, completed

    monkeypatch.setattr(AgentLoopEngine, "_PROVIDER_RETRY_BASE_SECONDS", 0.5)
    store = EphemeralSessionStore()
    runtime, root = await start(store)
    other = await runtime.start_run(
        StartRun(
            agent_id="other",
            input=(InputItem(role="user", content=(TextBlock(text="other"),)),),
            resolved_spec_hash="sha256:flow",
            idempotency_key="other",
        ),
        CONTEXT,
    )
    model = ScriptedModelProvider(
        (ScriptedModelStep(events=(), error=ERROR), completed())
    )
    other_model = ScriptedModelProvider((completed(),))

    def loop(provider):
        return AgentLoopEngine(
            runtime=runtime,
            model=provider,
            tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}),
        )

    executor = LoopChildRunExecutor(
        runtime=runtime,
        loop_factory=lambda *_: loop(model),
        resolved_spec_hash="sha256:flow",
    )
    native = NativeAgentFlowNode(
        runtime=runtime,
        descriptor=AgentDescriptor(
            agent_id="worker", name="worker", description="worker", instructions="work"
        ),
        child_executor=executor,
    )
    flow = FlowDefinition(
        version="1",
        start="work",
        nodes=(FlowNode(id="work", type="agent", agent="worker"),),
        edges=(FlowEdge(**{"from": "work", "to": "end"}),),
    )
    engine = FlowRuntime(
        runtime=runtime, flows={"main": flow}, agent_nodes={"worker": native}
    )
    agent = SAgent._from_composition(
        runtime=runtime,
        driver_factory=lambda run_id: (
            AgentFlowDriver(engine, "main", executor)
            if run_id == root.run_id
            else loop(other_model)
        ),
    )
    scheduler = InMemoryScheduler()
    dispatcher = LocalWorkerDispatcher(scheduler, max_concurrent_runs=1)
    dispatcher.attach_recovery_agent(agent)
    try:
        root_result = await dispatcher.submit(agent, root, CONTEXT)
        other_result = await dispatcher.submit(agent, other, CONTEXT)
        other_run = await asyncio.wait_for(other_result, 15)
        root_run = await asyncio.wait_for(root_result, 15)
        assert other_run.state == root_run.state == RunState.COMPLETED
        assert other_run.updated_at <= root_run.updated_at
        assert len(model.requests) == 2
        events = await store.read_events(root.run_id)
        assert not any(event.type == "interaction.requested" for event in events)
        checkpoints = [
            event for event in events if event.type == "checkpoint.committed"
        ]
        snapshots = [
            await store.get_checkpoint(event.data.checkpoint_id)
            for event in checkpoints
        ]
        assert any(
            checkpoint.state.get("automatic_resume_at") for checkpoint in snapshots
        )
    finally:
        await dispatcher.close()
        await agent.close()
        await scheduler.close()


_NATIVE_FLOW_WORKER = r"""
import asyncio, json, os, sys
from pathlib import Path
from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.multi_agent import AgentDescriptor
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor
from sagents.v2.agent.policy.tool_policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.flow import FlowRuntime
from sagents.v2.flow.plugins.agent import NativeAgentFlowNode
from sagents.v2.model import ModelCapabilities, ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.package.manifest.flows import FlowDefinition, FlowEdge, FlowNode
from sagents.v2.tool import InMemoryToolCatalog, InMemoryToolExecutor, ToolDefinition, ToolExecutionResult
from sagents.v2.contracts.items import TextBlock
from tests.sagents.v2.test_flow_running_recovery import start, CONTEXT

async def main():
    root, mode = Path(sys.argv[1]), sys.argv[2]
    store = FilesystemSessionStore(root / "sessions")
    runtime = HarnessRuntime(store)
    if mode == "crash":
        runtime, handle = await start(store)
        run_id = handle.run_id
        (root / "identity").write_text(run_id)
    else:
        run_id = (root / "identity").read_text()
    tool = ToolDefinition(name="save", description="save", input_schema={"type":"object"}, side_effect_level="write")
    async def save(call, context):
        with (root / "effects").open("a") as output:
            output.write("saved\n"); output.flush(); os.fsync(output.fileno())
        return ToolExecutionResult(tool_call_id=call.tool_call_id, operation_id=call.operation_id,
                                   content=(TextBlock(text="saved"),))
    class Model:
        async def capabilities(self, binding):
            return ModelCapabilities(supports_streaming=True, supports_tools=True)
        async def stream(self, request):
            if any(message.role == "tool" for message in request.messages):
                if mode == "crash":
                    (root / "ready").write_text("durable tool result before in-flight inference")
                    await asyncio.Event().wait()
                calls = ()
            else:
                calls = (ModelToolCall(tool_call_id="save-once", name="save", arguments={}),)
            yield ModelStreamEvent(kind="completed", response=ModelResponse(
                response_id="response", text="" if calls else "done", tool_calls=calls,
                finish_reason="tool_calls" if calls else "stop"))
    executor = LoopChildRunExecutor(runtime=runtime, resolved_spec_hash="sha256:flow",
        loop_factory=lambda *_: AgentLoopEngine(runtime=runtime, model=Model(),
            tool_catalog=InMemoryToolCatalog((tool,)), tool_executor=InMemoryToolExecutor({"save":tool},{"save":save}),
            tool_policy=DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)))
    native = NativeAgentFlowNode(runtime=runtime, child_executor=executor,
        descriptor=AgentDescriptor(agent_id="worker", name="worker", description="worker", instructions="work", tools=("save",)))
    flow = FlowDefinition(version="1", start="work", nodes=(FlowNode(id="work", type="agent", agent="worker"),),
                          edges=(FlowEdge(**{"from":"work", "to":"end"}),))
    engine = FlowRuntime(runtime=runtime, flows={"main":flow}, agent_nodes={"worker":native})
    result = (await engine.execute(run_id,"main",CONTEXT) if mode == "crash"
              else await engine.recover_interrupted(run_id,CONTEXT))
    print(json.dumps({"state":result.state.value}))
    await executor.close(); await store.close()
asyncio.run(main())
"""


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_hard_kill_flow_recovers_native_child_without_repeating_saved_write(
    tmp_path,
):
    import json
    import sys

    async def worker(mode):
        return await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _NATIVE_FLOW_WORKER,
            str(tmp_path),
            mode,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    first = await worker("crash")
    try:

        async def ready():
            while not (tmp_path / "ready").exists():
                if first.returncode is not None:
                    raise AssertionError((await first.stderr.read()).decode())
                await asyncio.sleep(0.02)

        await asyncio.wait_for(ready(), 60)
    finally:
        if first.returncode is None:
            first.kill()
        await first.wait()
    restored = await worker("recover")
    try:
        output, errors = await asyncio.wait_for(restored.communicate(), 60)
        assert restored.returncode == 0, errors.decode()
        assert json.loads(output.decode().splitlines()[-1])["state"] == "completed"
        assert (tmp_path / "effects").read_text() == "saved\n"
    finally:
        if restored.returncode is None:
            restored.kill()
            await restored.wait()


@pytest.mark.asyncio
async def test_recovery_reuses_answer_committed_before_running_cursor_checkpoint(
    tmp_path,
):
    from sagents.v2.contracts.commands import ReplyInteraction

    store = FilesystemSessionStore(tmp_path)
    runtime, handle = await start(store)
    finish = FakeNode({"done": True})
    flow = FlowDefinition(
        version="1",
        start="approval",
        nodes=(
            FlowNode(
                id="approval",
                type="interaction",
                interaction="approval",
                blocking_scope="run",
            ),
            FlowNode(id="finish", type="agent", agent="worker"),
        ),
        edges=(
            FlowEdge(**{"from": "approval", "to": "finish"}),
            FlowEdge(**{"from": "finish", "to": "end"}),
        ),
    )
    engine = FlowRuntime(
        runtime=runtime, flows={"main": flow}, agent_nodes={"worker": finish}
    )
    run = await engine.execute(handle.run_id, "main", CONTEXT)
    suspension = await store.get_suspension(run.suspension_id)
    interaction = await store.get_interaction(suspension.interaction_id)
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=run.run_id,
            expected_revision=run.revision,
            suspension_id=suspension.suspension_id,
            expected_suspension_revision=suspension.expected_revision,
            interaction_id=interaction.interaction_id,
            expected_interaction_revision=interaction.expected_revision,
            decision="approve",
            idempotency_key="answer",
        ),
        CONTEXT,
    )
    run = await runtime.get_run(run.run_id)
    await runtime.mark_resumed(
        run_id=run.run_id,
        expected_revision=run.revision,
        context=CONTEXT,
        idempotency_key="crash-after-resume",
    )
    await store.close()
    restored = FilesystemSessionStore(tmp_path)
    try:
        engine = FlowRuntime(
            runtime=HarnessRuntime(restored),
            flows={"main": flow},
            agent_nodes={"worker": finish},
        )
        assert (
            await engine.recover_interrupted(run.run_id, CONTEXT)
        ).state == RunState.COMPLETED
        assert len(finish.calls) == 1
        assert finish.calls[0].prior_results["approval"]["decision"] == "approve"
        events = await restored.read_events(run.run_id)
        assert (
            len([event for event in events if event.type == "interaction.requested"])
            == 1
        )
    finally:
        await restored.close()


@pytest.mark.asyncio
async def test_legacy_suspension_checkpoint_does_not_authorize_replaying_running_nodes(
    tmp_path,
):
    from sagents.v2.contracts.checkpoint import Checkpoint

    store = FilesystemSessionStore(tmp_path)
    runtime, handle = await start(store)
    run = await runtime.get_run(handle.run_id)
    run = await runtime.start_execution(
        run_id=run.run_id,
        expected_revision=run.revision,
        context=CONTEXT,
        idempotency_key="legacy-start",
    )
    state = FlowExecutionState(
        flow_id="main", flow_execution_id="legacy", current_node_id="inspect"
    )
    checkpoint = Checkpoint(
        checkpoint_id="legacy-checkpoint",
        checkpoint_codec_version="flow/2",
        session_id=run.session_id,
        run_id=run.run_id,
        run_sequence=run.last_run_sequence,
        session_revision=(await store.get_session(run.session_id)).revision,
        state=state.model_dump(mode="json", exclude={"execution_checkpoint"}),
        resolved_spec_hash=run.resolved_spec_hash,
        created_at=run.created_at,
    )
    await store.commit_run(
        run_id=run.run_id,
        expected_revision=run.revision,
        expected_states={RunState.RUNNING},
        new_state=RunState.RUNNING,
        drafts=(),
        checkpoint=checkpoint,
        context=CONTEXT,
        idempotency_key="legacy-checkpoint",
    )
    inspector = FakeNode({"saved": True})
    engine = FlowRuntime(
        runtime=runtime,
        flows={"main": sequential_flow()},
        agent_nodes={"inspector": inspector, "verifier": FakeNode({})},
    )
    try:
        with pytest.raises(SageV2Error, match="Legacy suspended checkpoints"):
            await engine.recover_interrupted(run.run_id, CONTEXT)
        assert not inspector.calls
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_pause_after_start_before_first_checkpoint_is_recoverable(tmp_path):
    from sagents.v2.contracts.commands import PauseRun

    store = FilesystemSessionStore(tmp_path)
    runtime, handle = await start(store)
    run = await runtime.get_run(handle.run_id)
    run = await runtime.start_execution(
        run_id=run.run_id,
        expected_revision=run.revision,
        context=CONTEXT,
        idempotency_key="before-checkpoint",
    )
    await runtime.pause_run(
        PauseRun(
            run_id=run.run_id, expected_revision=run.revision, idempotency_key="pause"
        ),
        CONTEXT,
    )
    inspector = FakeNode({})
    engine = FlowRuntime(
        runtime=runtime,
        flows={"main": sequential_flow()},
        agent_nodes={"inspector": inspector, "verifier": FakeNode({})},
    )
    try:
        assert (
            await engine.recover_interrupted(run.run_id, CONTEXT, flow_id="main")
        ).state == RunState.SUSPENDED
        assert not inspector.calls
    finally:
        await store.close()
