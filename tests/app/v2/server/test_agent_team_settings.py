import pytest

from tests.app.v2.server.conftest import register_and_login
from tests.app.v2.server.test_catalog_packages import store as store


def identity(client, name="alice"):
    return {"Authorization": f"Bearer {register_and_login(client, name)}"}


@pytest.mark.parametrize("mode", ["fibre", "team"])
def test_team_settings_roundtrip_and_omitted_fields_are_preserved(client, mode):
    headers = identity(client)
    member = client.post("/api/agents", headers=headers, json={"name": "Writer"}).json()["data"]
    response = client.post("/api/agents", headers=headers, json={
        "name": "Director", "agent_mode": mode, "available_sub_agent_ids": [member["id"]],
    })
    assert response.status_code == 200, response.text
    agent = response.json()["data"]
    assert agent["agent_mode"] == mode
    assert agent["available_sub_agent_ids"] == [member["id"]]
    definition = agent["package"]["manifest"]["agents"][agent["id"]]
    assert definition["mode"] == mode and definition["subagents"] == [member["id"]]
    assert set(agent["package"]["dependencies"]) == {member["id"]}
    url = f'/api/agents/{agent["id"]}'
    renamed = client.put(url, headers=headers, json={"name": "Renamed"})
    assert renamed.status_code == 200, renamed.text
    assert client.get(url, headers=headers).json()["data"]["agent_mode"] == mode
    assert renamed.json()["data"]["available_sub_agent_ids"] == [member["id"]]
    cleared = client.put(url, headers=headers, json={
        "name": "Solo", "agent_mode": "simple", "available_sub_agent_ids": [],
    })
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["agent_mode"] == "simple"
    assert cleared.json()["data"]["available_sub_agent_ids"] == []
    assert not cleared.json()["data"]["package"].get("dependencies")


def test_team_members_must_be_owned_distinct_and_acyclic(client):
    headers = identity(client)
    foreign_headers = identity(client, "bob")
    foreign = client.get("/api/agents", headers=foreign_headers).json()["data"][0]
    a = client.post("/api/agents", headers=headers, json={"name": "A"}).json()["data"]
    b = client.post("/api/agents", headers=headers, json={"name": "B"}).json()["data"]
    url = f'/api/agents/{a["id"]}'
    for members in ([a["id"]], [foreign["id"]], ["missing"], [b["id"], b["id"]]):
        response = client.put(url, headers=headers, json={
            "name": "A", "agent_mode": "team", "available_sub_agent_ids": members,
        })
        assert response.status_code == 422, response.text
    response = client.put(url, headers=headers, json={
        "name": "A", "agent_mode": "team", "available_sub_agent_ids": [b["id"]],
    })
    assert response.status_code == 200, response.text
    cycle = client.put(f'/api/agents/{b["id"]}', headers=headers, json={
        "name": "B", "agent_mode": "team", "available_sub_agent_ids": [a["id"]],
    })
    assert cycle.status_code == 422, cycle.text


@pytest.mark.parametrize("mode,tool", [("team", "sys_team_delegate_task"), ("fibre", "sys_delegate_task")])
def test_catalog_run_delegates_and_freezes_latest_member_configuration(tmp_path, mode, tool):
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.conftest import make_test_service
    from tests.app.v2.server.test_a2a_resume import _step
    from tests.app.v2.server.test_agui_chat import _run_input

    provider = ScriptedModelProvider(())
    host = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=host)) as client:
        headers = identity(client)
        member = client.post("/api/agents", headers=headers, json={
            "name": "Writer", "instructions": "old member prompt", "tools": [],
        }).json()["data"]
        created = client.post("/api/agents", headers=headers, json={
            "name": "Director", "agent_mode": mode, "available_sub_agent_ids": [member["id"]],
            "tools": [], "tool_approval": {"default": "auto_approve"},
        })
        assert created.status_code == 200, created.text
        root = created.json()["data"]
        client.put(f'/api/agents/{member["id"]}', headers=headers, json={
            "name": "Writer", "instructions": "latest member prompt", "tools": [],
        })
        provider._steps = (
            _step(1, "delegate", tool, {"tasks": [{"agent_id": member["id"], "content": "Write"}]}),
            _step(2, "member answer"), _step(3, "team answer"),
        )
        body = _run_input()
        body["forwardedProps"] = {"agentId": root["id"]}
        response = client.post("/api/agent", headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert "RUN_FINISHED" in response.text and "RUN_ERROR" not in response.text, response.text
        assert len(provider.requests) == 3, "\n".join(m.model_dump_json() for r in provider.requests for m in r.messages if m.role == "tool")
        assert tool in {item.name for item in provider.requests[0].tools}
        assert "latest member prompt" in provider.requests[1].model_dump_json()
        assert tool not in {item.name for item in provider.requests[1].tools}
        store = host.application.runtime.session_store
        runs = client.portal.call(store.list_session_runs, "thread-1")
        command = client.portal.call(store.get_start_command, runs[0].run_id)
        snapshot = command.config.metadata["server_v2.composition"]["agent"]["package"]
        child = snapshot["dependencies"][member["id"]]
        assert child["manifest"]["agents"][member["id"]]["instructions"]["inline"] == "latest member prompt"


def test_team_member_shell_ceiling_is_enforced_during_delegation(tmp_path):
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.conftest import make_test_service
    from tests.app.v2.server.test_a2a_resume import _step
    from tests.app.v2.server.test_agui_chat import _run_input

    provider = ScriptedModelProvider(())
    host = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=host)) as client:
        headers = identity(client)
        client.put('/api/auth/execution-policy', headers=headers, json={"shell": "sandboxed"})
        member = client.post('/api/agents', headers=headers, json={
            "name": "Restricted", "execution_policy": {"shell": "deny"},
            "tools": ["execute_shell_command"], "tool_approval": {"default": "auto_approve"},
        }).json()["data"]
        root = client.post('/api/agents', headers=headers, json={
            "name": "Director", "agent_mode": "team", "available_sub_agent_ids": [member["id"]],
            "tools": [], "tool_approval": {"default": "auto_approve"},
        }).json()["data"]
        provider._steps = (
            _step(1, "delegate", "sys_team_delegate_task", {"tasks": [{"agent_id": member["id"], "content": "Try command"}]}),
            _step(2, "try command", "execute_shell_command", {"command": "touch must-not-exist.txt"}),
            _step(3, "command denied"), _step(4, "finished"),
        )
        body = _run_input()
        body['forwardedProps'] = {"agentId": root["id"]}
        response = client.post('/api/agent', headers=headers, json=body)
        assert response.status_code == 200 and 'RUN_ERROR' not in response.text, response.text
        assert len(provider.requests) == 4
        assert 'disabled by the execution grant' in provider.requests[2].model_dump_json()
        assert not list(tmp_path.rglob('must-not-exist.txt'))


async def test_team_settings_survive_database_reload(store):
    from app.v2.server.catalog.records import AgentRecord, upsert_agent
    from app.v2.server.catalog.repository import DatabaseCatalogStore

    child = AgentRecord(id="writer", name="Writer")
    await store.create_agent("alice", child)
    record, _ = upsert_agent(await store.get("alice"), {
        "id": "director", "name": "Director", "agent_mode": "team",
        "available_sub_agent_ids": [child.id],
    })
    await store.create_agent("alice", record)
    restored = await DatabaseCatalogStore(store.database).get_agent("alice", record.id)
    assert restored.agent_mode == "team"
    assert restored.available_sub_agent_ids == [child.id]
    assert restored.package == record.package


def test_member_uses_its_own_model_when_delegated():
    from app.v2.server.catalog.records import AgentRecord, ModelRecord, UserCatalog, upsert_agent
    from app.v2.server.catalog.model_config import app_models
    from sagents.v2.agent.management.loading import resolve_bundle
    from sagents.v2.package.manifest import CompositionResolver
    from sagents.v2.contracts.commands import RunConfig

    child = AgentRecord(id="writer", name="Writer", model_id="child-model")
    catalog = UserCatalog(agents=[child], models=[
        ModelRecord(id=name, model=name, api_key="test") for name in ("parent-model", "child-model")
    ])
    record, catalog = upsert_agent(catalog, {
        "id": "director", "name": "Director", "model_id": "parent-model",
        "agent_mode": "team", "available_sub_agent_ids": [child.id],
    })
    resolved = resolve_bundle(record.package, record.package.manifest.runtime, models=app_models(catalog))
    config = CompositionResolver().resolve_child_run_config(resolved, child.id,
        parent_config=RunConfig(model_bindings={"primary": "parent-model"}), tools=(), skills=())
    assert config.model_bindings["primary"] == "child-model"


def test_fibre_spawned_expert_can_execute_in_its_own_run(tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.conftest import make_test_service
    from tests.app.v2.server.test_a2a_resume import _step
    from tests.app.v2.server.test_agui_chat import _run_input

    delegate = _step(2, "delegate", "sys_delegate_task", {"tasks": [{"agent_id": "pending", "content": "Answer"}]})
    def use_spawned_id(request):
        result = next(block.value for message in request.messages if message.tool_call_id == "call-1" for block in message.content)
        delegate.events[0].response.tool_calls[0].arguments["tasks"][0]["agent_id"] = result["agent_id"]
    provider = ScriptedModelProvider((
        _step(1, "spawn", "sys_spawn_agent", {"name": "Expert", "description": "An expert", "system_prompt": "Act as an expert"}),
        replace(delegate, assertion=use_spawned_id), _step(3, "expert answer"), _step(4, "finished"),
    ))
    host = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=host)) as client:
        headers = identity(client)
        root = client.post('/api/agents', headers=headers, json={
            "name": "Fibre", "agent_mode": "fibre", "tools": [],
            "tool_approval": {"default": "auto_approve"},
        }).json()["data"]
        body = _run_input()
        body['forwardedProps'] = {"agentId": root["id"]}
        response = client.post('/api/agent', headers=headers, json=body)
        assert response.status_code == 200 and 'RUN_ERROR' not in response.text, response.text
        assert len(provider.requests) == 4, "\n".join(m.model_dump_json() for r in provider.requests for m in r.messages if m.role == "tool")
        assert provider.requests[2].run_id != provider.requests[0].run_id


@pytest.mark.parametrize("parent,enabled,expected", [
    ("parent", ("mcp_read",), ["mcp_read"]),
    ("parent", ("mcp_write",), []),
    (None, ("mcp_read",), []),
])
async def test_spawned_external_tools_stay_within_parent_and_child_grants(parent, enabled, expected):
    from types import SimpleNamespace
    from app.v2.server.runtime.integrations.external_tools import ScopedExternalTools
    from tests.app.v2.server.test_external_tool_scope import Provider

    async def command_reader(run_id):
        return SimpleNamespace(agent_id="spawned", parent_run_id=parent,
            config=SimpleNamespace(enabled_tools=enabled))
    tools = ScopedExternalTools(Provider(), {}, command_reader=command_reader,
        dynamic_tools=("mcp_read",))
    assert [tool.name for tool in await tools.list_tools(run_id="child")] == expected
