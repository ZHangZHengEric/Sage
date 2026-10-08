import pytest
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from sagents.v2.agent.policy.tool_policy import ApprovalStrategy, DefaultToolPolicy
from sagents.v2.model.contracts import (
    ModelEventKind,
    ModelResponse,
    ModelStreamEvent,
    ModelToolCall,
)
from sagents.v2.testing.plugins.scripted_model import (
    ScriptedModelProvider,
    ScriptedModelStep,
)
from tests.app.v2.server.conftest import make_test_service
from tests.app.v2.server.test_agui_chat import _run_input


@pytest.mark.timeout(30)
def test_catalog_agent_registers_then_uses_local_skill_in_same_agui_run(
    tmp_path, monkeypatch
):
    # Explicitly authorize writes in this fixture; production keeps ordinary approvals.
    monkeypatch.setattr(
        "app.v2.server.packages.tool_policy.server_tool_policy",
        lambda *args, **kwargs: DefaultToolPolicy(
            approval_strategy=ApprovalStrategy.AUTO_APPROVE
        ),
    )

    def step(*calls, text=""):
        return ScriptedModelStep(
            events=(
                ModelStreamEvent(
                    kind=ModelEventKind.COMPLETED,
                    response=ModelResponse(
                        response_id="response",
                        text=text,
                        tool_calls=calls,
                        finish_reason="tool_calls" if calls else "stop",
                    ),
                ),
            )
        )

    provider = ScriptedModelProvider(
        (
            step(
                ModelToolCall(
                    tool_call_id="configure",
                    name="agent_self_configure",
                    arguments={
                        "add_skill_paths": ["/workspace/downloads/review"],
                        "system_prompt": "Use concise Chinese.",
                    },
                )
            ),
            step(
                ModelToolCall(
                    tool_call_id="load",
                    name="load_skill",
                    arguments={"skill_name": "review"},
                )
            ),
            step(text="done"),
        )
    )
    host = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=host)) as client:
        registered = client.post(
            "/api/auth/register", json={"username": "alice", "password": "secret1"}
        )
        assert registered.status_code == 200
        login = client.post(
            "/api/auth/login", json={"username": "alice", "password": "secret1"}
        ).json()["data"]
        user_id = login["user"]["user_id"]
        directory = host.paths.workspace_dir(user_id) / "downloads" / "review"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text("# Review\nCheck actual deployed routes.")
        response = client.post(
            "/api/agent",
            json=_run_input(),
            headers={"Authorization": f"Bearer {login['access_token']}"},
        )
        assert response.status_code == 200
    assert len(provider.requests) == 3
    assert "agent_self_configure" in {tool.name for tool in provider.requests[0].tools}
    assert "Check actual deployed routes" in str(provider.requests[-1].messages)

    assert "Use concise Chinese." in str(provider.requests[-1].messages)
