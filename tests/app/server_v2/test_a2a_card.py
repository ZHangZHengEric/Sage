from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.server_v2.bootstrap.app import create_app
from tests.app.server_v2.conftest import (
    make_test_service,
    register_and_login,
    scripted_hello,
)

A2A_HEADERS = {"A2A-Version": "1.0"}


def mint_key(client: TestClient, token: str, *, scopes=None) -> tuple[str, str]:
    """Create an Agent and an API key bound to it. Returns (agent_id, api_key)."""

    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/agents",
        json={"name": "Peer", "description": "Answers questions for other agents."},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    agent_id = created.json()["data"]["id"]
    body: dict[str, object] = {"agent_id": agent_id, "name": "peer key"}
    if scopes is not None:
        body["scopes"] = scopes
    issued = client.post("/api/keys", json=body, headers=headers)
    assert issued.status_code == 200, issued.text
    return agent_id, issued.json()["data"]["api_key"]


def rpc(client: TestClient, api_key: str, method: str, params: dict) -> dict:
    response = client.post(
        "/a2a/v1",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={"Authorization": f"Bearer {api_key}", **A2A_HEADERS},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def a2a_client(tmp_path):
    with make_a2a_client(tmp_path) as client:
        yield client


def make_a2a_client(tmp_path, *, steps: int = 1, **overrides):
    """A TestClient whose model answers ``steps`` times before running dry."""

    service = make_test_service(
        tmp_path, model_provider=scripted_hello(steps), **overrides
    )
    return TestClient(create_app(service=service))


@pytest.mark.timeout(30)
def test_agent_card_describes_the_key_s_agent(a2a_client):
    token = register_and_login(a2a_client)
    agent_id, api_key = mint_key(a2a_client, token)

    response = a2a_client.get(
        "/.well-known/agent-card.json",
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "Peer"
    assert card["skills"][0]["id"] == agent_id
    interface = card["supportedInterfaces"][0]
    assert interface["protocolBinding"] == "JSONRPC"
    assert interface["protocolVersion"] == "1.0"
    assert interface["url"].endswith("/a2a/v1")
    assert card["capabilities"]["pushNotifications"] is False


@pytest.mark.timeout(30)
def test_agent_card_is_not_served_anonymously(a2a_client):
    """The well-known path is authenticated because the host is multi-tenant."""

    register_and_login(a2a_client)
    assert a2a_client.get("/.well-known/agent-card.json").status_code == 401


@pytest.mark.timeout(30)
def test_public_base_url_overrides_the_request_host(tmp_path):
    with make_a2a_client(
        tmp_path, public_base_url="https://agents.example.com"
    ) as client:
        token = register_and_login(client)
        _, api_key = mint_key(client, token)
        card = client.get(
            "/a2a/v1/card", headers={"Authorization": f"Bearer {api_key}"}
        ).json()

    assert card["supportedInterfaces"][0]["url"] == (
        "https://agents.example.com/a2a/v1"
    )
