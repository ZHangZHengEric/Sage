from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.app.server_v2.conftest import register_and_login
from tests.app.server_v2.test_a2a_card import (  # noqa: F401
    a2a_client,
    make_a2a_client,
    mint_key,
    rpc,
)
from tests.app.server_v2.test_a2a_send import send


def post_rpc(client: TestClient, headers: dict, method: str, params: dict):
    return client.post(
        "/a2a/v1",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        headers={"A2A-Version": "1.0", **headers},
    )


@pytest.mark.timeout(30)
def test_the_rpc_endpoint_rejects_a_request_with_no_api_key(a2a_client):  # noqa: F811
    register_and_login(a2a_client)

    response = post_rpc(a2a_client, {}, "GetTask", {"id": "run_1"})

    assert response.status_code == 401


@pytest.mark.timeout(30)
def test_a_garbage_or_revoked_key_is_rejected(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)
    headers = {"Authorization": f"Bearer {api_key}"}
    key_id = api_key.split(".")[1]

    assert post_rpc(
        a2a_client, {"Authorization": "Bearer nonsense"}, "GetTask", {"id": "x"}
    ).status_code == 401

    revoked = a2a_client.delete(
        f"/api/keys/{key_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert revoked.status_code == 200
    assert post_rpc(a2a_client, headers, "GetTask", {"id": "x"}).status_code == 401


@pytest.mark.timeout(30)
def test_a_read_only_key_cannot_start_a_run(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token, scopes=["a2a:read"])

    response = post_rpc(
        a2a_client,
        {"Authorization": f"Bearer {api_key}"},
        "SendMessage",
        {
            "message": {
                "messageId": "msg-1",
                "role": "ROLE_USER",
                "parts": [{"text": "hi"}],
            }
        },
    )

    assert response.status_code == 403


@pytest.mark.timeout(30)
def test_a_tenant_forged_in_the_request_body_is_ignored(tmp_path):
    """The SDK copies ``params.tenant`` onto the call context verbatim.

    That field is attacker-controlled, so naming another user there must not
    move the Run into their data. The Run has to land in the key owner's
    tenant, and the victim must not be able to see it.
    """

    with make_a2a_client(tmp_path, steps=2) as client:
        victim_token = register_and_login(client, "victim")
        attacker_token = register_and_login(client, "attacker")
        victim_user_id = client.get(
            "/api/auth/session", headers={"Authorization": f"Bearer {victim_token}"}
        ).json()["data"]["user_id"]
        _, attacker_key = mint_key(client, attacker_token)

        forged = client.post(
            "/a2a/v1",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "SendMessage",
                "params": {
                    "tenant": victim_user_id,
                    "message": {
                        "messageId": "msg-1",
                        "role": "ROLE_USER",
                        "parts": [{"text": "exfiltrate"}],
                    },
                },
            },
            headers={
                "Authorization": f"Bearer {attacker_key}",
                "A2A-Version": "1.0",
            },
        )
        assert forged.status_code == 200
        task = forged.json()["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"

        # The Run must be owned by the attacker in the session store too, not
        # just in the host thread index: the attacker can read it back and the
        # victim, holding their own key, cannot.
        _, victim_key = mint_key(client, victim_token)
        _, attacker_read_key = mint_key(client, attacker_token, scopes=["a2a:read"])
        assert rpc(client, attacker_read_key, "GetTask", {"id": task["id"]})["result"]
        assert (
            rpc(client, victim_key, "GetTask", {"id": task["id"]})["error"]["code"]
            == -32001
        )

        victim_threads = client.get(
            "/api/threads", headers={"Authorization": f"Bearer {victim_token}"}
        ).json()["data"]
        attacker_threads = client.get(
            "/api/threads", headers={"Authorization": f"Bearer {attacker_token}"}
        ).json()["data"]

    assert [item["thread_id"] for item in victim_threads] == []
    assert task["contextId"] in [item["thread_id"] for item in attacker_threads]


@pytest.mark.timeout(30)
def test_one_tenant_cannot_read_another_tenant_s_task(tmp_path):
    with make_a2a_client(tmp_path, steps=2) as client:
        owner_token = register_and_login(client, "owner")
        other_token = register_and_login(client, "other")
        _, owner_key = mint_key(client, owner_token)
        _, other_key = mint_key(client, other_token)
        task_id = send(client, owner_key, "private")["result"]["task"]["id"]

        mine = rpc(client, owner_key, "GetTask", {"id": task_id})
        theirs = rpc(client, other_key, "GetTask", {"id": task_id})

    assert mine["result"]["id"] == task_id
    assert theirs["error"]["code"] == -32001


@pytest.mark.timeout(30)
def test_a_key_cannot_reach_another_agent_of_the_same_owner(tmp_path):
    """The Agent is bound to the credential, not chosen per request."""

    with make_a2a_client(tmp_path, steps=2) as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        bound_agent_id, api_key = mint_key(client, token)
        other = client.post(
            "/api/agents",
            json={"name": "Secret", "instructions": "You are the secret agent."},
            headers=headers,
        )
        other_agent_id = other.json()["data"]["id"]
        assert other_agent_id != bound_agent_id

        task = send(client, api_key, "hi")["result"]["task"]
        threads = client.get("/api/threads", headers=headers).json()["data"]

    thread = next(
        item for item in threads if item["thread_id"] == task["contextId"]
    )
    assert thread["agent_id"] == bound_agent_id
