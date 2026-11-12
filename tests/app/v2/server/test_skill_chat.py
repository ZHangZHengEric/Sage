
from typing import cast

from sagents.v2.contracts.items import JsonBlock, TextBlock
from fastapi.testclient import TestClient

from app.v2.server.main import create_app
from tests.app.v2.server.conftest import (
    make_test_service,
    register_and_login,
    scripted_hello,
)
from tests.app.v2.server.test_agui_chat import _run_input

import pytest


@pytest.mark.timeout(30)
def test_agui_run_sees_bound_skill_without_workspace_copy(tmp_path):
    provider = scripted_hello()
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        token = register_and_login(client)
        headers = {"Authorization": f"Bearer {token}"}
        agent_id = client.get("/api/agents", headers=headers).json()["data"][0]["id"]
        client.post(
            "/api/skills",
            json={
                "name": "demo",
                "content": "---\nname: demo\ndescription: Demo skill\n---\n\n# Demo\n",
            },
            headers=headers,
        )
        client.put(f"/api/agents/{agent_id}/skills", json={"names": ["demo"]}, headers=headers)
        response = client.post("/api/agent", json=_run_input(), headers=headers)
        assert response.status_code == 200

    assert provider.requests
    rendered = "\n".join(
        cast(TextBlock, block).text
        for request in provider.requests
        for message in request.messages
        for block in message.content
        if getattr(block, "text", None)
    )
    assert "<available_skills>" in rendered
    assert "demo" in rendered
    assert not (tmp_path / "tenants").exists() or not any(
        tmp_path.joinpath("tenants").rglob("skills/demo")
    )


@pytest.mark.timeout(30)
@pytest.mark.parametrize("mode,search", [("simple", False), ("simple", True), ("team", True)])
def test_agent_skill_visibility_reaches_server_model_request(tmp_path, mode, search):
    if search:
        from sagents.v2.model import ModelToolCall, ScriptedModelProvider
        from tests.sagents.v2.test_standard_execution_configuration import response

        provider = ScriptedModelProvider((
            response(ModelToolCall(tool_call_id="search", name="search_skills",
                                   arguments={"query": "searchable-guide", "limit": 1})),
            response(ModelToolCall(tool_call_id="load", name="load_skill",
                                   arguments={"skill_name": "searchable-guide"})),
            response(),
        ))
    else:
        provider = scripted_hello()
    service = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=service)) as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}
        config = {
            "name": "Research",
            "agent_mode": mode,
            "tools": ["search_skills"] if search else [],
            "tool_approval": {"default": "ask", "tools": {
                "search_skills": "auto_approve", "load_skill": "auto_approve",
            }},
        }
        if mode == "team":
            member = client.post("/api/agents", json={"name": "Reviewer"}, headers=headers)
            assert member.status_code == 200
            config["available_sub_agent_ids"] = [member.json()["data"]["id"]]
        agent = client.post("/api/agents", json=config, headers=headers)
        assert agent.status_code == 200
        agent_id = agent.json()["data"]["id"]
        for name in ("visible-guide", "searchable-guide"):
            result = client.post("/api/skills", json={
                "name": name,
                "content": f"---\nname: {name}\ndescription: Guide\n---\nGuide body",
            }, headers=headers)
            assert result.status_code == 200
        result = client.put(f"/api/agents/{agent_id}/skills", json={
            "names": ["visible-guide", "searchable-guide"],
            "default_visible_skills": ["visible-guide"],
            "default_visible_skills_limit": 25,
        }, headers=headers)
        assert result.status_code == 200
        payload = _run_input()
        payload["forwardedProps"] = {"agentId": agent_id}
        response = client.post("/api/agent", json=payload, headers=headers)
        assert response.status_code == 200
        assert "RUN_FINISHED" in response.text

    request = provider.requests[0]
    prompt = "\n".join(
        block.text for message in request.messages if message.role == "system"
        for block in message.content if isinstance(block, TextBlock)
    )
    assert "<skill_name>visible-guide</skill_name>" in prompt
    assert "<skill_name>searchable-guide</skill_name>" not in prompt
    assert ("search_skills" in {tool.name for tool in request.tools}) == search
    if search:
        matches = [
            block.value for message in provider.requests[1].messages
            if message.role == "tool" and message.tool_call_id == "search"
            for block in message.content if isinstance(block, JsonBlock)
        ]
        assert matches == [[{"name": "searchable-guide", "description": "Guide"}]]
        assert any("<active_skill>" in block.text
                   for message in provider.requests[2].messages
                   for block in message.content if isinstance(block, TextBlock))


def test_team_preserves_each_members_fixed_skill_version(tmp_path):
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.test_a2a_resume import _step

    provider = ScriptedModelProvider(())
    host = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=host)) as client:
        headers = {"Authorization": f"Bearer {register_and_login(client)}"}

        def call(method, path, payload):
            response = client.request(method, path, headers=headers, json=payload)
            assert response.status_code == 200, response.text
            return response

        settings = {"tools": ["search_skills"], "tool_approval": {"default": "auto_approve"}}
        member = call("POST", "/api/agents", {"name": "Member", **settings}).json()["data"]["id"]
        team = call("POST", "/api/agents", {
            "name": "Team", "agent_mode": "team", "available_sub_agent_ids": [member], **settings,
        }).json()["data"]["id"]

        def publish(description):
            return call("POST", "/api/skills", {
                "name": "guide",
                "content": f"---\nname: guide\ndescription: {description}\n---\n{description}\n",
            }).json()["data"]

        first = publish("rootversion")
        second = publish("memberversion")
        for agent_id, version in ((team, first), (member, second)):
            url = f"/api/agents/{agent_id}/skills"
            call("PUT", url, {"names": ["guide"], "default_visible_skills": ["guide"]})
            call("PUT", f"{url}/{version['skill_id']}/version", {"version_id": version["version_id"]})
        publish("latestversion")
        provider._steps = (
            _step(1, "root load", "load_skill", {"skill_name": "guide"}),
            _step(2, "delegate", "sys_team_delegate_task", {"tasks": [{"agent_id": member, "content": "Search and load"}]}),
            _step(3, "search", "search_skills", {"query": "memberversion"}),
            _step(4, "member load", "load_skill", {"skill_name": "guide"}),
            _step(5, "child answer"),
            _step(6, "team answer"),
        )
        payload = _run_input()
        payload["forwardedProps"] = {"agentId": team}
        stream = call("POST", "/api/agent", payload)
        assert "RUN_FINISHED" in stream.text and "RUN_ERROR" not in stream.text

    assert "rootversion" in provider.requests[0].model_dump_json()
    assert "memberversion" in provider.requests[2].model_dump_json()
    assert "latestversion" not in provider.requests[2].model_dump_json()
    assert any(
        block.value == [{"name": "guide", "description": "memberversion"}]
        for message in provider.requests[3].messages if message.role == "tool"
        for block in message.content if isinstance(block, JsonBlock)
    )
    from pathlib import Path

    root_path = next(Path(message.metadata["workspace_path"]) for message in provider.requests[1].messages
                     if message.role == "tool" and message.tool_call_id == "call-1")
    member_path = next(Path(message.metadata["workspace_path"]) for message in provider.requests[4].messages
                       if message.role == "tool" and message.tool_call_id == "call-4")
    assert root_path != member_path
    assert "rootversion" in (root_path / "SKILL.md").read_text()
    assert "memberversion" in (member_path / "SKILL.md").read_text()
