from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from sagents.v2.contracts.items import UsageSummary
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelRequest,
    ModelResponse,
    ModelStreamEvent,
)
from tests.app.server_v2.conftest import register_and_login
from tests.app.server_v2.test_a2a_card import (  # noqa: F401
    A2A_HEADERS,
    a2a_client,
    make_a2a_client,
    mint_key,
    rpc,
)
from tests.app.server_v2.test_a2a_send import send

# Long enough that a request handled while the model is still answering is
# unambiguously not waiting for it, short enough not to slow the suite down.
_MODEL_DELAY = 0.5


class SlowModelProvider:
    """A model that takes measurable time, so "did not wait" is observable.

    ``ScriptedModelProvider`` answers within the same event-loop turn, which
    makes a Run terminal before the request that started it can look at it. The
    non-blocking paths — ``returnImmediately``, ``CancelTask`` on a live Run —
    cannot be told apart from the blocking ones without a model that is still
    thinking when the response is written.
    """

    def __init__(self, *, delay: float = _MODEL_DELAY) -> None:
        self._delay = delay

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=False,
            supports_reasoning=False,
            supports_multimodal_input=False,
            supports_structured_output=False,
        )

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        await asyncio.sleep(self._delay)
        yield ModelStreamEvent(kind=ModelEventKind.TEXT_DELTA, delta="hello")
        yield ModelStreamEvent(
            kind=ModelEventKind.COMPLETED,
            response=ModelResponse(
                response_id="response_slow",
                text="hello",
                finish_reason="stop",
                usage=UsageSummary(input_tokens=3, output_tokens=1),
            ),
        )

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        return self._stream(request)


def stream_events(client: TestClient, api_key: str, method: str, params: dict) -> list:
    """Collect one JSON-RPC streaming response as a list of result payloads."""

    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    headers = {"Authorization": f"Bearer {api_key}", **A2A_HEADERS}
    with client.stream("POST", "/a2a/v1", json=body, headers=headers) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        return [
            json.loads(line[len("data:") :])
            for line in response.iter_lines()
            if line.startswith("data:")
        ]


def await_state(client: TestClient, api_key: str, task_id: str, state: str) -> dict:
    """Poll GetTask until the Run reaches ``state``; the drive is detached."""

    deadline = time.monotonic() + 10
    task: dict = {}
    while time.monotonic() < deadline:
        task = rpc(client, api_key, "GetTask", {"id": task_id})["result"]
        if task["status"]["state"] == state:
            return task
        time.sleep(0.05)
    raise AssertionError(f"task stayed in {task.get('status')} instead of {state}")


@pytest.mark.timeout(30)
def test_streaming_opens_with_a_snapshot_and_ends_on_a_terminal_status(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    events = stream_events(
        a2a_client,
        api_key,
        "SendStreamingMessage",
        {
            "message": {
                "messageId": "msg-1",
                "role": "ROLE_USER",
                "parts": [{"text": "hi"}],
            }
        },
    )

    results = [event["result"] for event in events]
    # A2A opens a stream with the whole Task so a client never has to assemble
    # one from increments it may have joined too late to see.
    assert "task" in results[0]
    assert results[0]["task"]["status"]["state"] == "TASK_STATE_SUBMITTED"
    assert results[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"
    replies = [
        part["text"]
        for result in results
        if result.get("message", {}).get("role") == "ROLE_AGENT"
        for part in result["message"]["parts"]
    ]
    assert replies == ["hello"]


@pytest.mark.timeout(30)
def test_a_stream_does_not_echo_the_callers_own_message_back(a2a_client):  # noqa: F811
    """The caller wrote it; repeating it as progress would inform nobody."""

    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    events = stream_events(
        a2a_client,
        api_key,
        "SendStreamingMessage",
        {
            "message": {
                "messageId": "msg-1",
                "role": "ROLE_USER",
                "parts": [{"text": "hi"}],
            }
        },
    )

    roles = [
        event["result"]["message"]["role"]
        for event in events
        if "message" in event["result"]
    ]
    assert roles == ["ROLE_AGENT"]
    # It is still part of the conversation, so the Task keeps it.
    task_id = events[0]["result"]["task"]["id"]
    history = rpc(a2a_client, api_key, "GetTask", {"id": task_id})["result"]["history"]
    assert [item["role"] for item in history] == ["ROLE_USER", "ROLE_AGENT"]


@pytest.mark.timeout(30)
def test_subscribing_to_a_finished_task_yields_its_final_snapshot(a2a_client):  # noqa: F811
    """A client that reconnects late is owed the Task, not a replay."""

    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)
    task_id = send(a2a_client, api_key, "hi")["result"]["task"]["id"]

    events = stream_events(a2a_client, api_key, "SubscribeToTask", {"id": task_id})

    assert len(events) == 1
    task = events[0]["result"]["task"]
    assert task["id"] == task_id
    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.timeout(30)
def test_one_tenant_cannot_subscribe_to_another_tenants_task(tmp_path):
    """A subscription that is refused before it opens is a plain error reply.

    The refusal happens while resolving the Run, which is before the first event
    exists, so there is no stream to put an error frame into — and answering
    with an empty ``text/event-stream`` would look like a Task with nothing to
    say rather than one this key may not read.
    """

    with make_a2a_client(tmp_path, steps=2) as client:
        owner_token = register_and_login(client, "owner")
        other_token = register_and_login(client, "other")
        _, owner_key = mint_key(client, owner_token)
        _, other_key = mint_key(client, other_token)
        task_id = send(client, owner_key, "private")["result"]["task"]["id"]

        body = rpc(client, other_key, "SubscribeToTask", {"id": task_id})

    assert body["error"]["code"] == -32001


@pytest.mark.timeout(30)
def test_return_immediately_answers_before_the_run_finishes(tmp_path):
    with TestClient(_slow_app(tmp_path)) as client:
        token = register_and_login(client)
        _, api_key = mint_key(client, token)

        started = time.monotonic()
        task = rpc(
            client,
            api_key,
            "SendMessage",
            {
                "message": {
                    "messageId": "msg-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "hi"}],
                },
                "configuration": {"returnImmediately": True},
            },
        )["result"]["task"]
        elapsed = time.monotonic() - started

        assert elapsed < _MODEL_DELAY
        assert task["status"]["state"] != "TASK_STATE_COMPLETED"
        # The Run was handed to a background task, not abandoned: it finishes
        # even though nothing is holding the request open any more.
        finished = await_state(client, api_key, task["id"], "TASK_STATE_COMPLETED")
        assert [item["role"] for item in finished["history"]] == [
            "ROLE_USER",
            "ROLE_AGENT",
        ]


@pytest.mark.timeout(30)
def test_cancelling_a_running_task_reports_it_cancelled(tmp_path):
    with TestClient(_slow_app(tmp_path)) as client:
        token = register_and_login(client)
        _, api_key = mint_key(client, token)
        task = rpc(
            client,
            api_key,
            "SendMessage",
            {
                "message": {
                    "messageId": "msg-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "hi"}],
                },
                "configuration": {"returnImmediately": True},
            },
        )["result"]["task"]

        cancelled = rpc(client, api_key, "CancelTask", {"id": task["id"]})["result"]

    assert cancelled["id"] == task["id"]
    assert cancelled["status"]["state"] == "TASK_STATE_CANCELED"


@pytest.mark.timeout(30)
def test_cancelling_a_finished_task_is_not_cancelable_rather_than_missing(a2a_client):  # noqa: F811
    """A Task that already ended exists, so -32001 would be a lie."""

    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)
    task_id = send(a2a_client, api_key, "hi")["result"]["task"]["id"]

    body = rpc(a2a_client, api_key, "CancelTask", {"id": task_id})

    assert body["error"]["code"] == -32002


@pytest.mark.timeout(30)
def test_a_read_only_key_cannot_cancel(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, read_key = mint_key(a2a_client, token, scopes=["a2a:read"])

    response = a2a_client.post(
        "/a2a/v1",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "CancelTask",
            "params": {"id": "run_whatever"},
        },
        headers={"Authorization": f"Bearer {read_key}", **A2A_HEADERS},
    )

    assert response.status_code == 403


@pytest.mark.timeout(30)
def test_list_tasks_pages_through_the_owners_tasks_only(tmp_path):
    with make_a2a_client(tmp_path, steps=4) as client:
        token = register_and_login(client, "owner")
        other_token = register_and_login(client, "other")
        _, api_key = mint_key(client, token)
        _, other_key = mint_key(client, other_token)
        mine = {
            send(client, api_key, "one", message_id="msg-1")["result"]["task"]["id"],
            send(client, api_key, "two", message_id="msg-2")["result"]["task"]["id"],
        }
        theirs = send(client, other_key, "theirs")["result"]["task"]["id"]

        first = rpc(client, api_key, "ListTasks", {"pageSize": 1})["result"]
        second = rpc(
            client,
            api_key,
            "ListTasks",
            {"pageSize": 1, "pageToken": first["nextPageToken"]},
        )["result"]

    listed = [task["id"] for task in first["tasks"] + second["tasks"]]
    assert set(listed) == mine
    assert theirs not in listed
    # The walk ends by running out of Tasks on the last page, rather than
    # handing back a token for an empty page the client would have to ask for
    # to discover there was nothing behind it.
    assert first["nextPageToken"]
    assert not second.get("nextPageToken")


@pytest.mark.timeout(30)
def test_list_tasks_can_be_narrowed_to_one_context(tmp_path):
    with make_a2a_client(tmp_path, steps=3) as client:
        token = register_and_login(client)
        _, api_key = mint_key(client, token)
        first = send(client, api_key, "one", message_id="msg-1")["result"]["task"]
        send(client, api_key, "two", message_id="msg-2")

        listed = rpc(
            client, api_key, "ListTasks", {"contextId": first["contextId"]}
        )["result"]["tasks"]

    assert [task["id"] for task in listed] == [first["id"]]


@pytest.mark.timeout(30)
def test_a_malformed_page_token_is_invalid_params(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    body = rpc(a2a_client, api_key, "ListTasks", {"pageToken": "not-a-token"})

    assert body["error"]["code"] == -32602


@pytest.mark.timeout(30)
def test_the_card_advertises_streaming_once_it_is_implemented(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    card = a2a_client.get(
        "/a2a/v1/card", headers={"Authorization": f"Bearer {api_key}"}
    ).json()

    assert card["capabilities"]["streaming"] is True


def _slow_app(tmp_path):
    from app.server_v2.bootstrap.app import create_app
    from tests.app.server_v2.conftest import make_test_service

    return create_app(
        service=make_test_service(tmp_path, model_provider=SlowModelProvider())
    )
