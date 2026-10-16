"""External user IDs are accepted only from an authenticated Agent caller."""
import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from tests.app.v2.server.test_external_chat import make_host, setup_agent


@pytest.mark.parametrize("method,suffix,body", [
    ("POST", "/runs", {"threadId": "t", "runId": "r", "messages": []}),
    ("GET", "/runs/t/r", None),
    ("GET", "/runs/t/r/files", None),
    ("POST", "/runs/t/r/cancel", None),
    ("POST", "/runs/t/r/reply", {"interaction_id": "i", "decision": "approve_once"}),
    ("PUT", "/workspace/files", {"directory": "projects/p", "files": {}}),
    ("DELETE", "/workspace/files?path=projects/p&recursive=true", None),
    ("DELETE", "/sessions/t", None),
])
def test_external_routes_require_machine_credential(tmp_path, method, suffix, body):
    with TestClient(create_app(make_host(tmp_path))) as client:
        token = setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        del client.headers["Authorization"]
        url = f"/api/agents/{agent}{suffix}"
        for authorization in (None, "Bearer invalid", f"Bearer {token}"):
            headers = {"SAGE-TENANT-ID": "wishseen-user"}
            if authorization:
                headers["Authorization"] = authorization
            response = client.request(method, url, headers=headers, json=body)
            assert response.status_code == 401, response.text


def test_external_keys_enforce_agent_scopes_revocation_and_owner(tmp_path):
    with TestClient(create_app(make_host(tmp_path))) as client:
        token = setup_agent(client)
        agent = client.headers["SAGE-AGENT-ID"]
        admin_headers = {"Authorization": f"Bearer {token}"}
        other = client.post("/api/agents", headers=admin_headers,
            json={"name": "Other Agent", "instructions": "hello"}).json()["data"]["id"]
        assert client.get(f"/api/agents/{other}/runs/t/r",
                          headers={"SAGE-TENANT-ID": "alice"}).status_code == 403
        key = client.post("/api/keys", headers=admin_headers,
            json={"agent_id": agent, "name": "read-only", "scopes": ["a2a:read"]}).json()["data"]
        headers = {"SAGE-TENANT-ID": "alice", "Authorization": "Bearer " + key["api_key"]}
        assert client.get(f"/api/agents/{agent}/runs/t/r", headers=headers).status_code == 404
        assert client.put(f"/api/agents/{agent}/workspace/files", headers=headers,
            json={"directory": "projects/p", "files": {}}).status_code == 403
        assert client.post(f"/api/agents/{agent}/runs/t/r/reply", headers=headers,
            json={"interaction_id": "i", "decision": "approve_once"}).status_code == 403
        assert client.post("/api/agent", headers=headers,
            json={"threadId": "t", "runId": "r", "messages": []}).status_code == 403
        assert client.delete(f"/api/keys/{key['key_id']}", headers=admin_headers).status_code == 200
        assert client.get(f"/api/agents/{agent}/runs/t/r", headers=headers).status_code == 401
        assert client.get("/api/threads/t/result", headers=headers).status_code == 401
        assert not (tmp_path / "tenants" / "alice").exists()
