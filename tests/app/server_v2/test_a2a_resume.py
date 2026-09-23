"""Answering a Task that is waiting on input, over plain A2A messages.

A2A has no concept of an approval prompt. It has a Task in the input-required
state and an ordinary Message naming that Task, and everything Sage needs —
which question is being answered, and which of its allowed decisions the answer
picks — has to survive that round trip. These tests pin both directions: what a
waiting Task tells a client, and what a client's reply is allowed to mean.
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.server_v2.app import create_app
from sagents.v2.contracts.items import UsageSummary
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep
from tests.app.server_v2.conftest import make_test_service, register_and_login
from tests.app.server_v2.test_a2a_card import mint_key, rpc
from tests.app.server_v2.test_a2a_send import send
from tests.app.server_v2.test_a2a_stream import stream_events


def _step(index: int, text: str, tool: str = "", arguments: dict | None = None):
    calls = (
        (ModelToolCall(tool_call_id=f"call-{index}", name=tool, arguments=arguments or {}),)
        if tool
        else ()
    )
    return ScriptedModelStep(
        events=(
            ModelStreamEvent(
                kind=ModelEventKind.COMPLETED,
                response=ModelResponse(
                    response_id=f"response-{index}",
                    text=text,
                    tool_calls=calls,
                    finish_reason="tool_calls" if tool else "stop",
                    usage=UsageSummary(input_tokens=3, output_tokens=1),
                ),
            ),
        )
    )


@contextmanager
def asking_client(tmp_path):
    """A client whose agent immediately asks to do something that needs approval.

    ``file_write`` is a write-level tool, so the default policy suspends the Run
    and asks before it happens. That is the only path in this host that produces
    a real pending Interaction, which is what makes it the honest fixture here:
    the Task a client sees is the one the product actually produces.
    """

    provider = ScriptedModelProvider(
        (
            _step(1, "I will write the note.", "file_write",
                  {"file_path": "note.txt", "content": "blue"}),
            _step(2, "written"),
            _step(3, "written"),
            _step(4, "written"),
        )
    )
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        yield client


def ask(client: TestClient, token: str, **key_options) -> tuple[str, dict]:
    """Drive one agent up to its approval question. Returns (api_key, task)."""

    agent_id, api_key = mint_key(client, token, **key_options)
    granted = client.put(
        f"/api/agents/{agent_id}",
        json={"name": "Peer", "tools": ["file_write"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert granted.status_code == 200, granted.text
    task = send(client, api_key, "write a note")["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    return api_key, task


def reply(client: TestClient, api_key: str, task: dict, text: str, **metadata) -> dict:
    return send(
        client, api_key, text,
        message_id=f"reply-{task['id']}",
        taskId=task["id"],
        contextId=task["contextId"],
        metadata=metadata,
    )


@pytest.mark.timeout(30)
def test_a_waiting_task_carries_the_question_and_the_answers_it_accepts(tmp_path):
    """The Task has to say what it is waiting for, or a reply is a guess.

    A2A's ``input-required`` says only that input is wanted. Without the
    interaction id and its allowed decisions a client cannot tell an approval
    from a free-text question, and would have to infer the vocabulary from
    prose written for a human.
    """

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        _, task = ask(client, token)

    metadata = task["metadata"]
    assert metadata["sage.interactionId"]
    assert metadata["sage.interactionType"] == "approval"
    assert list(metadata["sage.allowedDecisions"]) == ["approve_once", "deny", "cancel"]
    assert metadata["sage.payload"]["tool_name"] == "file_write"


@pytest.mark.timeout(30)
def test_approving_over_a2a_finishes_the_run(tmp_path):
    """The whole point: a reply naming the Task moves it, not a new Task."""

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        api_key, task = ask(client, token)

        answered = reply(
            client, api_key, task, "yes, go ahead", **{"sage.decision": "approve_once"}
        )["result"]["task"]

    # The same Task, carried forward — not a second one in the same context.
    assert answered["id"] == task["id"]
    assert answered["contextId"] == task["contextId"]
    assert answered["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.timeout(30)
def test_the_reply_waits_for_what_happens_after_it_rather_than_before(tmp_path):
    """A resumed Run must not be reported finished by its own old suspension.

    The Run's log already contains the ``run.suspended`` that produced this
    question. A wait that starts reading from the beginning would match that
    record instantly and hand back the very Task the client was answering,
    which looks exactly like a reply that changed nothing.
    """

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        api_key, task = ask(client, token)

        answered = reply(
            client, api_key, task, "go ahead", **{"sage.decision": "approve_once"}
        )["result"]["task"]

    assert answered["status"]["state"] != task["status"]["state"]


@pytest.mark.timeout(30)
def test_denying_over_a2a_is_also_an_answer(tmp_path):
    """Refusing the tool call resolves the question; it does not abandon the Run.

    A denial is not a failure and not a cancellation — the agent is told it may
    not do that one thing and carries on, so the Task reaches the same terminal
    state an approval would. What distinguishes them is that the tool never ran,
    not that the conversation ended differently.
    """

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        api_key, task = ask(client, token)

        answered = reply(
            client, api_key, task, "no, don't", **{"sage.decision": "deny"}
        )["result"]["task"]

    assert answered["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.timeout(30)
def test_free_text_alone_cannot_approve_a_tool_call(tmp_path):
    """Prose is not a decision, and reading it as consent is irreversible.

    An approval offers ``approve_once``/``deny``/``cancel`` and nothing in a
    sentence picks one of them. "yes, go ahead" and "no, don't" are equally
    plausible English; guessing wrong in one direction writes a file the caller
    refused. So an unnamed decision is rejected rather than interpreted.
    """

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        api_key, task = ask(client, token)

        body = reply(client, api_key, task, "yes, go ahead")

        assert body["error"]["code"] == -32602
        # And the question is still standing, waiting for a real answer.
        still = rpc(client, api_key, "GetTask", {"id": task["id"]})["result"]
        assert still["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"


@pytest.mark.timeout(30)
def test_a_decision_the_question_does_not_offer_is_rejected(tmp_path):
    """``approve_and_remember`` is a real decision — just not one on offer here."""

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        api_key, task = ask(client, token)

        body = reply(
            client, api_key, task, "always allow this",
            **{"sage.decision": "approve_and_remember"},
        )

    assert body["error"]["code"] == -32602


@pytest.mark.timeout(30)
def test_a_streaming_reply_opens_on_the_answered_task_and_runs_forward(tmp_path):
    """Streaming a reply shows what the answer caused, not the wait before it.

    The opening frame is the whole Task, as A2A requires, so it legitimately
    still reads ``input-required`` — that is the Task at the moment the reply
    was admitted. Everything after it must be new: replaying the increments
    that led to the question would end the stream on the old suspension.
    """

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        api_key, task = ask(client, token)

        events = stream_events(
            client,
            api_key,
            "SendStreamingMessage",
            {
                "message": {
                    "messageId": "reply-streamed",
                    "role": "ROLE_USER",
                    "parts": [{"text": "go ahead"}],
                    "taskId": task["id"],
                    "contextId": task["contextId"],
                    "metadata": {"sage.decision": "approve_once"},
                }
            },
        )

    results = [event["result"] for event in events]
    assert results[0]["task"]["id"] == task["id"]
    assert results[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.timeout(30)
def test_replying_to_a_task_that_is_not_waiting_is_invalid_params(tmp_path):
    """A finished Task cannot be answered; continuing it is a new Task.

    This is -32602 rather than -32002, which means "this Task cannot be
    cancelled". The params are what is wrong: they describe a Task in a state
    it is no longer in, and the client's next move is to read it again.
    """

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        api_key, task = ask(client, token)
        reply(client, api_key, task, "go ahead", **{"sage.decision": "approve_once"})

        body = reply(client, api_key, task, "and again",
                     **{"sage.decision": "approve_once"})

    assert body["error"]["code"] == -32602


@pytest.mark.timeout(30)
def test_one_tenant_cannot_answer_another_tenants_question(tmp_path):
    """An unreadable Task is missing, not forbidden — replies are no exception.

    Reporting "denied" here would confirm the Task exists, turning the reply
    path into the membership oracle the read path is careful not to be.
    """

    with asking_client(tmp_path) as client:
        owner_token = register_and_login(client, "owner")
        other_token = register_and_login(client, "other")
        api_key, task = ask(client, owner_token)
        _, other_key = mint_key(client, other_token)

        body = reply(client, other_key, task, "go ahead",
                     **{"sage.decision": "approve_once"})

        assert body["error"]["code"] == -32001
        # And the owner's question is untouched by the attempt.
        still = rpc(client, api_key, "GetTask", {"id": task["id"]})["result"]
        assert still["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"


@pytest.mark.timeout(30)
def test_a_read_only_key_cannot_answer(tmp_path):
    """Answering runs the tool that was being asked about, so it needs invoke.

    Scope is settled at HTTP because A2A has no JSON-RPC error for it, so this
    is a 403 rather than an error object in a 200 response.
    """

    with asking_client(tmp_path) as client:
        token = register_and_login(client)
        _, task = ask(client, token)
        _, read_key = mint_key(client, token, scopes=["a2a:read"])

        response = client.post(
            "/a2a/v1",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "SendMessage",
                "params": {
                    "message": {
                        "messageId": "reply-denied",
                        "role": "ROLE_USER",
                        "parts": [{"text": "go ahead"}],
                        "taskId": task["id"],
                        "contextId": task["contextId"],
                        "metadata": {"sage.decision": "approve_once"},
                    }
                },
            },
            headers={
                "Authorization": f"Bearer {read_key}",
                "A2A-Version": "1.0",
            },
        )

    assert response.status_code == 403, response.text
