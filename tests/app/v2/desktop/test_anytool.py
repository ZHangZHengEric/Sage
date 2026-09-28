"""The v2 HTTP host supplies its own model config to the independent MCP."""
import json

import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.v2.desktop.backend.anytool import DesktopV2AnyToolApp
from app.v2.desktop.backend.catalog import JsonDesktopCatalogStore, DesktopMcpRecord, DesktopModelProviderRecord
from mcp_servers.anytool import model_client


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [False, True])
async def test_mcp_call_uses_v2_catalog_or_explicit_simulator(tmp_path, monkeypatch, explicit):
    catalog = JsonDesktopCatalogStore(tmp_path / "catalog.json")
    await catalog.save_model_provider(DesktopModelProviderRecord(
        id="model", user_id="default_user", name="Model", model="catalog-model",
        protocol="openai-responses", base_url="https://catalog.example/v1", api_key="catalog-key", is_default=True,
    ))
    simulator = {"model": "explicit-model", "api_key": "explicit-key", "base_url": "https://explicit.example/v1"} if explicit else {}
    await catalog.save_mcp(DesktopMcpRecord(
        user_id="default_user", name="AnyTool", protocol="streamable_http", kind="anytool",
        tools=({"name": "lookup", "returns": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}},),
        simulator=simulator,
    ))
    requests = []
    def handler(request):
        requests.append(request)
        payload = json.loads(request.content)
        assert payload["model"] == ("explicit-model" if explicit else "catalog-model")
        assert request.headers["authorization"] == ("Bearer explicit-key" if explicit else "Bearer catalog-key")
        if explicit:
            assert request.url.path == "/v1/chat/completions"
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true,"extra":"drop"}'}}]})
        assert request.url.path == "/v1/responses"
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": '{"ok":true,"extra":"drop"}'}]}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(model_client.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    app = Starlette(routes=[Mount("/mcp", DesktopV2AnyToolApp(catalog))])
    with TestClient(app) as client:
        response = client.post("/mcp/AnyTool", headers={"Accept": "application/json, text/event-stream"}, json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "lookup", "arguments": {"user_id": "other-user"}},
        })
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError"), result
    assert result["structuredContent"] == {"ok": True}
    assert len(requests) == 1
