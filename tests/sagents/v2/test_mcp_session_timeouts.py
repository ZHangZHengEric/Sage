"""Transport read deadlines must not reintroduce SDK limits on long tools."""

import asyncio
from contextlib import asynccontextmanager

import pytest

from sagents.v2.tool.plugins._shared.mcp_session import sdk_session
from sagents.v2.tool.plugins.mcp import McpServerConfig


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["sse", "streamable_http"])
@pytest.mark.parametrize("deadline", [None, 7200])
async def test_sdk_transport_read_timeout_matches_execution_policy(monkeypatch, protocol, deadline):
    import httpx
    import mcp
    import mcp.client.sse
    import mcp.client.streamable_http

    observed = {}

    @asynccontextmanager
    async def transport(url, **kwargs):
        observed.update(kwargs)
        # Both SDK transports build this HTTPX timeout, including for a JSON
        # response to a long-running POST rather than only for SSE events.
        timeout = httpx.Timeout(kwargs["timeout"], read=kwargs["sse_read_timeout"])
        assert timeout.connect == 30
        assert timeout.read == (7200 if deadline is None else deadline)
        yield (None, None) if protocol == "sse" else (None, None, lambda: None)

    @asynccontextmanager
    async def session(read, write):
        class Session:
            async def initialize(self):
                pass

        yield Session()

    monkeypatch.setattr(mcp, "ClientSession", session)
    monkeypatch.setattr(mcp.client.sse, "sse_client", transport)
    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", transport)
    async with sdk_session(McpServerConfig(
        name="long-work", protocol=protocol, url="http://127.0.0.1/mcp",
        call_timeout_seconds=deadline,
    )):
        pass
    assert observed["sse_read_timeout"] == (7200 if deadline is None else deadline)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 0, -1])
def test_call_timeout_must_be_finite_and_positive(value):
    with pytest.raises(ValueError):
        McpServerConfig(name="bounded", protocol="sse", url="https://example.test", call_timeout_seconds=value)


def test_default_call_timeout_is_two_hours_and_can_be_overridden():
    assert McpServerConfig(name="default", protocol="sse", url="https://example.test").call_timeout_seconds == 7200
    assert McpServerConfig(name="custom", protocol="sse", url="https://example.test", call_timeout_seconds=14400).call_timeout_seconds == 14400


@pytest.mark.asyncio
async def test_sdk_initialization_stays_bounded_without_execution_deadline(monkeypatch):
    import mcp
    import mcp.client.sse

    @asynccontextmanager
    async def transport(*args, **kwargs):
        yield None, None

    @asynccontextmanager
    async def session(*args):
        class Session:
            async def initialize(self):
                await asyncio.Event().wait()

        yield Session()

    monkeypatch.setattr(mcp, "ClientSession", session)
    monkeypatch.setattr(mcp.client.sse, "sse_client", transport)
    with pytest.raises(TimeoutError):
        async with sdk_session(McpServerConfig(
            name="unresponsive", protocol="sse", url="http://127.0.0.1/mcp",
            timeout_seconds=0.01,
        )):
            pytest.fail("uninitialized session was exposed")


@pytest.mark.asyncio
async def test_real_http_sdk_waits_for_long_json_tool_response(monkeypatch):
    import json

    import httpx
    import mcp.client.streamable_http

    original = mcp.client.streamable_http.streamablehttp_client

    async def handle(request):
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        if message["method"] == "initialize":
            result = {
                "protocolVersion": message["params"]["protocolVersion"],
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "slow", "version": "1"},
            }
        elif message["method"] == "tools/list":
            result = {"tools": [{"name": "generate", "inputSchema": {"type": "object"}}]}
        else:
            await asyncio.sleep(0.1)
            # Inspect the actual timeout on the SDK's tool POST, rather than
            # only checking the arguments passed into its transport factory.
            assert request.extensions["timeout"]["read"] == 7200
            result = {"content": [{"type": "text", "text": "done"}]}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def client_factory(**kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(handle), **kwargs)

    def transport(*args, **kwargs):
        return original(*args, **kwargs, httpx_client_factory=client_factory)

    monkeypatch.setattr(mcp.client.streamable_http, "streamablehttp_client", transport)
    async with sdk_session(McpServerConfig(
        name="slow", protocol="streamable_http", url="http://127.0.0.1/mcp",
        timeout_seconds=5,
    )) as session:
        result = await session.call_tool("generate", {})
        assert result.content[0].text == "done"
