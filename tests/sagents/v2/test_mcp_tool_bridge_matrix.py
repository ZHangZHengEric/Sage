from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from sagents.v2.contracts.principals import (
    ActorRef,
    PrincipalType,
    RequestContext,
)
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
