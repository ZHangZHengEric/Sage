"""The hop budget that keeps two agents from delegating to each other forever.

A delegation chain has no natural end: each agent only sees the request in
front of it, so a cycle looks like ordinary work from every position in it.
The budget travels with the request as a depth count, and is enforced twice —
outbound, by not composing A2A Tools into a Run that is already at the limit,
and inbound, by refusing a request that arrives past it. These tests cover
both ends and the handover between them.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sagents.v2.testing.plugins import ScriptedModelProvider
from sagents.v2.tool.plugins.a2a import CALL_DEPTH_KEY, MAX_CALL_DEPTH

from app.server_v2.main import create_app
from app.server_v2.runtime.integrations.a2a import A2APluginCache
from tests.app.server_v2.conftest import make_test_service, register_and_login
from tests.app.server_v2.test_a2a_card import (  # noqa: F401
    a2a_client,
    mint_key,
)
from tests.app.server_v2.test_a2a_resume import _step
from tests.app.server_v2.test_a2a_send import send
from tests.sagents.v2.test_a2a_tool_bridge_matrix import FakePeer

PEER = {"name": "researcher", "url": "https://peer.example.com"}
TOOL = "a2a_researcher_research"


def delegating_client(tmp_path, transport: FakePeer, *, steps: int = 4):
    """A client whose agent immediately delegates to the fake peer."""

    provider = ScriptedModelProvider(
        (
            _step(1, "I will ask the researcher.", TOOL, {"message": "what is new"}),
            *(_step(index, "researcher says: the answer") for index in range(2, steps)),
        )
    )
    service = make_test_service(tmp_path, model_provider=provider)
    # The host owns the transport, exactly as it owns the MCP session factory.
    service.a2a_plugins = A2APluginCache(transport=transport)
    return TestClient(create_app(service=service))


def frames(body: str) -> list[dict]:
    return [
        json.loads(line[len("data:") :].lstrip())
        for line in body.splitlines()
        if line.startswith("data:")
    ]


def run_agui(client: TestClient, token: str, *, run_id: str = "run-1") -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    agents = client.get("/api/agents", headers=headers).json()["data"]
    response = client.post(
        "/api/agent",
        json={
            "threadId": "thread-1",
            "runId": run_id,
            "state": {},
            "messages": [{"id": "m1", "role": "user", "content": "what is new"}],
            "tools": [],
            "context": [],
            "forwardedProps": {"agentId": agents[0]["id"]},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return frames(response.text)


def configure_peer(client: TestClient, token: str) -> None:
    created = client.post(
        "/api/a2a-agents",
        json=PEER,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert created.status_code == 200, created.text


@pytest.mark.timeout(30)
def test_a_request_past_the_budget_is_refused_before_any_work_is_done(a2a_client):  # noqa: F811
    """The chain is already too long; running this Run would extend it."""

    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    body = send(
        a2a_client,
        api_key,
        "keep going",
        metadata={CALL_DEPTH_KEY: MAX_CALL_DEPTH + 1},
    )

    assert body["error"]["code"] == -32602
    assert str(MAX_CALL_DEPTH) in body["error"]["message"]


@pytest.mark.timeout(30)
def test_a_request_inside_the_budget_is_ordinary_work(a2a_client):  # noqa: F811
    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    task = send(a2a_client, api_key, "hi", metadata={CALL_DEPTH_KEY: 1})["result"][
        "task"
    ]

    assert task["status"]["state"] == "TASK_STATE_COMPLETED"


@pytest.mark.timeout(30)
def test_a_depth_that_is_not_a_number_is_rejected_rather_than_assumed(a2a_client):  # noqa: F811
    """Defaulting a malformed budget to zero is how a cycle restarts itself."""

    token = register_and_login(a2a_client)
    _, api_key = mint_key(a2a_client, token)

    body = send(a2a_client, api_key, "hi", metadata={CALL_DEPTH_KEY: "deep"})

    assert body["error"]["code"] == -32602


@pytest.mark.timeout(30)
def test_delegating_to_a_peer_asks_before_it_happens(tmp_path):
    """Nothing about a message sent to another organisation can be taken back."""

    transport = FakePeer()
    with delegating_client(tmp_path, transport) as client:
        token = register_and_login(client)
        configure_peer(client, token)

        kinds = [
            frame.get("name") if frame.get("type") == "CUSTOM" else frame.get("type")
            for frame in run_agui(client, token)
        ]

    assert "sage.run.suspended" in kinds
    assert "RUN_FINISHED" not in kinds
    assert transport.sent == []


@pytest.mark.timeout(30)
def test_an_approved_delegation_reaches_the_peer_announcing_its_hop(tmp_path):
    """A first-hop Run tells the peer it is the second, so the chain can end."""

    transport = FakePeer()
    with delegating_client(tmp_path, transport) as client:
        token = register_and_login(client)
        configure_peer(client, token)
        run_agui(client, token)

        resumed = client.post(
            "/api/threads/thread-1/resume",
            json={"runId": "run-2", "decision": "approve_once"},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resumed.status_code == 200, resumed.text
    assert len(transport.sent) == 1
    message = transport.sent[0][1]["params"]["message"]
    assert message["parts"][0]["text"] == "what is new"
    assert message["metadata"][CALL_DEPTH_KEY] == 1


@pytest.mark.timeout(30)
def test_a_peer_that_is_down_does_not_stop_the_run_from_starting(tmp_path):
    """Composition reads the peer's card. A peer being down is not a Run failing.

    The Agent loses that peer's Tools for this Run, which is the same thing
    that happens when the peer is removed from the catalog, and then answers
    with what it has.
    """

    transport = FakePeer(card=ConnectionError("no route to host"))
    with delegating_client(tmp_path, transport) as client:
        token = register_and_login(client)
        configure_peer(client, token)

        kinds = [
            frame.get("name") if frame.get("type") == "CUSTOM" else frame.get("type")
            for frame in run_agui(client, token)
        ]

    assert "RUN_STARTED" in kinds
    assert transport.sent == []


@pytest.mark.timeout(30)
def test_a_peer_that_is_not_in_the_catalog_gives_the_agent_no_tools(tmp_path):
    """Delegation is opt-in per tenant, not a capability every Agent has."""

    transport = FakePeer()
    with delegating_client(tmp_path, transport) as client:
        token = register_and_login(client)

        interactions = [
            frame["value"]
            for frame in run_agui(client, token)
            if frame.get("name") == "sage.interaction.requested"
        ]

    # The Run asks what to do instead of delegating: the Tool the model named
    # is not one this Run was granted, because no peer was configured.
    assert interactions
    assert interactions[0]["payload"]["reason_code"] == "tool.not_enabled"
    assert transport.sent == []
