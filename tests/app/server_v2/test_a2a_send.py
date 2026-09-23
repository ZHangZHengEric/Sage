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


def send(client: TestClient, api_key: str, text: str, **message) -> dict:
    params = {
        "message": {
            "messageId": message.pop("message_id", "msg-1"),
            "role": "ROLE_USER",
            "parts": [{"text": text}],
            **message,
        }
    }
    return rpc(client, api_key, "SendMessage", params)


@pytest.mark.timeout(30)
def test_send_message_runs_the_agent_and_returns_a_completed_task(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    result = send(a2a_client, api_key, "hi there")["result"]

    task = result["task"]
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"
    assert task["id"] and task["contextId"]
    replies = [
        "".join(part.get("text", "") for part in item.get("parts", []))
        for item in task.get("history", [])
        if item.get("role") == "ROLE_AGENT"
    ]
    assert "hello" in replies


@pytest.mark.timeout(30)
def test_get_task_returns_the_same_snapshot_as_the_send_that_created_it(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)
    created = send(a2a_client, api_key, "hi there")["result"]["task"]

    fetched = rpc(a2a_client, api_key, "GetTask", {"id": created["id"]})["result"]

    assert fetched["id"] == created["id"]
    assert fetched["contextId"] == created["contextId"]
    assert fetched["status"]["state"] == created["status"]["state"]
    assert fetched["history"] == created["history"]


@pytest.mark.timeout(30)
def test_a_context_id_keeps_two_messages_in_one_thread(tmp_path):
    with make_a2a_client(tmp_path, steps=2) as client:
        token = register_and_login(client)
        _, api_key = mint_key(client, token)

        first = send(client, api_key, "one", message_id="msg-1")["result"]["task"]
        second = send(
            client,
            api_key,
            "two",
            message_id="msg-2",
            contextId=first["contextId"],
        )["result"]["task"]

    assert second["status"]["state"] == "TASK_STATE_COMPLETED"
    assert second["contextId"] == first["contextId"]
    # Two messages in one context are two Tasks, not one: A2A Tasks are units
    # of work and Sage Runs are too.
    assert second["id"] != first["id"]


@pytest.mark.timeout(30)
def test_a_model_failure_becomes_a_failed_task_not_a_transport_error(a2a_client):  # noqa: F811
    """A2A 1.0 has no error field on TaskStatus, so the code rides metadata."""

    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)
    send(a2a_client, api_key, "one", message_id="msg-1")

    # The scripted model has no second response, so this run fails inside the
    # agent rather than at the transport.
    task = send(a2a_client, api_key, "two", message_id="msg-2")["result"]["task"]

    assert task["status"]["state"] == "TASK_STATE_FAILED"
    assert task["status"]["message"]["parts"][0]["text"]
    assert task["metadata"]["sage.errorCode"] == "model.script_exhausted"


@pytest.mark.timeout(30)
def test_unknown_task_id_is_a_task_not_found_error(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    body = rpc(a2a_client, api_key, "GetTask", {"id": "run_missing"})

    assert body["error"]["code"] == -32001


@pytest.mark.timeout(30)
def test_a_message_with_no_usable_content_is_invalid_params(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    body = rpc(
        a2a_client,
        api_key,
        "SendMessage",
        {"message": {"messageId": "msg-1", "role": "ROLE_USER", "parts": []}},
    )

    assert body["error"]["code"] == -32602
