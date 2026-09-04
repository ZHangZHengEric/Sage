from fastapi.testclient import TestClient

from app.server_v2.app import create_app
from tests.app.server_v2.conftest import (
    make_test_service,
    register_and_login,
    scripted_hello,
)
from tests.app.server_v2.test_agui_chat import _run_input


import pytest


@pytest.mark.timeout(30)
def test_agui_run_sees_bound_skill_without_workspace_copy(tmp_path):
    provider = scripted_hello()
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        client.post(
            "/api/skills",
            json={
                "name": "demo",
                "content": "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
            },
            headers=headers,
        )
        client.put("/api/agents/main/skills", json={"names": ["demo"]}, headers=headers)
        response = client.post("/api/agent", json=_run_input(), headers=headers)
        assert response.status_code == 200

    assert provider.requests
    rendered = "\n".join(
        block.text
        for request in provider.requests
        for message in request.messages
        for block in message.content
        if getattr(block, "text", None)
    )
    assert "<available_skills>" in rendered
    assert "demo" in rendered
    assert not (tmp_path / "tenants").exists() or not any(
        tmp_path.joinpath("tenants").rglob("skills/demo")
    )
