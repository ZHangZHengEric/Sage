from app.server_v2.domain.threads import (
    ThreadRecord,
    apply_thread_upsert,
    resolve_thread_agent_id,
)
from app.server_v2.app import create_app
from tests.app.server_v2.conftest import (
    make_test_service,
    register_and_login,
    scripted_hello,
)
from tests.app.server_v2.test_agui_chat import _run_input

from fastapi.testclient import TestClient


def test_pinned_agent_wins_over_requested():
    existing = ThreadRecord(thread_id="t1", user_id="u1", agent_id="writer")
    assert resolve_thread_agent_id(existing, "coder") == "writer"
    assert resolve_thread_agent_id(None, "coder") == "coder"


def test_upsert_keeps_first_agent_id():
    first = apply_thread_upsert(
        None, thread_id="t1", user_id="u1", title="hi", agent_id="writer"
    )
    second = apply_thread_upsert(
        first, thread_id="t1", user_id="u1", title="hi", agent_id="coder"
    )
    assert first.agent_id == "writer"
    assert second.agent_id == "writer"


def test_agui_run_pins_thread_agent_and_ignores_later_picker(tmp_path):
    provider = scripted_hello(steps=2)
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        writer = client.post(
            "/api/agents",
            json={"name": "Writer", "instructions": "You are the catalog writer agent."},
            headers=headers,
        ).json()["data"]["id"]
        coder = client.post(
            "/api/agents",
            json={"name": "Coder", "instructions": "You are the catalog coder agent."},
            headers=headers,
        ).json()["data"]["id"]
        first = _run_input("thread-pin", "run-pin-1")
        first["forwardedProps"] = {"agentId": writer}
        assert client.post("/api/agent", json=first, headers=headers).status_code == 200
        threads = client.get("/api/threads", headers=headers)
        assert threads.status_code == 200
        assert threads.json()["data"][0]["agent_id"] == writer
        second = _run_input("thread-pin", "run-pin-2")
        second["forwardedProps"] = {"agentId": coder}
        assert client.post("/api/agent", json=second, headers=headers).status_code == 200

    rendered = "\n".join(
        block.text
        for request in provider.requests
        for message in request.messages
        for block in message.content
        if getattr(block, "text", None)
    )
    assert "catalog writer agent" in rendered
    assert "catalog coder agent" not in rendered
    assert len(provider.requests) == 2
