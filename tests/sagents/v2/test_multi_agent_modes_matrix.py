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
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.localization import localize_tool_definition
from sagents.v2.contracts.commands import (
    InputItem,
    ReplyInteraction,
    RunConfig,
    StartRun,
)
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState, SessionConcurrencyMode
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    AgentMode,
    AgentRegistry,
    DelegationBatch,
    DelegationResult,
    DelegationTask,
    MultiAgentCoordinator,
    SessionDynamicAgentRoster,
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
        (AgentMode.FIBRE, WorkspaceSharingPolicy.SHARED_PARENT),
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
@pytest.mark.parametrize("mode", [AgentMode.FIBRE, AgentMode.TEAM])
async def test_workspace_policy_is_independent_from_agent_mode(mode):
    executor = FakeChildExecutor()
    coordinator = MultiAgentCoordinator(
        mode=mode,
        registry=AgentRegistry((MEMBER,)),
        executor=executor,
        workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD,
    )
    await coordinator.delegate(
        DelegationBatch(tasks=(task(1),)),
        parent_run_id="run_parent",
        parent_session_id="session_parent",
        context=CONTEXT,
    )
    assert (
        executor.calls[0][2]["workspace_policy"] == WorkspaceSharingPolicy.PRIVATE_CHILD
    )


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
    runtime = ephemeral_runtime()
    suite = MultiAgentToolPlugin(
        coordinator=MultiAgentCoordinator(
            mode=mode, registry=AgentRegistry((MEMBER,)), executor=FakeChildExecutor()
        ),
        runtime=runtime,
    )
    assert {
        tool.name for tool in await suite.catalog.list_tools(run_id="run_1")
    } == names


@pytest.mark.asyncio
async def test_multi_agent_tool_definitions_are_localized_for_the_model():
    runtime = ephemeral_runtime()
    suite = MultiAgentToolPlugin(
        coordinator=MultiAgentCoordinator(
            mode=AgentMode.FIBRE,
            registry=AgentRegistry((MEMBER,)),
            executor=FakeChildExecutor(),
        ),
        runtime=runtime,
    )

    spawn = localize_tool_definition(
        await suite.catalog.get_tool("sys_spawn_agent", run_id="run_1"), "zh-CN"
    )
    delegate = localize_tool_definition(
        await suite.catalog.get_tool("sys_delegate_task", run_id="run_1"), "zh-CN"
    )

    assert spawn.description.startswith("创建一个可在当前会话中复用")
    assert spawn.input_schema["properties"]["system_prompt"]["description"].startswith(
        "定义子智能体"
    )
    assert delegate.description.startswith("把一个或多个具体任务")
    task_fields = delegate.input_schema["properties"]["tasks"]["items"]["properties"]
    assert task_fields["agent_id"]["description"] == "目标智能体的准确 ID"
    assert task_fields["original_task"]["description"].startswith("用于补充上下文")


@pytest.mark.asyncio
async def test_fibre_delegation_schema_and_optional_context_fields():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root task"),)),),
            resolved_spec_hash="sha256:parent",
            idempotency_key="parent_for_delegation_tool",
        ),
        CONTEXT,
    )
    executor = FakeChildExecutor()
    suite = MultiAgentToolPlugin(
        coordinator=MultiAgentCoordinator(
            mode=AgentMode.FIBRE,
            registry=AgentRegistry((MEMBER,)),
            executor=executor,
        ),
        runtime=runtime,
    )
    definition = await suite.catalog.get_tool("sys_delegate_task", run_id=parent.run_id)
    task_schema = definition.input_schema["properties"]["tasks"]["items"]

    assert task_schema["required"] == ["agent_id", "content"]
    assert set(task_schema["properties"]) == {
        "agent_id",
        "content",
        "task_name",
        "original_task",
        "session_id",
    }

    result = await suite.executor.execute(
        ToolCall(
            tool_call_id="call_delegate",
            tool_name="sys_delegate_task",
            arguments={
                "tasks": [
                    {
                        "agent_id": "member",
                        "content": "Implement and test quicksort.",
                    },
                    {
                        "agent_id": "member",
                        "content": "Review the quicksort implementation.",
                        "task_name": "Review quicksort",
                    },
                ]
            },
            operation_id="operation_delegate",
            idempotency_key="delegate_without_optional_context",
            owner_run_id=parent.run_id,
        ),
        CONTEXT,
    )

    first = executor.calls[0][1]
    second = executor.calls[1][1]
    assert first.task_name == "Delegated task 1"
    assert first.original_task == "Implement and test quicksort."
    assert first.parent_tool_call_id == "call_delegate"
    assert second.task_id == "call_delegate_2"
    assert second.task_name == "Review quicksort"
    assert result.content[0].value["child_run_ids"] == [
        "run_call_delegate_1",
        "run_call_delegate_2",
    ]


@pytest.mark.asyncio
async def test_fibre_spawn_inherits_parent_tools_and_skills():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root task"),)),),
            config=RunConfig(
                enabled_tools=("file_read", "file_write", "execute_shell_command"),
                enabled_skills=("python",),
            ),
            resolved_spec_hash="sha256:parent",
            idempotency_key="parent_for_spawn_tool",
        ),
        CONTEXT,
    )
    registry = AgentRegistry((MEMBER,))
    suite = MultiAgentToolPlugin(
        coordinator=MultiAgentCoordinator(
            mode=AgentMode.FIBRE,
            registry=registry,
            executor=FakeChildExecutor(),
        ),
        runtime=runtime,
    )

    result = await suite.executor.execute(
        ToolCall(
            tool_call_id="call_spawn",
            tool_name="sys_spawn_agent",
            arguments={
                "name": "Coder",
                "description": "Writes and tests code",
                "system_prompt": "Implement code carefully and verify it.",
            },
            operation_id="operation_spawn",
            idempotency_key="spawn_with_parent_grants",
            owner_run_id=parent.run_id,
        ),
        CONTEXT,
    )

    spawned = await registry.get(result.content[0].value["agent_id"])
    assert spawned.tools == (
        "file_read",
        "file_write",
        "execute_shell_command",
    )
    assert spawned.skills == ("python",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        (
            "sys_spawn_agent",
            {
                "name": "Grandchild",
                "description": "Should never be created",
                "system_prompt": "This invocation must be rejected by policy.",
            },
        ),
        (
            "sys_delegate_task",
            {
                "tasks": [
                    {
                        "agent_id": "member",
                        "content": "Attempt nested delegation.",
                    }
                ]
            },
        ),
    ],
)
async def test_delegated_fibre_child_cannot_bypass_leaf_policy(tool_name, arguments):
    runtime = ephemeral_runtime()
    root = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            resolved_spec_hash="sha256:root",
            idempotency_key=f"root_for_{tool_name}",
        ),
        CONTEXT,
    )
    child = await runtime.start_run(
        StartRun(
            session_id=root.session_id,
            agent_id="member",
            input=(InputItem(role="user", content=(TextBlock(text="child"),)),),
            session_concurrency_mode=SessionConcurrencyMode.FORK,
            resolved_spec_hash="sha256:child",
            idempotency_key=f"delegated_child_for_{tool_name}",
            parent_run_id=root.run_id,
            invocation_mode="delegation",
        ),
        CONTEXT,
    )
    registry = AgentRegistry((MEMBER,))
    suite = MultiAgentToolPlugin(
        coordinator=MultiAgentCoordinator(
            mode=AgentMode.FIBRE,
            registry=registry,
            executor=FakeChildExecutor(),
        ),
        runtime=runtime,
    )

    with pytest.raises(Exception) as denied:
        await suite.executor.execute(
            ToolCall(
                tool_call_id=f"call_{tool_name}",
                tool_name=tool_name,
                arguments=arguments,
                operation_id=f"operation_{tool_name}",
                idempotency_key=f"nested_{tool_name}",
                owner_run_id=child.run_id,
            ),
            CONTEXT,
        )

    assert denied.value.info.code == "agent.nested_delegation_not_allowed"
    assert await registry.list() == (MEMBER,)


@pytest.mark.asyncio
async def test_delegated_team_child_can_delegate_with_fixed_roster_only():
    runtime = ephemeral_runtime()
    root = await runtime.start_run(
        StartRun(
            agent_id="team_leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            resolved_spec_hash="sha256:team-root",
            idempotency_key="team_root_for_nested_delegation",
        ),
        CONTEXT,
    )
    child = await runtime.start_run(
        StartRun(
            session_id=root.session_id,
            agent_id="team_member",
            input=(InputItem(role="user", content=(TextBlock(text="child"),)),),
            session_concurrency_mode=SessionConcurrencyMode.FORK,
            resolved_spec_hash="sha256:team-child",
            idempotency_key="delegated_team_child",
            parent_run_id=root.run_id,
            invocation_mode="delegation",
        ),
        CONTEXT,
    )
    executor = FakeChildExecutor()
    suite = MultiAgentToolPlugin(
        coordinator=MultiAgentCoordinator(
            mode=AgentMode.TEAM,
            registry=AgentRegistry((MEMBER,)),
            executor=executor,
        ),
        runtime=runtime,
    )

    names = {tool.name for tool in await suite.catalog.list_tools(run_id=child.run_id)}
    result = await suite.executor.execute(
        ToolCall(
            tool_call_id="call_nested_team_delegate",
            tool_name="sys_team_delegate_task",
            arguments={
                "tasks": [
                    {
                        "agent_id": "member",
                        "content": "Handle the next fixed-roster team task.",
                    }
                ]
            },
            operation_id="operation_nested_team_delegate",
            idempotency_key="nested_team_delegate",
            owner_run_id=child.run_id,
        ),
        CONTEXT,
    )

    assert names == {"sys_team_delegate_task"}
    assert "sys_spawn_agent" not in names
    assert len(executor.calls) == 1
    assert result.content[0].value["child_run_ids"] == [
        "run_call_nested_team_delegate_1"
    ]


@pytest.mark.asyncio
async def test_fibre_dynamic_agent_roster_survives_a_fresh_projection():
    runtime = ephemeral_runtime()
    leader = AgentDescriptor(
        agent_id="leader",
        name="Leader",
        description="Fibre leader",
        instructions="Create a specialist, then finish.",
        mode=AgentMode.FIBRE,
        tools=("file_read",),
        skills=("python",),
    )
    registry = AgentRegistry()
    spawn = ModelToolCall(
        tool_call_id="call_spawn",
        name="sys_spawn_agent",
        arguments={
            "name": "Coder",
            "description": "Writes and tests code",
            "system_prompt": "Implement code carefully and verify it.",
        },
    )
    provider = ScriptedModelProvider(
        (
            ScriptedModelStep(
                events=(
                    ModelStreamEvent(
                        kind=ModelEventKind.COMPLETED,
                        response=ModelResponse(
                            response_id="spawn_agent",
                            tool_calls=(spawn,),
                            finish_reason="tool_calls",
                        ),
                    ),
                )
            ),
            ScriptedModelStep(events=(completed("done"),)),
        )
    )
    factory = ModeAwareAgentLoopFactory(
        runtime=runtime,
        model_factory=lambda descriptor, run_id: provider,
        base_catalog=InMemoryToolCatalog(()),
        base_executor=InMemoryToolExecutor({}, {}),
        registry=registry,
        resolved_spec_hash="sha256:dynamic-roster",
    )
    parent = await runtime.start_run(
        StartRun(
            agent_id=leader.agent_id,
            input=(InputItem(role="user", content=(TextBlock(text="work"),)),),
            config=RunConfig(
                enabled_tools=leader.tools,
                enabled_skills=leader.skills,
            ),
            resolved_spec_hash="sha256:dynamic-roster",
            idempotency_key="dynamic_roster",
        ),
        CONTEXT,
    )

    result = await factory.create_loop(leader, parent.run_id).execute(
        parent.run_id, CONTEXT
    )
    restored = await SessionDynamicAgentRoster(runtime.session_store).load(
        parent.session_id
    )

    assert result.state == RunState.COMPLETED
    assert len(restored) == 1
    assert restored[0].name == "Coder"
    assert restored[0].dynamic is True
    assert restored[0].tools == ("file_read",)
    assert restored[0].skills == ("python",)


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
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            config=RunConfig(
                metadata={
                    "response_language": "zh",
                    "current_time": "Mon, 31 Aug 2026 00:21:50 +0800",
                    "system_context": {"preference": "concise"},
                    "working_directory": "/workspace",
                    "workspace_files": "Working directory: /workspace",
                }
            ),
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
    capable_member = MEMBER.model_copy(
        update={"tools": ("file_write",), "skills": ("python",)}
    )
    result = await loop_executor(runtime).run_child(
        capable_member,
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
    assert command.config.enabled_tools == ("file_write",)
    assert command.config.enabled_skills == ("python",)
    assert command.config.metadata["workspace_policy"] == "private_child"
    assert command.config.metadata["response_language"] == "zh"
    assert command.config.metadata["current_time"] == (
        "Mon, 31 Aug 2026 00:21:50 +0800"
    )
    assert command.config.metadata["system_context"] == {"preference": "concise"}
    assert "working_directory" not in command.config.metadata
    assert "workspace_files" not in command.config.metadata
    assert command.input[0].metadata["frozen_current_time_context"] == (
        "<current_time>Mon, 31 Aug 2026 00:21:50 +0800</current_time>"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        AgentMode.FIBRE,
        AgentMode.TEAM,
    ],
)
async def test_loop_child_executor_applies_mode_specific_delegation_policy(
    mode,
):
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            resolved_spec_hash="sha256:parent",
            idempotency_key="parent_for_leaf_child",
        ),
        CONTEXT,
    )
    await runtime.start_execution(
        run_id=parent.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="parent_for_leaf_child_execute",
    )
    observed = []

    def leaf_loop_factory(descriptor, run_id):
        observed.append(descriptor)
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

    executor = LoopChildRunExecutor(
        runtime=runtime,
        loop_factory=leaf_loop_factory,
        resolved_spec_hash="sha256:leaf-child",
    )
    nested_capable_member = MEMBER.model_copy(
        update={"mode": mode, "allow_delegation": True}
    )

    result = await executor.run_child(
        nested_capable_member,
        task(1),
        parent_run_id=parent.run_id,
        workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
        context=CONTEXT,
    )

    assert result.outcome == RunState.COMPLETED
    assert observed[0].mode == mode
    # Existing agents selected into either multi-agent mode are execution leaves.
    assert observed[0].allow_delegation is False


@pytest.mark.asyncio
async def test_recovered_delegated_child_remains_a_leaf_after_restart():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            resolved_spec_hash="sha256:parent",
            idempotency_key="parent_for_recovered_leaf",
        ),
        CONTEXT,
    )
    await runtime.start_execution(
        run_id=parent.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="parent_for_recovered_leaf_execute",
    )
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
    observed = []

    async def write(call, context):
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text="written"),),
        )

    def child_loop_factory(descriptor, run_id):
        observed.append(descriptor)
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

    original = MEMBER.model_copy(
        update={"mode": AgentMode.FIBRE, "allow_delegation": True}
    )
    initial = LoopChildRunExecutor(
        runtime=runtime,
        loop_factory=child_loop_factory,
        resolved_spec_hash="sha256:recovered-leaf",
    )
    suspended = await initial.run_child(
        original,
        task(1),
        parent_run_id=parent.run_id,
        workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
        context=CONTEXT,
    )
    assert suspended.outcome == RunState.SUSPENDED

    async def resolve_original(agent_id):
        assert agent_id == original.agent_id
        return original

    recovered = LoopChildRunExecutor(
        runtime=runtime,
        loop_factory=child_loop_factory,
        resolved_spec_hash="sha256:recovered-leaf",
        descriptor_resolver=resolve_original,
    )
    completed_child = await recovered.resolve_interaction(
        suspended.child_run_id,
        decision="approve_once",
        payload={},
        context=CONTEXT,
    )

    assert completed_child.outcome == RunState.COMPLETED
    assert len(observed) == 2
    assert all(descriptor.allow_delegation is False for descriptor in observed)


@pytest.mark.asyncio
async def test_shared_workspace_child_inherits_parent_workspace_projection():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            config=RunConfig(
                metadata={
                    "response_language": "zh",
                    "working_directory": "/workspace",
                    "workspace_files": "Working directory: /workspace\nREADME.md",
                    "external_paths": ["/references"],
                }
            ),
            resolved_spec_hash="sha256:parent",
            idempotency_key="shared_workspace_parent",
        ),
        CONTEXT,
    )
    await runtime.start_execution(
        run_id=parent.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="shared_workspace_parent_execute",
    )

    result = await loop_executor(runtime).run_child(
        MEMBER,
        task(1),
        parent_run_id=parent.run_id,
        workspace_policy=WorkspaceSharingPolicy.SHARED_PARENT,
        context=CONTEXT,
    )
    command = await runtime.session_store.get_start_command(result.child_run_id)

    assert command.config.metadata["working_directory"] == "/workspace"
    assert command.config.metadata["workspace_files"].endswith("README.md")
    assert command.config.metadata["external_paths"] == ["/references"]


@pytest.mark.asyncio
async def test_child_session_owner_is_recovered_by_a_fresh_coordinator():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(
        StartRun(
            agent_id="leader",
            input=(InputItem(role="user", content=(TextBlock(text="root"),)),),
            resolved_spec_hash="sha256:parent",
            idempotency_key="parent_for_owner_recovery",
        ),
        CONTEXT,
    )
    await runtime.start_execution(
        run_id=parent.run_id,
        expected_revision=0,
        context=CONTEXT,
        idempotency_key="parent_owner_recovery_execute",
    )
    first = MultiAgentCoordinator(
        mode=AgentMode.FIBRE,
        registry=AgentRegistry((MEMBER,)),
        executor=loop_executor(runtime),
    )
    delegated = await first.delegate(
        DelegationBatch(tasks=(task(1),)),
        parent_run_id=parent.run_id,
        parent_session_id=parent.session_id,
        context=CONTEXT,
    )
    other = MEMBER.model_copy(update={"agent_id": "other"})
    restored = MultiAgentCoordinator(
        mode=AgentMode.FIBRE,
        registry=AgentRegistry((MEMBER, other)),
        executor=loop_executor(runtime),
    )

    with pytest.raises(Exception) as owner:
        await restored.delegate(
            DelegationBatch(
                tasks=(
                    task(
                        2,
                        agent_id="other",
                        session_id=delegated[0].child_session_id,
                    ),
                )
            ),
            parent_run_id=parent.run_id,
            parent_session_id=parent.session_id,
            context=CONTEXT,
        )

    assert owner.value.info.code == "agent.child_session_owner_conflict"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", [AgentMode.SIMPLE, AgentMode.FIBRE, AgentMode.TEAM])
async def test_builtin_modes_are_agent_nodes_on_flow_runtime(mode):
    runtime = ephemeral_runtime()
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
    runtime = ephemeral_runtime()
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
    assert (
        grandchildren[0]["config"]["metadata"]["parent_tool_call_id"] == "call_delegate"
    )


@pytest.mark.asyncio
async def test_child_agent_approval_suspends_parent_flow_and_resumes_same_node():
    runtime = ephemeral_runtime()
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
    parent_suspension = await runtime.session_store.get_suspension(
        suspended_parent.suspension_id
    )
    parent_interaction = await runtime.session_store.get_interaction(
        parent_suspension.interaction_id
    )

    assert child.state == RunState.SUSPENDED
    assert parent_checkpoint.state["pending_node_execution_id"]
    assert parent_interaction.payload["child_run_id"] == child_run_id
    assert parent_interaction.payload["child_interaction_id"]
    await runtime.reply_interaction(
        ReplyInteraction(
            run_id=parent.run_id,
            suspension_id=parent_suspension.suspension_id,
            interaction_id=parent_interaction.interaction_id,
            expected_revision=suspended_parent.revision,
            expected_suspension_revision=parent_suspension.expected_revision,
            expected_interaction_revision=parent_interaction.expected_revision,
            decision="approve_once",
            idempotency_key="approve_child_write",
        ),
        CONTEXT,
    )

    completed_parent = await bundle.runtime.resume(parent.run_id, CONTEXT)
    completed_child = await runtime.get_run(child_run_id)
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
    assert completed_child.state == RunState.COMPLETED
    assert [event.type for event in node_events] == [
        "flow.node.started",
        "flow.node.suspended",
        "flow.node.resumed",
        "flow.node.completed",
    ]
    assert len({event.node_execution_id for event in node_events}) == 1
