from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import pytest

from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
from sagents.v2.contracts.errors import ErrorCategory, SageV2Error
from sagents.v2.tool import McpServerConfig, McpToolPlugin, ToolCall


CONTEXT = RequestContext(
    actor=ActorRef(principal_id="user_1", principal_type=PrincipalType.USER)
)


class FakeSession:
    def __init__(self) -> None:
        self.calls = []

    async def list_tools(self):
        return {
            "tools": [
                {
                    "name": "search files",
                    "description": "Search remote files",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ]
        }

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return {
            "content": [{"type": "text", "text": "found"}],
            "structuredContent": {"count": 1},
            "isError": False,
        }


@pytest.mark.asyncio
async def test_mcp_bridge_namespaces_discovers_executes_and_deduplicates():
    session = FakeSession()

    @asynccontextmanager
    async def factory(config):
        assert config.name == "drive"
        yield session

    bridge = McpToolPlugin(
        (
            McpServerConfig(
                name="drive", protocol="streamable_http", url="https://mcp.test"
            ),
        ),
        session_factory=factory,
    )
    tools = await bridge.list_tools(run_id="run_1")

    assert [value.name for value in tools] == ["mcp_drive_search_files"]
    assert tools[0].requires_approval is True
    assert tools[0].resume_strategy.value == "manual_resolution"
    call = ToolCall(
        tool_call_id="call_1",
        tool_name=tools[0].name,
        arguments={"query": "report"},
        operation_id="operation_1",
        idempotency_key="same-call",
        owner_run_id="run_1",
    )
    first = await bridge.execute(call, CONTEXT)
    second = await bridge.execute(call, CONTEXT)

    assert first == second
    assert session.calls == [("search files", {"query": "report"})]
    assert first.content[0].text == "found"
    assert first.content[1].value == {"count": 1}
    reconciled = await bridge.reconcile("operation_1", CONTEXT)
    assert reconciled.state.value == "succeeded"


@pytest.mark.asyncio
async def test_mcp_bridge_coalesces_concurrent_idempotent_dispatches():
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingSession(FakeSession):
        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            started.set()
            await release.wait()
            return {"content": [{"type": "text", "text": "found"}]}

    session = BlockingSession()

    @asynccontextmanager
    async def factory(config):
        del config
        yield session

    bridge = McpToolPlugin(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp"),),
        session_factory=factory,
    )
    tool = (await bridge.list_tools(run_id="run_1"))[0]
    call = ToolCall(
        tool_call_id="call_1",
        tool_name=tool.name,
        arguments={"query": "report"},
        operation_id="operation_1",
        idempotency_key="dispatch-once",
        owner_run_id="run_1",
    )

    first = asyncio.create_task(bridge.execute(call, CONTEXT))
    await started.wait()
    second = asyncio.create_task(bridge.execute(call, CONTEXT))
    await asyncio.sleep(0)
    pending = await bridge.reconcile("operation_1", CONTEXT)
    release.set()
    first_result, second_result = await asyncio.gather(first, second)

    assert pending.state.value == "pending"
    assert first_result == second_result
    assert session.calls == [("search files", {"query": "report"})]


@pytest.mark.asyncio
async def test_mcp_bridge_rejects_idempotency_key_reuse_for_a_different_call():
    session = FakeSession()

    @asynccontextmanager
    async def factory(config):
        del config
        yield session

    bridge = McpToolPlugin(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp"),),
        session_factory=factory,
    )
    tool = (await bridge.list_tools(run_id="run_1"))[0]
    original = ToolCall(
        tool_call_id="call_1",
        tool_name=tool.name,
        arguments={"query": "report"},
        operation_id="operation_1",
        idempotency_key="reused-key",
        owner_run_id="run_1",
    )
    conflicting = original.model_copy(
        update={"tool_call_id": "call_2", "arguments": {"query": "different"}}
    )

    await bridge.execute(original, CONTEXT)
    with pytest.raises(SageV2Error) as caught:
        await bridge.execute(conflicting, CONTEXT)

    assert caught.value.info.code == "tool.idempotency_conflict"
    assert session.calls == [("search files", {"query": "report"})]


@pytest.mark.asyncio
async def test_mcp_bridge_validates_arguments_before_remote_dispatch():
    session = FakeSession()

    @asynccontextmanager
    async def factory(config):
        del config
        yield session

    bridge = McpToolPlugin(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp"),),
        session_factory=factory,
    )
    tool = (await bridge.list_tools(run_id="run_1"))[0]
    call = ToolCall(
        tool_call_id="call_1",
        tool_name=tool.name,
        arguments={},
        operation_id="operation_1",
        idempotency_key="invalid-call",
        owner_run_id="run_1",
    )

    with pytest.raises(SageV2Error) as caught:
        await bridge.execute(call, CONTEXT)

    assert caught.value.info.code == "tool.arguments_invalid"
    assert caught.value.info.metadata["side_effect_state"] == "not_applied"
    assert session.calls == []


@pytest.mark.asyncio
async def test_mcp_bridge_exposes_discovery_failure_instead_of_hiding_server():
    @asynccontextmanager
    async def failing_factory(config):
        raise ConnectionError("offline")
        yield  # pragma: no cover

    bridge = McpToolPlugin(
        (McpServerConfig(name="broken", protocol="stdio", command="missing"),),
        session_factory=failing_factory,
    )

    with pytest.raises(Exception, match="offline") as caught:
        await bridge.list_tools(run_id="run_1")
    assert caught.value.info.code == "mcp.discovery_failed"
    assert caught.value.info.category == ErrorCategory.PROVIDER_TRANSIENT
    assert caught.value.info.retryable is True


@pytest.mark.asyncio
async def test_mcp_dispatch_transport_failure_is_an_uncertain_side_effect():
    class FailingSession(FakeSession):
        async def call_tool(self, name, arguments):
            del name, arguments
            raise ConnectionError("connection lost after dispatch")

    @asynccontextmanager
    async def factory(config):
        del config
        yield FailingSession()

    bridge = McpToolPlugin(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp"),),
        session_factory=factory,
    )
    tool = (await bridge.list_tools(run_id="run_1"))[0]
    call = ToolCall(
        tool_call_id="call_1",
        tool_name=tool.name,
        arguments={"query": "report"},
        operation_id="operation_1",
        idempotency_key="dispatch-once",
        owner_run_id="run_1",
    )

    with pytest.raises(SageV2Error) as caught:
        await bridge.execute(call, CONTEXT)

    assert caught.value.info.code == "mcp.call_failed"
    assert caught.value.info.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT
    assert caught.value.info.retryable is False
    assert caught.value.info.safe_to_resume is False

    with pytest.raises(SageV2Error) as replayed:
        await bridge.execute(call, CONTEXT)
    assert replayed.value.info == caught.value.info


@pytest.mark.asyncio
async def test_mcp_concurrent_failure_is_typed_and_dispatched_once():
    started = asyncio.Event()
    release = asyncio.Event()

    class FailingSession(FakeSession):
        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            started.set()
            await release.wait()
            raise ConnectionError("connection lost after dispatch")

    session = FailingSession()

    @asynccontextmanager
    async def factory(config):
        del config
        yield session

    bridge = McpToolPlugin(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp"),),
        session_factory=factory,
    )
    tool = (await bridge.list_tools(run_id="run_1"))[0]
    call = ToolCall(
        tool_call_id="call_1",
        tool_name=tool.name,
        arguments={"query": "report"},
        operation_id="operation_1",
        idempotency_key="dispatch-once",
        owner_run_id="run_1",
    )

    first = asyncio.create_task(bridge.execute(call, CONTEXT))
    await started.wait()
    second = asyncio.create_task(bridge.execute(call, CONTEXT))
    await asyncio.sleep(0)
    release.set()
    failures = await asyncio.gather(first, second, return_exceptions=True)

    assert session.calls == [("search files", {"query": "report"})]
    assert all(isinstance(value, SageV2Error) for value in failures)
    assert {value.info.code for value in failures} == {"mcp.call_failed"}


def test_mcp_api_key_is_redacted_by_the_persistable_contract():
    config = McpServerConfig(
        name="drive",
        protocol="streamable_http",
        url="https://mcp.test",
        api_key="super-secret",
    )

    assert "super-secret" not in repr(config)
    assert config.model_dump(mode="json")["api_key"] == "**********"
