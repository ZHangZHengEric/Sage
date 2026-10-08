import pytest
from fastapi.testclient import TestClient
from sagents.v2.model.contracts import ModelEventKind, ModelResponse, ModelStreamEvent
from sagents.v2.testing.plugins import ScriptedModelProvider, ScriptedModelStep

from app.v2.server.main import create_app
from tests.app.v2.server.conftest import (
    make_test_service,
    register_and_login,
    scripted_hello,
)
from tests.app.v2.server.test_agui_chat import _parse_sse, _run_input


@pytest.mark.timeout(30)
def test_server_judge_continues_after_intermediate_text(tmp_path):
    def step(text):
        return ScriptedModelStep(
            events=(
                ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id=f"response_{len(text)}",
                        text=text,
                        finish_reason="stop",
                    ),
                ),
            )
        )

    provider = ScriptedModelProvider(
        (
            step("I found the relevant files. I will verify them next."),
            step('{"decision":"continue","reason":"Verification remains."}'),
            step("Verification passed. Here is the answer."),
            step('{"decision":"completed","reason":"The answer is delivered."}'),
        )
    )
    service = make_test_service(tmp_path, model_provider=provider, stub_judge=False)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        response = client.post(
            "/api/agent",
            json=_run_input(),
            headers={"Authorization": f"Bearer {token}"},
        )

    assert _parse_sse(response.text)[-1]["type"] == "RUN_FINISHED"
    assert [request.metadata.get("purpose") for request in provider.requests] == [
        None,
        "continuation_judge",
        None,
        "continuation_judge",
    ]


@pytest.mark.timeout(30)
def test_agui_run_uses_catalog_agent_instructions(tmp_path):
    provider = scripted_hello()
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/api/agents",
            json={
                "name": "Writer",
                "instructions": "You are the catalog writer agent.",
            },
            headers=headers,
        )
        agent_id = created.json()["data"]["id"]
        payload = _run_input()
        payload["forwardedProps"] = {"agentId": agent_id}
        response = client.post("/api/agent", json=payload, headers=headers)
        assert response.status_code == 200

    assert provider.requests
    rendered = "\n".join(
        block.text
        for request in provider.requests
        for message in request.messages
        for block in message.content
        if getattr(block, "text", None)
    )
    assert "catalog writer agent" in rendered
