"""Exercise the example through the real Sage bridge and MCP SDK transport."""
from __future__ import annotations

import json

import httpx
import pytest
from mcp.client.streamable_http import streamablehttp_client

from examples import sagents_v2_parallel_search as example


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_error", [False, True])
async def test_anonymous_example_dispatch_and_cleanup(monkeypatch, capsys, tool_error):
    requests = []
    clients = []
    released = []

    def handle(request):
        requests.append(request)
        assert str(request.url) == example.ENDPOINT
        assert request.headers["User-Agent"] == example.USER_AGENT
        assert "Authorization" not in request.headers
        if request.method != "POST":
            return httpx.Response(405)
        message = json.loads(request.content)
        method = message["method"]
        if "id" not in message:
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "inputSchema": {"type": "object"}}
                for name in ("web_search", "web_fetch")
            ]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "https://example.org source excerpt"}],
                      "isError": tool_error}
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def client_factory(headers=None, timeout=None, auth=None):
        client = httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth,
                                   transport=httpx.MockTransport(handle))
        clients.append(client)
        return client

    def transport(*args, **kwargs):
        return streamablehttp_client(*args, **kwargs, httpx_client_factory=client_factory)

    plugin = example.create_plugin()
    original_release = plugin.release_run

    async def release(run_id):
        released.append(run_id)
        await original_release(run_id)

    monkeypatch.setenv("PARALLEL_API_KEY", "must-not-be-used")
    monkeypatch.setattr(example, "streamablehttp_client", transport)
    monkeypatch.setattr(example, "create_plugin", lambda: plugin)
    monkeypatch.setattr(plugin, "release_run", release)
    if tool_error:
        with pytest.raises(RuntimeError, match="source excerpt"):
            await example.run("Python asyncio TaskGroup documentation", "https://example.org")
    else:
        await example.run("Python asyncio TaskGroup documentation", "https://example.org")
    calls = [json.loads(r.content)["params"] for r in requests
             if r.method == "POST" and json.loads(r.content)["method"] == "tools/call"]
    assert calls[0]["name"] == "web_search"
    assert calls[0]["arguments"]["objective"] == "Python asyncio TaskGroup documentation"
    assert calls[0]["arguments"]["search_queries"] == ["Python asyncio TaskGroup documentation"]
    if not tool_error:
        assert calls[1]["name"] == "web_fetch"
        assert calls[1]["arguments"]["urls"] == ["https://example.org"]
        assert calls[0]["arguments"]["session_id"] == calls[1]["arguments"]["session_id"]
    else:
        assert len(calls) == 1
    assert "source excerpt" in capsys.readouterr().out
    assert released and not plugin._results
    assert all(client.is_closed for client in clients)
