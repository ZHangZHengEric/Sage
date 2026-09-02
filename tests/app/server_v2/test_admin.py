from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.app.server_v2.conftest import register_and_login


def admin_login(client: TestClient) -> str:
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin12345"},
    )
    assert login.status_code == 200
    assert login.json()["data"]["user"]["role"] == "admin"
    return login.json()["data"]["access_token"]


@pytest.mark.timeout(30)
def test_admin_can_see_all_users_threads_and_models(client: TestClient):
    alice = register_and_login(client, "alice")
    run = client.post(
        "/api/agent",
        json={
            "threadId": "thread-alice",
            "runId": "run-alice",
            "messages": [{"id": "m1", "role": "user", "content": "hello"}],
            "forwardedProps": {"agentId": "main"},
        },
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert run.status_code == 200
    saved = client.post(
        "/api/models",
        json={
            "protocol": "openai-chat-completions",
            "base_url": "https://models.example.com/v1",
            "model": "demo-model",
            "api_key": "sk-test",
        },
        headers={"Authorization": f"Bearer {alice}"},
    )
    assert saved.status_code == 200

    admin = admin_login(client)
    headers = {"Authorization": f"Bearer {admin}"}
    users = client.get("/api/admin/users", headers=headers)
    assert {item["username"] for item in users.json()["data"]} >= {"admin", "alice"}
    threads = client.get("/api/admin/threads", headers=headers)
    assert any(item["thread_id"] == "thread-alice" for item in threads.json()["data"])
    models = client.get("/api/admin/models", headers=headers)
    assert any(item["model"] == "demo-model" for item in models.json()["data"])
    hidden = client.get("/api/admin/users", headers={"Authorization": f"Bearer {alice}"})
    assert hidden.status_code == 403


def test_only_one_admin_is_bootstrapped(client: TestClient):
    register = client.post(
        "/api/auth/register",
        json={"username": "admin", "password": "secret1"},
    )
    assert register.status_code == 409
    login = client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin12345"},
    )
    assert login.json()["data"]["user"]["role"] == "admin"
