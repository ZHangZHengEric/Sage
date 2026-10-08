"""AnyTool runs without either Sage runtime and preserves MCP/wire contracts."""
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from mcp_servers.anytool.anytool_runtime import generate_anytool_result
from mcp_servers.anytool import model_client

ROOT = Path(__file__).resolve().parents[2]


def test_import_without_sage():
    result = subprocess.run([sys.executable, "-c", """
import importlib.abc, sys
class BlockSage(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'sagents', 'common', 'app'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, BlockSage())
from mcp_servers.anytool import anytool_runtime, anytool_server, model_client, __main__
"""], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol, path, response", [
    ("openai-chat-completions", "/v1/chat/completions", {"choices": [{"message": {"content": '{"ok":true}'}}]}),
    ("openai-responses", "/v1/responses", {"output": [{"content": [{"type": "output_text", "text": '{"ok":true}'}]}]}),
    ("anthropic-messages", "/v1/messages", {"content": [{"type": "text", "text": '{"ok":true}'}]}),
    ("gemini-generate-content", "/v1/models/test:generateContent", {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": '{"ok":true}'}]}, "finishReason": "STOP"}]}),
])
async def test_model_wire_and_result(monkeypatch, protocol, path, response):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response)
    original = httpx.AsyncClient
    monkeypatch.setattr(model_client.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = await generate_anytool_result(
        server_name="demo", tool_def={"name": "lookup"},
        arguments={"query": "hello", "user_id": "hidden", "session_id": "hidden"},
        server_config={"simulator": {"protocol": protocol, "model": "test", "base_url": "https://example.com/v1", "api_key": "test-key"}},
    )
    assert result["parsed"] == {"ok": True}
    assert result["arguments"] == {"query": "hello"}
    assert len(requests) == 1
    assert requests[0].url.path == path
    payload = json.loads(requests[0].content)
    assert "hidden" not in requests[0].content.decode()
    if protocol == "gemini-generate-content":
        assert requests[0].headers["x-goog-api-key"] == "test-key"
        assert payload["generationConfig"]["responseMimeType"] == "application/json"
        assert "systemInstruction" in payload
    elif protocol == "anthropic-messages":
        assert payload["model"] == "test"
        assert requests[0].headers["x-api-key"] == "test-key"
        assert "system" in payload and "response_format" not in payload
    elif protocol == "openai-responses":
        assert payload["text"] == {"format": {"type": "json_object"}}
    else:
        assert payload["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_standalone_stdio_lists_tools(tmp_path):
    config = tmp_path / "anytool.json"
    config.write_text(json.dumps({"tools": [{"name": "lookup", "parameters": {"type": "object"}}]}))
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_servers.anytool", str(config)], cwd=str(ROOT))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            listed = await client.list_tools()
            assert [tool.name for tool in listed.tools] == ["lookup"]
            # A missing configuration is an MCP error, not a hidden v1 fallback.
            result = await client.call_tool("lookup", {})
            assert result.isError
            assert "simulator" in result.content[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("status, expected_calls", [(400, 2), (401, 1), (500, 1)])
async def test_json_fallback_does_not_retry_auth_or_server_errors(monkeypatch, status, expected_calls):
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(status, json={"error": "rejected"})
        assert "response_format" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(model_client.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    kwargs = dict(server_name="demo", tool_def={"name": "lookup"}, arguments={}, server_config={"simulator": {"api_key": "key", "base_url": "https://example.com/v1", "model": "test"}})
    if status == 400:
        assert (await generate_anytool_result(**kwargs))["parsed"] == {}
    else:
        with pytest.raises(httpx.HTTPStatusError):
            await generate_anytool_result(**kwargs)
    assert len(requests) == expected_calls
