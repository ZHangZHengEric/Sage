"""Transport failures reach the model without blocking root or delegated runs."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from sagents.v2.agent import AgentLoopEngine
from sagents.v2.agent.modes import ModeAwareAgentLoopFactory
from sagents.v2.agent.multi_agent import AgentDescriptor, AgentMode, AgentRegistry
from sagents.v2.agent.policy.tool_policy import ApprovalStrategy
from sagents.v2.agent.policy.plugins.tool_policy import DefaultToolPolicy
from sagents.v2.contracts.commands import InputItem, RunConfig, StartRun
from sagents.v2.contracts.items import TextBlock
from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.contracts.run_state import RunState
from sagents.v2.model import ModelResponse, ModelStreamEvent, ModelToolCall
from sagents.v2.testing.plugins.scripted_model import ScriptedModelProvider, ScriptedModelStep
from sagents.v2.testing.runtime import ephemeral_runtime
from sagents.v2.tool import McpServerConfig, McpToolPlugin


CONTEXT = RequestContext(actor=ActorRef(principal_id="user", principal_type=PrincipalType.USER,
                                       scopes=("tool.external_side_effect",)))
POLICY = DefaultToolPolicy(approval_strategy=ApprovalStrategy.AUTO_APPROVE)


def step(*, tool=None, key="call", assertion=None):
    calls = (ModelToolCall(tool_call_id=key, name=f"mcp_media_{tool}", arguments={"job": "video-1"}),) if tool else ()
    return ScriptedModelStep(events=(ModelStreamEvent(kind="completed", response=ModelResponse(
        response_id=key, text="" if calls else "done", tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
    )),), assertion=assertion)


def assert_unknown(request):
    messages = [message for message in request.messages if message.role == "tool"]
    text = "\n".join(block.text for block in messages[-1].content if isinstance(block, TextBlock))
    assert "remote execution outcome is unknown" in text
    assert "Before retrying" in text
    assert "operation_id" in text and "idempotency_key" in text
    assert "video-1" in text
    assert messages[-1].metadata["recovery_action"] == "check_status_before_retry"


class MediaServer:
    def __init__(self, failure, *, applied=True):
        self.failure = failure
        self.applied = applied
        self.calls = []
        self.created = 0
        self.sessions = 0
        self.dispatched = asyncio.Event()

    async def list_tools(self):
        return {"tools": [{"name": name, "description": name,
                           "inputSchema": {"type": "object", "properties": {"job": {"type": "string"}}}}
                          for name in ("create", "status")]}

    async def call_tool(self, name, arguments):
        self.calls.append(name)
        if name == "create":
            first = self.calls.count("create") == 1
            if not first or self.applied:
                self.created += 1
            if first:
                self.dispatched.set()
                if self.failure == "reset":
                    raise ConnectionResetError("Connection reset by peer")
                if self.failure in {"timeout", "interrupted"}:
                    await asyncio.Event().wait()
                if self.failure == "none":
                    return None
            text = "created"
        else:
            text = "completed: video-1.mp4" if self.created else "not_applied: safe to retry"
        return {"content": [{"type": "text", "text": text}], "isError": False}

    @asynccontextmanager
    async def session(self, config):
        self.sessions += 1
        yield self

    def bridge(self):
        return McpToolPlugin((McpServerConfig(
            name="media", protocol="streamable_http", url="https://unused.test",
            call_timeout_seconds=0.01 if self.failure == "timeout" else None,
        ),), session_factory=self.session)


async def start(runtime, agent_id="root"):
    return await runtime.start_run(StartRun(
        agent_id=agent_id, input=(InputItem(role="user", content=(TextBlock(text="make video"),)),),
        config=RunConfig(max_steps=10), resolved_spec_hash="sha256:mcp-recovery", idempotency_key="start",
    ), CONTEXT)


async def assert_no_interactions(runtime, run_id):
    events = await runtime.session_store.read_events(run_id)
    assert not [event for event in events if event.type == "interaction.requested"]
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["reset", "timeout", "none"])
@pytest.mark.parametrize("applied", [True, False])
async def test_main_agent_checks_status_then_reuses_output_or_retries(failure, applied):
    server = MediaServer(failure, applied=applied)
    bridge = server.bridge()
    runtime = ephemeral_runtime()
    handle = await start(runtime)
    steps = [step(tool="create"), step(tool="status", key="status", assertion=assert_unknown)]
    if not applied:
        steps.append(step(tool="create", key="retry"))
    steps.append(step())
    model = ScriptedModelProvider(tuple(steps))
    loop = AgentLoopEngine(runtime=runtime, model=model, tool_catalog=bridge, tool_executor=bridge, tool_policy=POLICY)

    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert server.calls == (["create", "status"] if applied else ["create", "status", "create"])
    assert server.created == 1
    assert server.sessions >= len(server.calls)  # Each recovery call opens a fresh connection.
    events = await assert_no_interactions(runtime, handle.run_id)
    failures = [e for e in events if e.type == "tool.call.failed"]
    assert len(failures) == 1
    assert failures[0].data.error.metadata["execution_outcome"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["reset", "timeout", "none"])
async def test_parent_and_delegated_child_both_recover_without_approval(failure):
    runtime = ephemeral_runtime()
    handle = await start(runtime)
    servers = {name: MediaServer(failure) for name in ("root", "child")}
    bridges = {name: server.bridge() for name, server in servers.items()}
    definitions = await bridges["root"].list_tools(run_id=handle.run_id)
    delegate = ScriptedModelStep(events=(ModelStreamEvent(kind="completed", response=ModelResponse(
        response_id="delegate", tool_calls=(ModelToolCall(
            tool_call_id="delegate", name="sys_team_delegate_task",
            arguments={"tasks": [{"agent_id": "child", "content": "make video"}]},
        ),), finish_reason="tool_calls",
    )),))
    models = {name: ScriptedModelProvider((
        step(tool="create"), step(tool="status", key="status", assertion=assert_unknown),
        *((delegate,) if name == "root" else ()), step(),
    )) for name in servers}
    descriptors = {name: AgentDescriptor(
        agent_id=name, name=name, description=name, instructions="Complete the task",
        mode=AgentMode.TEAM if name == "root" else AgentMode.SIMPLE,
        tools=tuple(tool.name for tool in definitions),
    ) for name in servers}

    def compose(descriptor, run_id, catalog, executor):
        return AgentLoopEngine(runtime=runtime, model=models[descriptor.agent_id],
                               tool_catalog=catalog, tool_executor=executor, tool_policy=POLICY)

    # The production factory shares the base bridge across parent and child.
    # Route fake sessions by the running task's owner to fault each agent once.
    class RoutedBridge(McpToolPlugin):
        async def execute(self, call, context):
            owner = (await runtime.session_store.get_start_command(call.owner_run_id)).agent_id
            bridge = bridges[owner]
            await bridge.list_tools(run_id=call.owner_run_id)
            return await bridge.execute(call, context)

    base = RoutedBridge(bridges["root"].servers, session_factory=servers["root"].session)
    factory = ModeAwareAgentLoopFactory(
        runtime=runtime, model_factory=lambda descriptor, _: models[descriptor.agent_id],
        base_catalog=base, base_executor=base, registry=AgentRegistry(tuple(descriptors.values())),
        resolved_spec_hash="sha256:mcp-recovery", loop_composer=compose,
    )
    result = await factory.create_loop(descriptors["root"], handle.run_id).execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    for server in servers.values():
        assert server.calls == ["create", "status"]
        assert server.created == 1
    await assert_no_interactions(runtime, handle.run_id)
    sessions = await runtime.session_store.list_descendant_sessions(handle.session_id)
    assert len(sessions) == 1
    child_runs = await runtime.session_store.list_session_runs(sessions[0].session_id)
    assert len(child_runs) == 1
    assert child_runs[0].state == RunState.COMPLETED
    await assert_no_interactions(runtime, child_runs[0].run_id)
    # Child interaction propagation must not introduce a parent approval.
    for model in models.values():
        assert len(model.requests) >= 3


@pytest.mark.asyncio
async def test_interrupted_dispatch_recovers_with_new_bridge_without_replaying_write():
    server = MediaServer("interrupted")
    runtime = ephemeral_runtime()
    handle = await start(runtime)
    bridge = server.bridge()
    loop = AgentLoopEngine(runtime=runtime, model=ScriptedModelProvider((step(tool="create"),)),
                           tool_catalog=bridge, tool_executor=bridge, tool_policy=POLICY)
    task = asyncio.create_task(loop.execute(handle.run_id, CONTEXT))
    await asyncio.wait_for(server.dispatched.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    fresh_bridge = server.bridge()  # No in-memory receipts survive the worker loss.
    cold = ephemeral_runtime()
    await cold.session_store.load_state(await runtime.session_store.export_state())
    model = ScriptedModelProvider((step(tool="status", key="status", assertion=assert_unknown), step()))
    recovered = AgentLoopEngine(runtime=cold, model=model, tool_catalog=fresh_bridge,
                                tool_executor=fresh_bridge, tool_policy=POLICY)
    result = await recovered.recover_interrupted(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert server.calls == ["create", "status"]
    assert server.created == 1
    await assert_no_interactions(cold, handle.run_id)


@pytest.mark.asyncio
async def test_connection_reset_before_dispatch_returns_known_failure_for_safe_retry():
    server = MediaServer("none")
    attempts = 0

    @asynccontextmanager
    async def session(config):
        nonlocal attempts
        attempts += 1
        if attempts == 2:  # Discovery succeeds; opening the first call fails.
            raise ConnectionResetError("connection reset before dispatch")
        yield server

    bridge = McpToolPlugin(server.bridge().servers, session_factory=session)
    runtime = ephemeral_runtime()
    handle = await start(runtime)

    def assert_not_applied(request):
        message = [m for m in request.messages if m.role == "tool"][-1]
        assert "mcp.connection_failed" in message.content[0].text
        assert "outcome is unknown" not in message.content[0].text

    model = ScriptedModelProvider((step(tool="status"), step(tool="status", key="retry", assertion=assert_not_applied), step()))
    loop = AgentLoopEngine(runtime=runtime, model=model, tool_catalog=bridge, tool_executor=bridge, tool_policy=POLICY)
    result = await loop.execute(handle.run_id, CONTEXT)

    assert result.state == RunState.COMPLETED
    assert server.calls == ["status"]
    await assert_no_interactions(runtime, handle.run_id)
