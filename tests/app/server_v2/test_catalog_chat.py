import pytest
from fastapi.testclient import TestClient

from app.server_v2.app import create_app
from tests.app.server_v2.conftest import (
    make_test_service,
    register_and_login,
    scripted_hello,
)
from tests.app.server_v2.test_agui_chat import _run_input


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
