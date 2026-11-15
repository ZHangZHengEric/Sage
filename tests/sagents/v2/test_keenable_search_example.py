"""Exercise the Keenable example through the real Sage bridge and MCP SDK transport.

All MCP traffic goes to an httpx.MockTransport; no live network calls.
"""
from __future__ import annotations

import json

import httpx
import pytest
from mcp.client.streamable_http import streamablehttp_client

from examples.v2 import keenable_search as example

SECRET = "kn-test-secret-value"
SESSION_PROP = {"session_id": {"type": "string", "maxLength": 128}}
SEARCH_SCHEMA = {"type": "object", "required": ["query"],
                 "properties": {"query": {"type": "string"}, **SESSION_PROP}}
FETCH_SCHEMA = {"type": "object", "required": ["url"],
                "properties": {"url": {"type": "string"}, **SESSION_PROP}}


def _install(monkeypatch, plugin_kwargs, *, tools=None, tool_error=False):
    """Route the example's MCP transport to a fixture server and record traffic."""
    if tools is None:
        tools = {"search_web_pages": SEARCH_SCHEMA, "fetch_page_content": FETCH_SCHEMA}
    state = {"requests": [], "clients": [], "released": []}

    def handle(request):
        state["requests"].append(request)
        if request.method != "POST":
            return httpx.Response(405)
        message = json.loads(request.content)
        if "id" not in message:
            return httpx.Response(202)
        method = message["method"]
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "fixture", "version": "1"}}
        elif method == "tools/list":
            result = {"tools": [{"name": name, "inputSchema": schema}
                                for name, schema in tools.items()]}
        elif method == "tools/call":
            result = {"content": [{"type": "text", "text": "https://example.org source excerpt"}],
                      "isError": tool_error}
        else:
            raise AssertionError(method)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    def client_factory(headers=None, timeout=None, auth=None):
        client = httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth,
                                   transport=httpx.MockTransport(handle))
        state["clients"].append(client)
        return client

    def transport(*args, **kwargs):
        return streamablehttp_client(*args, **kwargs, httpx_client_factory=client_factory)

    plugin = example.create_plugin(**plugin_kwargs)
    original_release = plugin.release_run

    async def release(run_id):
        state["released"].append(run_id)
        await original_release(run_id)

    monkeypatch.setattr(example, "streamablehttp_client", transport)
    monkeypatch.setattr(example, "create_plugin", lambda api_key=None: plugin)
    monkeypatch.setattr(plugin, "release_run", release)
    state["plugin"] = plugin
    return state


def _calls(state):
    return [json.loads(r.content)["params"] for r in state["requests"]
            if r.method == "POST" and json.loads(r.content)["method"] == "tools/call"]


def _assert_cleaned_up(state):
    assert state["released"] and not state["plugin"]._results
    assert all(client.is_closed for client in state["clients"])


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_error", [False, True])
async def test_public_mode_dispatch_and_cleanup(monkeypatch, capsys, tool_error):
    monkeypatch.setenv("KEENABLE_API_KEY", "must-not-be-read-by-run")
    state = _install(monkeypatch, {}, tool_error=tool_error)
    if tool_error:
        with pytest.raises(RuntimeError, match="source excerpt"):
            await example.run("Python asyncio TaskGroup documentation", "https://example.org")
    else:
        await example.run("Python asyncio TaskGroup documentation", "https://example.org")

    for request in state["requests"]:
        assert str(request.url) == example.PUBLIC_ENDPOINT
        assert request.headers["User-Agent"] == example.USER_AGENT
        assert example.API_KEY_HEADER not in request.headers
        assert "Authorization" not in request.headers
    calls = _calls(state)
    assert calls[0]["name"] == "search_web_pages"
    assert calls[0]["arguments"]["query"] == "Python asyncio TaskGroup documentation"
    if tool_error:
        assert len(calls) == 1
    else:
        assert calls[1]["name"] == "fetch_page_content"
        assert calls[1]["arguments"]["url"] == "https://example.org"
        assert calls[0]["arguments"]["session_id"] == calls[1]["arguments"]["session_id"]
    assert "source excerpt" in capsys.readouterr().out
    _assert_cleaned_up(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_error", [False, True])
async def test_keyed_mode_sends_header_and_keeps_secret_out_of_output(
    monkeypatch, capsys, tool_error,
):
    state = _install(monkeypatch, {"api_key": SECRET}, tool_error=tool_error)
    assert state["plugin"].servers[0].url == example.KEYED_ENDPOINT
    error = None
    try:
        await example.run("query", None, api_key=SECRET)
    except RuntimeError as exc:
        error = str(exc)
    assert (error is not None) == tool_error

    assert state["requests"]
    for request in state["requests"]:
        assert str(request.url) == example.KEYED_ENDPOINT
        assert request.headers[example.API_KEY_HEADER] == SECRET
        assert "Authorization" not in request.headers
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err
    assert SECRET not in (error or "")
    assert SECRET not in repr(state["plugin"].servers[0])
    _assert_cleaned_up(state)


@pytest.mark.asyncio
async def test_missing_tool_fails_and_cleans_up(monkeypatch):
    state = _install(monkeypatch, {}, tools={"search_web_pages": SEARCH_SCHEMA})
    with pytest.raises(RuntimeError, match=example.FETCH_TOOL):
        await example.run("query", "https://example.org")
    assert [c["name"] for c in _calls(state)] == ["search_web_pages"]
    _assert_cleaned_up(state)


@pytest.mark.asyncio
async def test_session_id_only_sent_when_schema_declares_it(monkeypatch):
    plain = {"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}}
    state = _install(monkeypatch, {}, tools={"search_web_pages": plain})
    await example.run("query")
    (call,) = _calls(state)
    assert call["arguments"] == {"query": "query"}
    _assert_cleaned_up(state)


def test_create_plugin_selects_endpoint_by_key():
    assert example.create_plugin().servers[0].url == example.PUBLIC_ENDPOINT
    assert example.create_plugin().servers[0].api_key is None
    keyed = example.create_plugin(SECRET).servers[0]
    assert keyed.url == example.KEYED_ENDPOINT
    assert SECRET not in keyed.model_dump_json()
