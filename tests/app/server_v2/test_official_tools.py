from fastapi.testclient import TestClient

from app.server_v2.app import create_app
from app.server_v2.services.official import DEFAULT_OFFICIAL_TOOLS
from tests.app.server_v2.conftest import (
    make_test_service,
    register_and_login,
    scripted_hello,
)
from tests.app.server_v2.test_agui_chat import _run_input


def test_list_official_tools(client):
    token = register_and_login(client)
    response = client.get(
        "/api/tools", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    names = {item["name"] for item in response.json()["data"]}
    assert "file_read" in names
    assert "execute_shell_command" in names
    defaults = {
        item["name"] for item in response.json()["data"] if item["default"]
    }
    assert defaults == set(DEFAULT_OFFICIAL_TOOLS)


def test_agui_run_exposes_official_file_tools(tmp_path):
    provider = scripted_hello()
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        response = client.post(
            "/api/agent",
            json=_run_input(),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

    assert provider.requests
    names = {tool.name for tool in provider.requests[0].tools}
    assert "file_read" in names
    assert "execute_shell_command" in names
