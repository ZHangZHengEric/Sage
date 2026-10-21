"""The displayed selections must be the same selections a catalog Run uses."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from anyio.from_thread import BlockingPortal
    from sagents.v2.agent.management.contracts import AgentPackageBundle

from sagents.v2.contracts.errors import RuntimeErrorInfo

from sagents.v2.contracts.events import RunEventData

import pytest

from app.v2.server.catalog.records import AgentRecord, UserCatalog, upsert_agent
from app.v2.server.config.manifest import server_v2_run_manifest
from sagents.v2.contracts.errors import SageV2Error
from sagents.v2.package.manifest.runtime import CapabilitySelection, merge_capability_selections
from sagents.v2.runtime.artifact import SessionArtifactStore
from sagents.v2.runtime.artifact.binding import bind_artifact_store
from sagents.v2.runtime.artifact.plugins.ephemeral import InMemoryArtifactStore
from tests.app.v2.server.test_file_downloads import identity
from tests.app.v2.server.test_session_diagnostics import admin_headers


def test_merge_same_plugin_inherits_and_changed_plugin_replaces():
    defaults = {"x": CapabilitySelection(plugin="one", config={"a": 1, "b": 2})}
    result = merge_capability_selections(defaults, {"x": CapabilitySelection(plugin="one", config={"b": 3})})
    assert result["x"].config == {"a": 1, "b": 3}
    assert defaults["x"].config == {"a": 1, "b": 2}
    assert merge_capability_selections(defaults, {"x": CapabilitySelection(plugin="two")})["x"].config == {}


def test_persisted_forbidden_package_is_rejected_at_run_composition():
    agent = AgentRecord(id="demo", name="demo")
    cast('AgentPackageBundle', agent.package).manifest.runtime.capabilities["session.store"] = CapabilitySelection(plugin="sage.session.mysql")
    with pytest.raises(SageV2Error, match="session.store.*不允许"):
        server_v2_run_manifest(agent=agent)


def test_builtin_agent_options_do_not_silently_accept_unknown_binding():
    with pytest.raises(SageV2Error, match="default"):
        upsert_agent(UserCatalog(), {"id": "demo", "name": "demo", "plugins": {
            "context.summarizer": {"plugin": "sage.context.summarizer.model", "name": "ignored"},
        }})


def test_public_and_admin_inventory_show_session_artifact_selection(client):
    user, _ = identity(client, "artifact-config")
    public = client.get("/api/plugins", headers=user).json()["data"]
    admin = client.get("/api/plugins/server", headers=admin_headers(client)).json()["data"]
    assert public["defaults"]["artifact.store"] == "sage.session.filesystem"
    selected = next(item for item in admin["providers"] if item["capability"] == "artifact.store")
    assert selected["plugin_id"] == "sage.session.filesystem"
    assert selected["implementation"] == "SessionArtifactStore"
    assert "artifact.store" not in admin["configurable"]


async def test_scoped_artifacts_keep_selected_backend_and_isolate_runs():
    store = InMemoryArtifactStore()
    first, other = bind_artifact_store(store, "first"), bind_artifact_store(store, "other")
    await first.put(artifact_id="same", media_type="text/plain", content=_chunks(b"first"))
    await other.put(artifact_id="same", media_type="text/plain", content=_chunks(b"other"))
    assert b"".join([part async for part in (await first.get("same"))[1]]) == b"first"
    assert b"".join([part async for part in (await other.get("same"))[1]]) == b"other"
    session = SessionArtifactStore(object())
    bound = bind_artifact_store(session, "first")
    assert isinstance(bound, SessionArtifactStore)
    assert bound.session_store is session.session_store


async def _chunks(value):
    yield value


def test_agent_id_and_package_entrypoints_emit_the_same_agui_result(tmp_path):
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from tests.app.v2.server.conftest import make_test_service, scripted_hello
    from tests.app.v2.server.test_session_diagnostics import _run_input

    host = make_test_service(tmp_path, model_provider=scripted_hello(3))
    with TestClient(create_app(service=host)) as client:
        headers, _ = identity(client, "same-package")
        agent = client.get("/api/agents", headers=headers).json()["data"][0]
        request = _run_input()
        first = client.post("/api/agent", headers=headers, json=request)
        second = client.post("/api/agent-package", headers=headers, json={
            **request, "threadId": "package-thread", "runId": "package-run",
            "agent_package": agent["package"],
        })
        saved = client.get("/api/threads/package-thread/package", headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"] == agent["package"]
        page = client.get("/api/threads/package-thread/events", headers=headers).json()["data"]
        assert page["has_package"] is True
        third = client.post("/api/agent-package", headers=headers, json={
            **request, "threadId": "package-thread", "runId": "package-followup",
            "agent_package": saved.json()["data"],
        })
        assert third.status_code == 200 and 'RUN_FINISHED' in third.text and 'RUN_ERROR' not in third.text, third.text
        assert first.status_code == second.status_code == 200, second.text
        assert first.headers["content-type"] == second.headers["content-type"]
        other, _ = identity(client, "different-owner")
        assert client.get("/api/threads/package-thread/package", headers=other).status_code == 404
        for response in (first, second):
            assert 'TEXT_MESSAGE_CONTENT' in response.text, response.text
            assert 'hello' in response.text
            assert 'RUN_FINISHED' in response.text
            assert 'RUN_ERROR' not in response.text, response.text


def test_package_entrypoint_rejects_server_override_before_execution(client):
    from tests.app.v2.server.test_session_diagnostics import _run_input
    headers, _ = identity(client, "invalid-package")
    agent = client.get("/api/agents", headers=headers).json()["data"][0]
    bundle = agent["package"]
    bundle["manifest"]["runtime"]["capabilities"]["session.store"] = {"plugin": "sage.session.ephemeral"}
    response = client.post("/api/agent-package", headers=headers, json={
        **_run_input(), "agent_package": bundle,
    })
    assert response.status_code in (400, 403, 422)
    assert "session.store" in response.text and "不允许" in response.text


@pytest.mark.timeout(15)
@pytest.mark.parametrize("route", ["agent", "agent-package"])
@pytest.mark.parametrize("tool,arguments,error_code", [
    ("nonexistent_tool", {}, "tool.not_found"),
    ("file_write", {"file_path": "result.txt"}, "tool.arguments_invalid"),
])
def test_both_entrypoints_recover_tool_errors_and_deliver_file(
    tmp_path, route, tool, arguments, error_code,
):
    from fastapi.testclient import TestClient
    from app.v2.server.main import create_app
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from tests.app.v2.server.conftest import make_test_service
    from tests.app.v2.server.test_a2a_resume import _step
    from tests.app.v2.server.test_agui_chat import _run_input

    provider = ScriptedModelProvider((
        _step(1, "try", tool, arguments),
        _step(2, "correct", "file_write", {"file_path": "result.txt", "content": "delivered"}),
        _step(3, "finished"),
    ))
    host = make_test_service(tmp_path, model_provider=provider)
    with TestClient(create_app(service=host)) as client:
        headers, _ = identity(client, "tool-recovery")
        agent = client.get("/api/agents", headers=headers).json()["data"][0]
        body = _run_input()
        body["forwardedProps"] = {"agentId": agent["id"]}
        if route == "agent-package":
            body["agent_package"] = agent["package"]
        response = client.post(f"/api/{route}", headers=headers, json=body)
        assert response.status_code == 200, response.text
        assert "RUN_FINISHED" in response.text and "RUN_ERROR" not in response.text
        download = client.get("/api/workspace/download", headers=headers,
                              params={"thread_id": "thread-1", "path": "result.txt"})
        assert download.status_code == 200 and download.content == b"delivered"
        store = host.application.entrypoint().runtime.session_store
        runs = cast('BlockingPortal', client.portal).call(store.list_session_runs, "thread-1")
        assert len(runs) == 1 and runs[0].state.value == "completed"
        events = cast('BlockingPortal', client.portal).call(store.read_events, runs[0].run_id)
        assert any(event.type == "tool.call.failed" and cast(RunEventData, event.data).error
                   and cast(RuntimeErrorInfo, cast(RunEventData, event.data).error).code == error_code for event in events)
        assert len(provider.requests) == 3
        assert error_code in provider.requests[1].model_dump_json()


@pytest.mark.asyncio
async def test_registered_model_factory_resolves_each_agent_binding(tmp_path):
    from tests.sagents.v2.sdk_fixture import build_registered_app
    from tests.sagents.v2.test_standard_execution_configuration import response, run
    from sagents.v2.model.contracts import ModelToolCall
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from sagents.v2.package.manifest import SageManifest
    from sagents.v2.package.manifest.runtime import RuntimeConfig
    seen = []
    def factory(scope, dependencies):
        route = scope.agent_configuration["model_routes"]["primary"]
        seen.append((scope.agent_id, route["model"]))
        steps = (response(ModelToolCall(tool_call_id="delegate", name="sys_team_delegate_task",
            arguments={"tasks": [{"agent_id": "child", "content": "Work"}]})), response()) if route["model"] == "main" else (response(),)
        return ScriptedModelProvider(steps)
    runtime = RuntimeConfig.model_validate({"capabilities": {
        "agent.continuation-policy": {"plugin": "sage.agent.continuation.deterministic"},
        "tool.selection-policy": {"plugin": "sage.tool-selection.direct"},
    }})
    def package(name, **fields):
        return SageManifest.model_validate({"kind": "agent-package", "metadata": {
            "id": "model." + name, "name": name, "version": "1"},
            "agents": {name: {"name": name, "instructions": {"inline": "Help"},
                              "models": {"primary": "custom-" + name}, **fields}},
            "entrypoint": {"agent": name}})
    app = await build_registered_app(tmp_path, runtime=runtime, model_factory=factory, models={"models": {
        "custom-main": {"provider": "openai-responses", "model": "main"},
        "custom-child": {"provider": "openai-responses", "model": "child"},
    }})
    try:
        child = await app.load_agent(package("child"))
        main = await app.load_agent(package("main", mode="team", subagents=["child"]), subagents={"child": child})
        result, events = await run(app, main, "route-bindings")
        assert result.state.value == "completed", events
        assert {route for _, route in seen} == {"main", "child"}
        assert len({agent for agent, _ in seen}) == 2
        assert any(item.plugin_id == "test.fixture.model-factory" for item in main.resolved_plan.providers)
    finally:
        await app.close()


def test_desktop_server_only_share_sagents_import_boundary():
    import ast
    from pathlib import Path
    root = Path(__file__).resolve().parents[4]
    for folder, forbidden in (("sagents/v2", ("app.v2.server", "app.v2.desktop")),
                              ("app/v2/desktop", ("app.v2.server",)),
                              ("app/v2/server", ("app.v2.desktop",))):
        for path in (root / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = [node.module or ""] if isinstance(node, ast.ImportFrom) else (
                    [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
                assert not any(name == item or name.startswith(item + ".") for name in names for item in forbidden), str(path)


def test_empty_tool_selection_is_not_expanded_at_execution(client):
    headers, _ = identity(client, "explicit-tools")
    created = client.post("/api/agents", headers=headers, json={"name": "No tools", "tools": []})
    assert created.status_code == 200, created.text
    payload = created.json()["data"]
    record = AgentRecord.model_validate({key: payload[key] for key in ("id", "name", "package")})
    assert record.tools == []
    assert server_v2_run_manifest(agent=record).agents[record.id].tools == ()
    default = client.post("/api/agents", headers=headers, json={"name": "Default tools"}).json()["data"]
    assert "file_read" in default["tools"]
    assert default["package"]["manifest"]["agents"][default["id"]]["tools"] == default["tools"]
