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
    assert bridge.capabilities == {
        "durable_operation_ledger": False,
        "supports_restart_reconciliation": False,
        "protocol_exactly_once": False,
    }
    tools = await bridge.list_tools(run_id="run_1")

    assert [value.name for value in tools] == ["mcp_drive_search_files"]
    assert tools[0].requires_approval is True
    assert tools[0].idempotency_strategy.value == "reconcile_only"
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

    await bridge.release_run("run_1")
    assert (await bridge.reconcile("operation_1", CONTEXT)).state.value == "unknown"
    assert bridge._call_fingerprints == {}


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
async def test_cancelled_mcp_dispatch_cannot_be_replayed_as_a_fresh_write():
    started = asyncio.Event()

    class BlockingSession(FakeSession):
        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            started.set()
            await asyncio.Event().wait()

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
        idempotency_key="cancelled-dispatch",
        owner_run_id="run_1",
    )
    task = asyncio.create_task(bridge.execute(call, CONTEXT))
    await started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(SageV2Error) as replayed:
        await bridge.execute(call, CONTEXT)

    assert replayed.value.info.code == "mcp.result_cancelled"
    assert replayed.value.info.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT
    assert session.calls == [("search files", {"query": "report"})]


@pytest.mark.asyncio
async def test_optional_mcp_discovery_failure_keeps_healthy_servers_available():
    healthy = FakeSession()

    @asynccontextmanager
    async def factory(config):
        if config.name == "offline":
            raise ConnectionError("offline")
        yield healthy

    bridge = McpToolPlugin(
        (
            McpServerConfig(
                name="offline",
                protocol="stdio",
                command="offline-mcp",
                required=False,
            ),
            McpServerConfig(name="drive", protocol="stdio", command="drive-mcp"),
        ),
        session_factory=factory,
    )

    tools = await bridge.list_tools(run_id="run_1")

    assert [tool.name for tool in tools] == ["mcp_drive_search_files"]
    assert bridge._discovery_errors["offline"].code == "mcp.discovery_failed"


@pytest.mark.asyncio
async def test_mcp_discovery_rejects_catalog_above_configured_limit():
    class LargeCatalogSession(FakeSession):
        async def list_tools(self):
            return {
                "tools": [
                    {"name": "one", "inputSchema": {"type": "object"}},
                    {"name": "two", "inputSchema": {"type": "object"}},
                ]
            }

    @asynccontextmanager
    async def factory(config):
        del config
        yield LargeCatalogSession()

    bridge = McpToolPlugin(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp", max_tools=1),),
        session_factory=factory,
    )

    with pytest.raises(SageV2Error) as oversized:
        await bridge.list_tools(run_id="run_1")

    assert oversized.value.info.code == "mcp.tool_catalog_too_large"


@pytest.mark.asyncio
async def test_mcp_discovery_reads_all_catalog_pages():
    class PaginatedSession(FakeSession):
        def __init__(self):
            super().__init__()
            self.cursors = []

        async def list_tools(self, cursor=None):
            self.cursors.append(cursor)
            if cursor is None:
                return {
                    "tools": [{"name": "one", "inputSchema": {"type": "object"}}],
                    "nextCursor": "page_2",
                }
            return {"tools": [{"name": "two", "inputSchema": {"type": "object"}}]}

    session = PaginatedSession()

    @asynccontextmanager
    async def factory(config):
        del config
        yield session

    bridge = McpToolPlugin(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp"),),
        session_factory=factory,
    )

    tools = await bridge.list_tools(run_id="run_1")

    assert [tool.name for tool in tools] == ["mcp_drive_one", "mcp_drive_two"]
    assert session.cursors == [None, "page_2"]


@pytest.mark.asyncio
async def test_mcp_discovery_rejects_repeated_pagination_cursor():
    class LoopingSession(FakeSession):
        async def list_tools(self, cursor=None):
            del cursor
            return {"tools": [], "nextCursor": "same"}

    @asynccontextmanager
    async def factory(config):
        del config
        yield LoopingSession()

    bridge = McpToolPlugin(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp"),),
        session_factory=factory,
    )

    with pytest.raises(SageV2Error) as invalid:
        await bridge.list_tools(run_id="run_1")

    assert invalid.value.info.code == "mcp.pagination_invalid"


@pytest.mark.asyncio
async def test_mcp_large_result_is_bounded_and_cached_without_replay():
    class LargeResultSession(FakeSession):
        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return {"content": [{"type": "text", "text": "x" * 2_000}]}

    session = LargeResultSession()

    @asynccontextmanager
    async def factory(config):
        del config
        yield session

    bridge = McpToolPlugin(
        (
            McpServerConfig(
                name="drive",
                protocol="stdio",
                command="mcp",
                max_result_bytes=256,
            ),
        ),
        session_factory=factory,
    )
    tool = (await bridge.list_tools(run_id="run_1"))[0]
    call = ToolCall(
        tool_call_id="call_1",
        tool_name=tool.name,
        arguments={"query": "report"},
        operation_id="operation_1",
        idempotency_key="large-result",
        owner_run_id="run_1",
    )

    first = await bridge.execute(call, CONTEXT)
    second = await bridge.execute(call, CONTEXT)

    assert first == second
    assert first.error is None
    assert first.metadata["mcp_result_truncated"] is True
    assert "exceeded" in first.content[0].text
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

    assert caught.value.info.code == "mcp.result_not_received"
    assert caught.value.info.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT
    assert caught.value.info.retryable is False
    assert caught.value.info.safe_to_resume is False
    assert caught.value.info.metadata["mcp_result_received"] is False
    assert caught.value.info.metadata["transport_failure"] == "connection"

    with pytest.raises(SageV2Error) as replayed:
        await bridge.execute(call, CONTEXT)
    assert replayed.value.info == caught.value.info


@pytest.mark.asyncio
async def test_mcp_timeout_is_an_uncertain_side_effect_without_a_tool_result():
    class SlowSession(FakeSession):
        async def call_tool(self, name, arguments):
            del name, arguments
            await asyncio.sleep(1)

    @asynccontextmanager
    async def factory(config):
        del config
        yield SlowSession()

    bridge = McpToolPlugin(
        (
            McpServerConfig(
                name="drive",
                protocol="stdio",
                command="mcp",
                timeout_seconds=0.01,
            ),
        ),
        session_factory=factory,
    )
    tool = (await bridge.list_tools(run_id="run_1"))[0]
    call = ToolCall(
        tool_call_id="call_1",
        tool_name=tool.name,
        arguments={"query": "report"},
        operation_id="operation_1",
        idempotency_key="timeout",
        owner_run_id="run_1",
    )

    with pytest.raises(SageV2Error) as caught:
        await bridge.execute(call, CONTEXT)

    assert caught.value.info.code == "mcp.result_timeout"
    assert caught.value.info.category == ErrorCategory.UNCERTAIN_SIDE_EFFECT
    assert caught.value.info.metadata["mcp_result_received"] is False
    assert caught.value.info.metadata["transport_failure"] == "timeout"
    assert "0.01 seconds" in caught.value.info.message


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
    assert {value.info.code for value in failures} == {"mcp.result_not_received"}


@pytest.mark.asyncio
async def test_mcp_invalid_received_result_wakes_all_waiters_without_redispatch():
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingSession(FakeSession):
        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            started.set()
            await release.wait()
            return {"content": [{"type": "text", "text": "found"}]}

    class InvalidProjectionBridge(McpToolPlugin):
        @staticmethod
        def _content(response):
            del response
            raise ValueError("invalid result projection")

    session = BlockingSession()

    @asynccontextmanager
    async def factory(config):
        del config
        yield session

    bridge = InvalidProjectionBridge(
        (McpServerConfig(name="drive", protocol="stdio", command="mcp"),),
        session_factory=factory,
    )
    tool = (await bridge.list_tools(run_id="run_1"))[0]
    call = ToolCall(
        tool_call_id="call_1",
        tool_name=tool.name,
        arguments={"query": "report"},
        operation_id="operation_1",
        idempotency_key="invalid-result",
        owner_run_id="run_1",
    )

    first = asyncio.create_task(bridge.execute(call, CONTEXT))
    await started.wait()
    second = asyncio.create_task(bridge.execute(call, CONTEXT))
    await asyncio.sleep(0)
    release.set()
    failures = await asyncio.wait_for(
        asyncio.gather(first, second, return_exceptions=True), timeout=1
    )

    assert session.calls == [("search files", {"query": "report"})]
    assert all(isinstance(value, SageV2Error) for value in failures)
    assert {value.info.code for value in failures} == {"mcp.result_invalid"}
    assert all(
        value.info.category == ErrorCategory.PROVIDER_PERMANENT
        and value.info.metadata["mcp_result_received"] is True
        for value in failures
    )
    with pytest.raises(SageV2Error) as replayed:
        await bridge.execute(call, CONTEXT)
    assert replayed.value.info.code == "mcp.result_invalid"
    assert session.calls == [("search files", {"query": "report"})]


@pytest.mark.asyncio
async def test_mcp_error_return_is_the_authoritative_failed_result():
    class ErrorSession(FakeSession):
        async def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            return {
                "content": [{"type": "text", "text": "remote rejected request"}],
                "isError": True,
            }

    session = ErrorSession()

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
        idempotency_key="returned-error",
        owner_run_id="run_1",
    )

    result = await bridge.execute(call, CONTEXT)
    reconciled = await bridge.reconcile(call.operation_id, CONTEXT)

    assert result.error is not None
    assert result.error.code == "mcp.tool_error"
    assert result.error.metadata["mcp_result_received"] is True
    assert reconciled.state.value == "failed"
    assert reconciled.result == result


def test_mcp_api_key_is_redacted_by_the_persistable_contract():
    config = McpServerConfig(
        name="drive",
        protocol="streamable_http",
        url="https://mcp.test",
        api_key="super-secret",
    )

    assert "super-secret" not in repr(config)
    assert config.model_dump(mode="json")["api_key"] == "**********"
