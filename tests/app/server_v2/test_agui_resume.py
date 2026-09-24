"""Answering a thread that is waiting on input, over the AG-UI surface.

An approval suspends a Run wherever it was started from, and the Run is the
same fact on every surface. These tests cover the web side of that: how a
thread says it is waiting, and what answering it does.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.server_v2.main import create_app
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


def _kinds(frames: list[dict]) -> list[str]:
    """Name each frame the way a client switches on it: CUSTOM by extension."""

    return [
        frame.get("name") if frame.get("type") == "CUSTOM" else frame.get("type")
        for frame in frames
    ]


def _custom(frames: list[dict], name: str) -> list[dict]:
    return [
        frame["value"]
        for frame in frames
        if frame.get("type") == "CUSTOM" and frame.get("name") == name
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
        kinds = _kinds(_frames(response.text))

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


@pytest.mark.timeout(30)
def test_the_suspension_stream_names_the_question_and_the_answers_it_takes(tmp_path):
    """A client that cannot see the question has nothing to put in front of a user.

    The web chat builds its approval prompt out of this one frame: what is
    being asked, and which answers the pending question accepts. The prose in
    the transcript is not enough — ``approve_once`` is vocabulary the server
    owns, and a UI that guessed it would be guessing about a write.
    """

    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        token = register_and_login(client)
        frames = _ask(client, token)

    asked = _custom(frames, "sage.interaction.requested")
    assert len(asked) == 1
    assert asked[0]["interaction_type"] == "approval"
    assert list(asked[0]["allowed_decisions"]) == ["approve_once", "deny", "cancel"]
    assert asked[0]["payload"]["tool_name"] == "file_write"


@pytest.mark.timeout(30)
def test_a_reopened_thread_still_carries_the_question_it_is_waiting_on(tmp_path):
    """Closing the tab must not strand the Run.

    A client reopening a waiting thread rebuilds it from the stored events, so
    the question has to be among them — otherwise the only way back to a
    suspended Run is the stream that happened to be open when it suspended.
    The Run boundary matters too: answering replays the Run from its first
    event, so a client needs to see where its own transcript rewinds to, and
    that the message it sent sits before that point rather than inside the
    replay.
    """

    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        token = register_and_login(client)
        _ask(client, token)
        page = client.get(
            "/api/threads/thread-1/events",
            headers={"Authorization": f"Bearer {token}"},
        ).json()["data"]

    kinds = _kinds(page["events"])
    assert "sage.interaction.requested" in kinds
    assert kinds.index("TEXT_MESSAGE_START") < kinds.index("RUN_STARTED")


@pytest.mark.timeout(30)
def test_an_answered_question_stops_being_pending(tmp_path):
    """The record says the question was closed, not merely that a Run moved on.

    A client decides whether to show the prompt by reading the thread, so an
    answer that left no trace would put an approval back in front of a user
    who has already given it.
    """

    with TestClient(create_app(service=_asking_service(tmp_path))) as client:
        token = register_and_login(client)
        _ask(client, token)
        _resume(client, token, "approve_once")
        page = client.get(
            "/api/threads/thread-1/events?limit=2000",
            headers={"Authorization": f"Bearer {token}"},
        ).json()["data"]

    resolved = _custom(page["events"], "sage.interaction.resolved")
    asked = _custom(page["events"], "sage.interaction.requested")
    assert [item["interaction_id"] for item in resolved] == [
        item["interaction_id"] for item in asked
    ]
