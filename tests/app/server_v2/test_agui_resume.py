"""Answering a thread that is waiting on input, over the AG-UI surface.

An approval suspends a Run wherever it was started from, and the Run is the
same fact on every surface. These tests cover the web side of that: how a
thread says it is waiting, and what answering it does.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.server_v2.app import create_app
from tests.app.server_v2.conftest import make_test_service, register_and_login
from tests.app.server_v2.test_a2a_resume import _step
from sagents.v2.testing.plugins import ScriptedModelProvider


def _asking_service(tmp_path):
    provider = ScriptedModelProvider(
        (
            _step(1, "I will write the note.", "file_write",
                  {"file_path": "note.txt", "content": "blue"}),
            _step(2, "written"),
            _step(3, "written"),
            _step(4, "written"),
        )
    )
    return make_test_service(tmp_path, model_provider=provider)


def _frames(body: str) -> list[dict]:
    return [
        json.loads(line[len("data:") :].lstrip())
        for line in body.splitlines()
        if line.startswith("data:")
    ]


def _ask(client: TestClient, token: str) -> list[dict]:
    """Run a thread up to its approval question and return the AG-UI frames."""

    headers = {"Authorization": f"Bearer {token}"}
    agents = client.get("/api/agents", headers=headers).json()["data"]
    granted = client.put(
        f"/api/agents/{agents[0]['id']}",
        json={"name": agents[0]["name"], "tools": ["file_write"]},
        headers=headers,
    )
    assert granted.status_code == 200, granted.text
    response = client.post(
        "/api/agent",
        json={
            "threadId": "thread-1",
            "runId": "run-1",
            "state": {},
            "messages": [{"id": "m1", "role": "user", "content": "write a note"}],
            "tools": [],
            "context": [],
            "forwardedProps": {"agentId": agents[0]["id"]},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return _frames(response.text)


def _resume(client: TestClient, token: str, decision: str, **body):
    return client.post(
        "/api/threads/thread-1/resume",
        json={"runId": "run-2", "decision": decision, **body},
        headers={"Authorization": f"Bearer {token}"},
    )


@pytest.mark.timeout(30)
def test_a_suspended_thread_streams_the_suspension_and_stops(tmp_path):
    """The stream ends where the agent stopped, not with a completed Run.

    This is what the resume route exists to answer: the client has been told
    the Run is parked, and nothing else will arrive on this stream.
    """

    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        token = register_and_login(client)
        frames = _ask(client, token)

    kinds = [frame.get("type") for frame in frames]
    assert "RUN_FINISHED" not in kinds
    assert any(
        frame.get("name") == "sage.run.suspended"
        for frame in frames
        if frame.get("type") == "CUSTOM"
    )


@pytest.mark.timeout(30)
def test_resuming_a_thread_streams_the_run_to_completion(tmp_path):
    """The answer releases the Run, and this stream is where it is watched.

    The new stream replays from the start of the Run so the client rebuilds
    item state exactly, which means it necessarily passes back over the
    suspension. Passing over it must not end the stream — that pause is the
    thing this request just undid.
    """

    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        token = register_and_login(client)
        _ask(client, token)

        response = _resume(client, token, "approve_once")

        assert response.status_code == 200, response.text
        kinds = [
            frame.get("name") if frame.get("type") == "CUSTOM" else frame.get("type")
            for frame in _frames(response.text)
        ]

    assert "sage.run.suspended" in kinds
    assert "RUN_FINISHED" in kinds
    assert kinds.index("sage.run.suspended") < kinds.index("RUN_FINISHED")


@pytest.mark.timeout(30)
def test_a_thread_that_is_not_waiting_cannot_be_resumed(tmp_path):
    """Nothing is pending, so there is no question this could be answering."""

    service = make_test_service(tmp_path)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        client.post(
            "/api/agent",
            json={
                "threadId": "thread-1",
                "runId": "run-1",
                "state": {},
                "messages": [{"id": "m1", "role": "user", "content": "hello"}],
                "tools": [],
                "context": [],
                "forwardedProps": {"agentId": "main"},
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        response = _resume(client, token, "approve_once")

    assert response.status_code == 409, response.text


@pytest.mark.timeout(30)
def test_a_decision_the_question_does_not_offer_is_rejected(tmp_path):
    """The pending question defines the vocabulary; the client does not."""

    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        token = register_and_login(client)
        _ask(client, token)

        response = _resume(client, token, "approve_and_remember")

    assert response.status_code == 422, response.text


@pytest.mark.timeout(30)
def test_one_user_cannot_resume_another_users_thread(tmp_path):
    """An unreadable thread is missing, so its id cannot be probed."""

    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        owner = register_and_login(client, "owner")
        other = register_and_login(client, "other")
        _ask(client, owner)

        response = _resume(client, other, "approve_once")

    assert response.status_code == 404, response.text
