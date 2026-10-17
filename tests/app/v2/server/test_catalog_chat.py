import pytest
from fastapi.testclient import TestClient
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep

from app.v2.server.main import create_app
from tests.app.v2.server.conftest import (
    make_test_service,
    register_and_login,
    scripted_hello,
)
from tests.app.v2.server.test_agui_chat import _parse_sse, _run_input


@pytest.mark.timeout(30)
def test_server_judge_continues_after_intermediate_text(tmp_path):
    def step(text):
        return ScriptedModelStep(
            events=(
                ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id=f"response_{len(text)}",
                        text=text,
                        finish_reason="stop",
                    ),
                ),
            )
        )

    provider = ScriptedModelProvider(
        (
            step("I found the relevant files. I will verify them next."),
            step('{"decision":"continue","reason":"Verification remains."}'),
            step("Verification passed. Here is the answer."),
            step('{"decision":"completed","reason":"The answer is delivered."}'),
        )
    )
    service = make_test_service(tmp_path, model_provider=provider, stub_judge=False)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        response = client.post(
            "/api/agent",
            json=_run_input(),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert _parse_sse(response.text)[-1]["type"] == "RUN_FINISHED"
    assert [request.metadata.get("purpose") for request in provider.requests] == [
        None,
        "continuation_judge",
        None,
        "continuation_judge",
    ]


@pytest.mark.timeout(30)
def test_agui_run_uses_catalog_agent_instructions(tmp_path):
    provider = scripted_hello()
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/agents",
            json={
                "name": "Writer",
                "instructions": "You are the catalog writer agent.",
            },
            headers=headers,
        )
        agent_id = created.json()["data"]["id"]
        payload = _run_input()
        payload["forwardedProps"] = {"agentId": agent_id}
        response = client.post("/api/agent", json=payload, headers=headers)
        assert response.status_code == 200

    assert provider.requests
    rendered = "\n".join(
        block.text
        for request in provider.requests
        for message in request.messages
        for block in message.content
        if getattr(block, "text", None)
    )
    assert "catalog writer agent" in rendered


@pytest.mark.parametrize('scope', [None, [], ['mcp_read'], ['a2a_peer_search']])
def test_agent_external_scope_reaches_the_actual_model_request(tmp_path, monkeypatch, scope):
    from sagents.v2.tool.contracts import ToolDefinition
    from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog

    provider = scripted_hello()
    service = make_test_service(tmp_path, model_provider=provider)
    from app.v2.server.catalog.records import McpServerRecord, A2AAgentRecord
    original_catalog = service.catalog.get
    async def catalog_with_tools(user_id):
        catalog = await original_catalog(user_id)
        catalog.mcp_servers = [McpServerRecord(name='test', url='https://mcp.invalid', tools=['mcp_read'])]
        catalog.a2a_agents = [A2AAgentRecord(name='peer', url='https://peer.invalid', skills=['a2a_peer_search'])]
        return catalog
    monkeypatch.setattr(service.catalog, 'get', catalog_with_tools)
    for cache, name in [(service.mcp_plugins, 'mcp_read'), (service.a2a_plugins, 'a2a_peer_search')]:
        plugin = InMemoryToolCatalog((ToolDefinition(name=name, description=name, input_schema={'type': 'object'}),))
        monkeypatch.setattr(cache, 'get', lambda *args, plugin=plugin, **kwargs: plugin)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        headers = {'Authorization': f'Bearer {token}'}
        config = {'name': 'Scoped', 'tools': ['file_read']}
        if scope is not None:
            config['external_tools'] = scope
        created = client.post('/api/agents', json=config, headers=headers)
        assert created.status_code == 200, created.text
        agent = created.json()['data']
        assert agent['external_tools'] == (scope or [])
        payload = _run_input()
        payload['forwardedProps'] = {'agentId': agent['id']}
        response = client.post('/api/agent', json=payload, headers=headers)
        assert response.status_code == 200, response.text
        assert _parse_sse(response.text)[-1]['type'] == 'RUN_FINISHED', response.text
    assert provider.requests
    names = {tool.name for tool in provider.requests[0].tools}
    assert names & {'mcp_read', 'a2a_peer_search'} == set(scope or [])
    assert 'file_read' in names
