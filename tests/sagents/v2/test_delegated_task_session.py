"""Delegation passes a user task, never the parent's conversation history."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.runtime.session.contracts import SessionStore
    from typing import Literal

from sagents.v2.composition.contracts import ApplicationResource

from sagents.v2.model.provider import ModelProvider

import pytest
from pydantic import ValidationError

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.multi_agent import (
    AgentDescriptor,
    DelegationTask,
    WorkspaceSharingPolicy,
)
from sagents.v2.agent.multi_agent.executors import LoopChildRunExecutor
from sagents.v2.context import DefaultContextAssembler
from sagents.v2.context.session_history import SessionHistoryLedgerBuilder
from sagents.v2.contracts.commands import InputItem, StartRun
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.run_state import SessionConcurrencyMode
from sagents.v2.model import ModelToolCall, ScriptedModelProvider, ScriptedModelStep
from sagents.v2.runtime import HarnessRuntime
from sagents.v2.runtime.session import FilesystemSessionStore
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.tool import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
    SideEffectLevel,
    ToolDefinition,
    ToolExecutionResult,
)
from tests.sagents.v2.test_session_history_context_matrix import (
    CONTEXT,
    command,
    completed,
    execute,
)


def child_command(parent, key="child"):
    return StartRun(
        agent_id="reviewer",
        input=(
            InputItem(
                role="user", content=(TextBlock(text="review current candidate"),)
            ),
        ),
        resolved_spec_hash="sha256:child",
        idempotency_key=key,
        parent_run_id=parent.run_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("durable", [False, True])
async def test_delegation_task_only_then_own_history_survives_restart(
    tmp_path, durable
):
    store = (
        FilesystemSessionStore(tmp_path / "store")
        if durable
        else ephemeral_runtime().session_store
    )
    runtime = HarnessRuntime(cast('SessionStore', store))
    parent = await runtime.start_run(
        command("private parent question", "parent"), CONTEXT
    )
    parent_calls = tuple(
        ModelToolCall(tool_call_id=f"parent{i}", name="lookup", arguments={"i": i})
        for i in range(2)
    )
    executed = []

    async def lookup(call, context):
        executed.append(call.tool_call_id)
        return ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=(TextBlock(text=f"answer {call.arguments['i']}"),),
        )

    definition = ToolDefinition(
        name="lookup",
        description="look up",
        input_schema={"type": "object"},
        side_effect_level=SideEffectLevel.NONE,
    )
    await execute(
        runtime,
        parent,
        ScriptedModelProvider(
            (
                ScriptedModelStep(events=(completed(calls=parent_calls),)),
                ScriptedModelStep(events=(completed("private parent answer"),)),
            )
        ),
        definitions=(definition,),
        handlers={"lookup": lookup},
    )

    async def parent_attachment():
        yield b"parent-only attachment"

    await store.put_attachment(
        parent.session_id,
        artifact_id="parent-only",
        media_type="text/plain",
        content=parent_attachment(),
        context=CONTEXT,
    )
    parent_before = await store.get_session(parent.session_id)
    parent_events = await store.read_events(parent.run_id)
    requests = []

    def executor(answer, call=None):
        def factory(descriptor, run_id):
            model = ScriptedModelProvider(
                tuple(
                    (
                        [ScriptedModelStep(events=(completed(calls=(call,)),))]
                        if call
                        else []
                    )
                    + [ScriptedModelStep(events=(completed(answer),))]
                )
            )
            requests.append(model.requests)
            return AgentLoopEngine(
                runtime=runtime,
                model=cast(ModelProvider, model),
                context_assembler=DefaultContextAssembler(
                    developer_instructions=descriptor.instructions,
                    history_reader=runtime.session_store,
                ),
                tool_catalog=InMemoryToolCatalog((definition,)),
                tool_executor=InMemoryToolExecutor(
                    {"lookup": definition}, {"lookup": lookup}
                ),
            )

        return LoopChildRunExecutor(
            runtime=runtime, loop_factory=factory, resolved_spec_hash="sha256:child"
        )

    descriptor = AgentDescriptor(
        agent_id="reviewer",
        name="Reviewer",
        description="review",
        instructions="Review the specified candidate.",
        tools=("lookup",),
    )
    task = DelegationTask(
        task_id="first",
        agent_id="reviewer",
        task_name="review",
        original_task="parent task",
        content="review current candidate",
        parent_tool_call_id="parent-delegation",
    )
    first_executor = executor(
        "child answer",
        ModelToolCall(tool_call_id="child_lookup", name="lookup", arguments={"i": 99}),
    )
    child = await first_executor.run_child(
        descriptor,
        task,
        parent_run_id=parent.run_id,
        workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD,
        context=CONTEXT,
    )
    duplicate = await first_executor.run_child(
        descriptor,
        task,
        parent_run_id=parent.run_id,
        workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD,
        context=CONTEXT,
    )
    assert child.error is None, child.error
    assert duplicate.child_run_id == child.child_run_id
    assert len(requests[0]) == 2 and sum(map(len, requests)) == 2
    initial = requests[0][0]
    assert [
        b.text for m in initial.messages if m.role == "user" for b in m.content
    ] == [task.content]
    assert not any(m.tool_calls or m.role == "tool" for m in initial.messages)
    assert "private parent" not in str(initial.messages)
    assert task.original_task not in str(initial.messages)
    assert cast(TextBlock, child.content[0]).text == "child answer"
    assert await store.get_session(parent.session_id) == parent_before
    assert await store.read_events(parent.run_id) == parent_events
    child_session = await store.get_session(cast(str, child.child_session_id))
    child_run = await store.get_run(cast(str, child.child_run_id))
    assert child_session.parent_session_id == parent.session_id
    assert (await getattr(store, 'export_session_state')(child.child_session_id))["sessions"][0][
        "attachments"
    ] == {}
    assert child_run.concurrency_mode == SessionConcurrencyMode.SERIAL
    assert child_run.base_session_sequence == child_run.base_session_revision == 0
    start = await store.get_start_command(cast(str, child.child_run_id))
    assert (
        start.parent_run_id == parent.run_id
        and start.config.metadata["parent_tool_call_id"] == "parent-delegation"
    )
    assert start.config.metadata["original_task"] == task.original_task
    assert await store.read_fork_base_events(cast(str, child.child_run_id)) == ()
    if durable:
        await cast(ApplicationResource, store).close()
        store = FilesystemSessionStore(tmp_path / "store")
        runtime = HarnessRuntime(cast('SessionStore', store))
    second_executor = executor("followup answer")
    assert (
        await second_executor.child_session_owner(
            cast(str, child.child_session_id), parent_session_id=parent.session_id
        )
        == "reviewer"
    )
    follow_task = task.model_copy(
        update={
            "task_id": "followup",
            "child_session_id": child.child_session_id,
            "content": "now review the repair",
        }
    )
    follow = await second_executor.run_child(
        descriptor,
        follow_task,
        parent_run_id=parent.run_id,
        workspace_policy=WorkspaceSharingPolicy.PRIVATE_CHILD,
        context=CONTEXT,
    )
    assert follow.child_session_id == child.child_session_id
    assert cast(TextBlock, follow.content[0]).text == "followup answer"
    follow_request = requests[-1][0]
    assert [
        b.text for m in follow_request.messages if m.role == "user" for b in m.content
    ] == [task.content, follow_task.content]
    assert [c.tool_call_id for m in follow_request.messages for c in m.tool_calls] == [
        "child_lookup"
    ]
    assert [m.tool_call_id for m in follow_request.messages if m.role == "tool"] == [
        "child_lookup"
    ]
    assert "private parent" not in str(follow_request.messages)
    assert executed == ["parent0", "parent1", "child_lookup"]
    if durable:
        await cast(ApplicationResource, store).close()


@pytest.mark.asyncio
async def test_parent_link_requires_authorized_parent_and_retry_is_idempotent():
    runtime = ephemeral_runtime()
    parent = await runtime.start_run(command("secret parent", "parent"), CONTEXT)
    cmd = child_command(parent)
    intruder = CONTEXT.model_copy(
        update={"actor": CONTEXT.actor.model_copy(update={"principal_id": "other"})}
    )
    with pytest.raises(SageV2Error):
        await runtime.start_run(cmd, intruder)
    assert await runtime.session_store.list_descendant_sessions(parent.session_id) == ()
    first = await runtime.start_run(cmd, CONTEXT)
    assert (await runtime.start_run(cmd, CONTEXT)).run_id == first.run_id
    history = await SessionHistoryLedgerBuilder(runtime.session_store).build(
        cmd, run_id=first.run_id
    )
    assert len(history) == 1 and history[0].role == "user"
    assert history[0].content == cmd.input[0].content


def test_no_copy_flag_or_forged_tool_inputs():
    payload = child_command(type("Parent", (), {"run_id": "parent"})()).model_dump(
        mode="json"
    )
    assert "copy_parent_messages" not in payload
    with pytest.raises(ValidationError):
        StartRun.model_validate({**payload, "copy_parent_messages": True})
    with pytest.raises(ValidationError):
        InputItem(role=cast("Literal['user', 'assistant', 'system', 'developer']", "tool"), content=())
