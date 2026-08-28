from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.modes import (
    BuiltinAgentModeFactory,
    ModeAwareAgentLoopFactory,
)
from sagents.v2.context import DefaultContextAssembler
from sagents.v2.model import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
    ScriptedModelProvider,
)
from sagents.v2.testing.plugins.scripted_model import ScriptedModelStep
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.contracts.commands import (
    InputItem,
    ReplyInteraction,
    ResumeRun,
    StartRun,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    DelegationBatch,
    DelegationResult,
    DelegationTask,
    MultiAgentCoordinator,
    WorkspaceSharingPolicy,
)
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor
from sagents.v2.tool.plugins.official.delegation import MultiAgentToolPlugin


CONTEXT = RequestContext(
    actor=ActorRef(
        principal_id="leader",
        principal_type=PrincipalType.AGENT,
        scopes=frozenset({"agent.delegate", "agent.spawn"}),
    )
)
MEMBER = AgentDescriptor(
    agent_id="member",
    name="Member",
    description="General expert",
    instructions="Be exact and return evidence.",
)


class FakeChildExecutor:
    def __init__(self):
        self.calls = []
        self.active = 0
        self.peak = 0

    async def run_child(self, descriptor, task, **kwargs):
        self.calls.append((descriptor, task, kwargs))
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        return DelegationResult(
            task_id=task.task_id,
            agent_id=task.agent_id,
            child_session_id=task.child_session_id or f"session_{task.task_id}",
            child_run_id=f"run_{task.task_id}",
            outcome=RunState.COMPLETED,
            content=(TextBlock(text=f"done {task.task_id}"),),
        )


def task(index, *, agent_id="member", session_id=None):
    return DelegationTask(
        task_id=f"task_{index}",
        agent_id=agent_id,
        task_name=f"Task {index}",
        original_task="root",
        content=f"work {index}",
        child_session_id=session_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "workspace"),
    [
        (AgentMode.FIBRE, WorkspaceSharingPolicy.PRIVATE_CHILD),
        (AgentMode.TEAM, WorkspaceSharingPolicy.SHARED_PARENT),
    ],
)
async def test_fibre_team_delegation_is_parallel_and_preserves_order(mode, workspace):
    executor = FakeChildExecutor()
    coordinator = MultiAgentCoordinator(
        mode=mode,
        registry=AgentRegistry((MEMBER,)),
        executor=executor,
        max_concurrency=3,
    )
    results = await coordinator.delegate(
        DelegationBatch(tasks=tuple(task(index) for index in range(8))),
        parent_run_id="run_parent",
        parent_session_id="session_parent",
        context=CONTEXT,
    )
    assert [result.task_id for result in results] == [
        f"task_{index}" for index in range(8)
    ]
    assert executor.peak == 3
    assert all(call[2]["workspace_policy"] == workspace for call in executor.calls)


@pytest.mark.asyncio
async def test_fibre_can_spawn_reusable_agent_but_team_cannot():
    dynamic = MEMBER.model_copy(update={"agent_id": "dynamic"})
    fibre_registry = AgentRegistry((MEMBER,))
    fibre = MultiAgentCoordinator(
        mode=AgentMode.FIBRE, registry=fibre_registry, executor=FakeChildExecutor()
    )
    spawned = await fibre.spawn(dynamic)
    assert spawned.dynamic is True
    assert (await fibre_registry.get("dynamic")).dynamic is True

    team = MultiAgentCoordinator(
        mode=AgentMode.TEAM,
        registry=AgentRegistry((MEMBER,)),
        executor=FakeChildExecutor(),
    )
    with pytest.raises(Exception) as denied:
        await team.spawn(dynamic)
    assert denied.value.info.code == "agent.spawn_not_allowed"


def test_parallel_batch_rejects_duplicate_explicit_child_session():
    with pytest.raises(ValidationError, match="distinct child_session"):
        DelegationBatch(
            tasks=(task(1, session_id="child"), task(2, session_id="child"))
        )


@pytest.mark.asyncio
async def test_parent_session_and_cross_agent_child_session_reuse_are_rejected():
    registry = AgentRegistry((MEMBER, MEMBER.model_copy(update={"agent_id": "other"})))
    coordinator = MultiAgentCoordinator(
        mode=AgentMode.TEAM, registry=registry, executor=FakeChildExecutor()
    )
    with pytest.raises(Exception) as parent:
        await coordinator.delegate(
            DelegationBatch(tasks=(task(1, session_id="parent"),)),
            parent_run_id="run_parent",
            parent_session_id="parent",
            context=CONTEXT,
        )
    assert parent.value.info.code == "agent.parent_session_reuse"
    await coordinator.delegate(
        DelegationBatch(tasks=(task(2, session_id="child"),)),
        parent_run_id="run_parent",
        parent_session_id="parent",
        context=CONTEXT,
    )
    with pytest.raises(Exception) as owner:
        await coordinator.delegate(
            DelegationBatch(tasks=(task(3, agent_id="other", session_id="child"),)),
            parent_run_id="run_parent",
            parent_session_id="parent",
            context=CONTEXT,
        )
    assert owner.value.info.code == "agent.child_session_owner_conflict"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "names"),
    [
        (AgentMode.FIBRE, {"sys_spawn_agent", "sys_delegate_task"}),
        (AgentMode.TEAM, {"sys_team_delegate_task"}),
    ],
)
async def test_mode_tool_surface_is_explicit_and_does_not_leak(mode, names):
    runtime = HarnessRuntime()
    suite = MultiAgentToolPlugin(
        coordinator=MultiAgentCoordinator(
            mode=mode, registry=AgentRegistry((MEMBER,)), executor=FakeChildExecutor()
        ),
        runtime=runtime,
    )
    assert {
        tool.name for tool in await suite.catalog.list_tools(run_id="run_1")
    } == names


def completed(text):
    return ModelStreamEvent(
        kind=ModelEventKind.COMPLETED,
        response=ModelResponse(
            response_id="response_done", text=text, finish_reason="stop"
        ),
    )


def loop_executor(runtime):
    def factory(descriptor, run_id):
        return AgentLoopEngine(
            runtime=runtime,
            model=ScriptedModelProvider(
                (ScriptedModelStep(events=(completed("child done"),)),)
            ),
            tool_catalog=InMemoryToolCatalog(()),
            tool_executor=InMemoryToolExecutor({}, {}),
            context_assembler=DefaultContextAssembler(
                developer_instructions=descriptor.instructions
            ),
        )

    return LoopChildRunExecutor(
        runtime=runtime,
        loop_factory=factory,
        resolved_spec_hash="sha256:children",
    )


@pytest.mark.asyncio
async def test_loop_child_executor_creates_real_fork_run_with_parent_causality():
    runtime = HarnessRuntime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            resolved_spec_hash="sha256:parent",
            idempotency_key="parent",
        ),
        CONTEXT,
    )
    await runtime.start_execution(
        run_id=parent.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="parent_execute",
    )
    result = await loop_executor(runtime).run_child(
        MEMBER,
        task(1),
        parent_run_id=parent.run_id,
        workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD,
        context=CONTEXT,
    )
    assert result.outcome == RunState.COMPLETED
    assert result.content[0].text == "child done"
    command = await runtime.session_store.get_start_command(result.child_run_id)
    assert command.parent_run_id == parent.run_id
    assert command.invocation_mode == "delegation"
    assert command.session_id == parent.session_id
    assert command.config.metadata["workspace_policy"] == "private_child"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [AgentMode.SIMPLE, AgentMode.FIBRE, AgentMode.TEAM])
async def test_builtin_modes_are_agent_nodes_on_flow_runtime(mode):
    runtime = HarnessRuntime()
    parent = await runtime.start_run(
        StartRun(
            agent_id=f"{mode.value}_leader",
            input=(InputItem(role="user", content=(TextBlock(text="do work"),)),),
            resolved_spec_hash="sha256:parent",
            idempotency_key=f"parent_{mode.value}",
        ),
        CONTEXT,
    )
    descriptor = MEMBER.model_copy(
        update={"agent_id": f"{mode.value}_leader", "mode": mode}
    )
    bundle = BuiltinAgentModeFactory(runtime, loop_executor(runtime)).create(descriptor)
    result = await bundle.runtime.execute(parent.run_id, bundle.flow_id, CONTEXT)
    assert result.state == RunState.COMPLETED
    events = await runtime.session_store.read_events(parent.run_id)
    assert [event.type for event in events if event.type.startswith("flow.")] == [
        "flow.started",
        "flow.node.started",
        "flow.node.completed",
        "flow.completed",
    ]


@pytest.mark.asyncio
async def test_fibre_flow_node_delegates_to_real_nested_child_run():
    runtime = HarnessRuntime()
    leader = AgentDescriptor(
        agent_id="fibre_leader",
        name="Leader",
        description="Fibre leader",
        instructions="Delegate independent specialist work and synthesize the result.",
        mode=AgentMode.FIBRE,
    )
    registry = AgentRegistry((leader, MEMBER))

    def model_factory(descriptor, run_id):
        if descriptor.agent_id == "fibre_leader":
            delegation = ModelToolCall(
                tool_call_id="call_delegate",
                name="sys_delegate_task",
                arguments={
                    "tasks": [
                        {
                            "agent_id": "member",
                            "task_name": "inspect",
                            "original_task": "root task",
                            "content": "inspect independently",
                        }
                    ]
                },
            )
            return ScriptedModelProvider(
                (
                    ScriptedModelStep(
                        events=(
                            ModelStreamEvent(
                                kind=ModelEventKind.COMPLETED,
                                response=ModelResponse(
                                    response_id="leader_delegate",
                                    tool_calls=(delegation,),
                                    finish_reason="tool_calls",
                                ),
                            ),
                        )
                    ),
                    ScriptedModelStep(events=(completed("leader synthesis"),)),
                )
            )
        return ScriptedModelProvider(
            (ScriptedModelStep(events=(completed("member evidence"),)),)
        )

    empty_catalog = InMemoryToolCatalog(())
    empty_executor = InMemoryToolExecutor({}, {})
    loop_factory = ModeAwareAgentLoopFactory(
        runtime=runtime,
        model_factory=model_factory,
        base_catalog=empty_catalog,
        base_executor=empty_executor,
        registry=registry,
        resolved_spec_hash="sha256:mode-aware",
        max_delegation_concurrency=2,
    )
    root = await runtime.start_run(
        StartRun(
            agent_id=leader.agent_id,
            input=(InputItem(role="user", content=(TextBlock(text="root task"),)),),
            resolved_spec_hash="sha256:root",
            idempotency_key="nested_root",
        ),
        CONTEXT,
    )
    bundle = BuiltinAgentModeFactory(runtime, loop_factory.child_executor).create(
        leader
    )
    result = await bundle.runtime.execute(root.run_id, bundle.flow_id, CONTEXT)
    root_events = await runtime.session_store.read_events(root.run_id)
    assert result.state == RunState.COMPLETED, [
        (event.type, getattr(event.data, "error", None)) for event in root_events
    ]
    state = await runtime.session_store.export_state()
    start_commands = {
        value["run_id"]: value["start_command"] for value in state["runs"]
    }
    children = [
        value
        for value in start_commands.values()
        if value and value.get("parent_run_id") == root.run_id
    ]
    assert len(children) == 1
    leader_run_id = next(
        run_id
        for run_id, value in start_commands.items()
        if value and value.get("parent_run_id") == root.run_id
    )
    grandchildren = [
        value
        for value in start_commands.values()
        if value and value.get("parent_run_id") == leader_run_id
    ]
    assert len(grandchildren) == 1
    assert grandchildren[0]["agent_id"] == "member"


@pytest.mark.asyncio
async def test_child_agent_approval_suspends_parent_flow_and_resumes_same_node():
    runtime = HarnessRuntime()
    descriptor = MEMBER.model_copy(update={"agent_id": "approval_agent"})
    write_tool = ToolDefinition(
        name="write_value",
        description="Write a value after approval.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        side_effect_level=SideEffectLevel.WRITE,
    )
    providers = {}

    async def write(call, context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="written"),),
        )

    def child_loop_factory(value, run_id):
        provider = providers.setdefault(
            run_id,
            ScriptedModelProvider(
                (
                    ScriptedModelStep(
                        events=(
                            ModelStreamEvent(
                                kind=ModelEventKind.COMPLETED,
                                response=ModelResponse(
                                    response_id="needs_write",
                                    tool_calls=(
                                        ModelToolCall(
                                            tool_call_id="call_write",
                                            name="write_value",
                                            arguments={"value": "x"},
                                        ),
                                    ),
                                    finish_reason="tool_calls",
                                ),
                            ),
                        )
                    ),
                    ScriptedModelStep(events=(completed("child complete"),)),
                )
            ),
        )
        return AgentLoopEngine(
            runtime=runtime,
            model=provider,
            tool_catalog=InMemoryToolCatalog((write_tool,)),
            tool_executor=InMemoryToolExecutor(
                {write_tool.name: write_tool}, {write_tool.name: write}
            ),
        )

    child_executor = LoopChildRunExecutor(
        runtime=runtime,
        loop_factory=child_loop_factory,
        resolved_spec_hash="sha256:approval-child",
    )
    parent = await runtime.start_run(
        StartRun(
            agent_id=descriptor.agent_id,
            input=(InputItem(role="user", content=(TextBlock(text="write"),)),),
            resolved_spec_hash="sha256:approval-parent",
            idempotency_key="approval_parent",
        ),
        CONTEXT,
    )
    bundle = BuiltinAgentModeFactory(runtime, child_executor).create(descriptor)

    suspended_parent = await bundle.runtime.execute(
        parent.run_id, bundle.flow_id, CONTEXT
    )
    parent_events_before = await runtime.session_store.read_events(parent.run_id)
    assert suspended_parent.state == RunState.SUSPENDED, getattr(
        parent_events_before[-1].data, "error", None
    )
    parent_checkpoint = await runtime.session_store.get_latest_checkpoint(parent.run_id)
    child_run_id = parent_checkpoint.state["pending_child_run_id"]
    child = await runtime.get_run(child_run_id)
    child_suspension = await runtime.session_store.get_suspension(child.suspension_id)
    child_interaction = await runtime.session_store.get_interaction(
        child_suspension.interaction_id
    )

    assert child.state == RunState.SUSPENDED
    assert parent_checkpoint.state["pending_node_execution_id"]
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=child_run_id,
            suspension_id=child_suspension.suspension_id,
            interaction_id=child_interaction.interaction_id,
            expected_revision=child.revision,
            expected_suspension_revision=child_suspension.expected_revision,
            expected_interaction_revision=child_interaction.expected_revision,
            decision="approve_once",
            idempotency_key="approve_child_write",
        ),
        CONTEXT,
    )
    completed_child = await child_loop_factory(descriptor, child_run_id).resume(
        child_run_id, CONTEXT
    )
    assert completed_child.state == RunState.COMPLETED
    resume_receipt = await runtime.resume_run(
        ResumeRun(
            run_id=parent.run_id,
            suspension_id=suspended_parent.suspension_id,
            expected_revision=suspended_parent.revision,
            expected_suspension_revision=0,
            idempotency_key="resume_parent_after_child",
        ),
        CONTEXT,
    )
    assert resume_receipt.decision.value == "accepted"

    completed_parent = await bundle.runtime.resume(parent.run_id, CONTEXT)
    parent_events = await runtime.session_store.read_events(parent.run_id)
    node_events = [
        event
        for event in parent_events
        if event.type
        in {
            "flow.node.started",
            "flow.node.suspended",
            "flow.node.resumed",
            "flow.node.completed",
        }
    ]

    assert completed_parent.state == RunState.COMPLETED
    assert [event.type for event in node_events] == [
        "flow.node.started",
        "flow.node.suspended",
        "flow.node.resumed",
        "flow.node.completed",
    ]
    assert len({event.node_execution_id for event in node_events}) == 1
