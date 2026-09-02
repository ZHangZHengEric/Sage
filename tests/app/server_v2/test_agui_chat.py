from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tests.app.server_v2.conftest import register_and_login


def _parse_sse(body: str) -> list[dict]:
    return [payload for _, payload in _parse_sse_frames(body)]


def _parse_sse_frames(body: str) -> list[tuple[str | None, dict]]:
    frames: list[tuple[str | None, dict]] = []
    for block in body.split("\n\n"):
        event_id = None
        data_lines = []
        for line in block.splitlines():
            if line.startswith("id:"):
                event_id = line[3:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
        if data_lines:
            frames.append((event_id, json.loads("\n".join(data_lines))))
    return frames


def _run_input(thread_id: str = "thread-1", run_id: str = "run-1") -> dict:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": {},
        "messages": [{"id": "m1", "role": "user", "content": "hello"}],
        "tools": [],
        "context": [],
        "forwardedProps": {"agentId": "main"},
    }


@pytest.mark.timeout(30)
def test_agui_chat_emits_standard_lifecycle(client: TestClient):
    token = register_and_login(client)
    response = client.post(
        "/api/agent",
        json=_run_input(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    types = [event["type"] for event in events]
    assert types[0] == "RUN_STARTED"
    started = events[0]
    assert started["threadId"] == "thread-1"
    assert started["runId"] == "run-1"
    assert "TEXT_MESSAGE_CONTENT" in types
    assert types[-1] == "RUN_FINISHED"
    threads = client.get(
        "/api/threads",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert threads.status_code == 200
    assert threads.json()["data"][0]["thread_id"] == "thread-1"


@pytest.mark.timeout(30)
def test_same_run_id_resubscribes_instead_of_rerunning(client: TestClient):
    token = register_and_login(client)
    first = client.post(
        "/api/agent",
        json=_run_input(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/agent",
        json=_run_input(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 200
    assert [event["type"] for event in _parse_sse(first.text)] == [
        event["type"] for event in _parse_sse(second.text)
    ]


@pytest.mark.timeout(30)
def test_other_user_cannot_see_thread(client: TestClient):
    alice = register_and_login(client, "alice")
    assert (
        client.post(
            "/api/agent",
            json=_run_input(),
            headers={"Authorization": f"Bearer {alice}"},
        ).status_code
        == 200
    )
    bob = register_and_login(client, "bob")
    hidden = client.post(
        "/api/agent",
        json=_run_input(run_id="run-2"),
        headers={"Authorization": f"Bearer {bob}"},
    )
    assert hidden.status_code == 404
    threads = client.get(
        "/api/threads",
        headers={"Authorization": f"Bearer {bob}"},
    )
    assert threads.json()["data"] == []


@pytest.mark.timeout(30)
def test_last_event_id_replays_only_unseen_events(client: TestClient):
    token = register_and_login(client)
    first = client.post(
        "/api/agent",
        json=_run_input(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    frames = _parse_sse_frames(first.text)
    assert frames[0][1]["type"] == "RUN_STARTED"
    cursor = frames[0][0]
    assert cursor
    replay = client.post(
        "/api/agent",
        json=_run_input(),
        headers={
            "Authorization": f"Bearer {token}",
            "Last-Event-ID": cursor,
        },
    )
    assert replay.status_code == 200
    replayed = _parse_sse(replay.text)
    assert [event["type"] for event in replayed] == [
        event["type"] for _, event in frames[1:]
    ]
