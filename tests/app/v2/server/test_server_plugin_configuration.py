"""Admin plugin changes are durable, isolated from live Runs, and validated."""

from dataclasses import replace

import pytest

from app.v2.server.config.manifest import server_v2_manifest, server_v2_run_manifest
from app.v2.server.config.plugins import ServerPluginConfig, revision
from tests.app.v2.server.test_file_downloads import identity
from tests.app.v2.server.test_session_diagnostics import admin_headers


def test_fresh_deployment_pins_current_server_plugin_defaults(tmp_path):
    from app.v2.server.config.plugins import SERVER_DEFAULTS
    from tests.app.v2.server.conftest import make_settings

    settings = make_settings(tmp_path, mysql_url="mysql+aiomysql://test:test@localhost/sage")
    assert not ServerPluginConfig(tmp_path).path.exists()
    capabilities = server_v2_manifest(settings).runtime.capabilities
    for capability, plugin in SERVER_DEFAULTS.items():
        assert capabilities[capability].plugin == plugin
    assert capabilities["context.summarizer"].config == {"model_binding": "primary"}
    assert capabilities["agent.continuation-policy"].config == {"model_binding": "fast"}
    assert capabilities["memory.provider"].config == {"root": str(tmp_path / "runtime/memory")}
    assert capabilities["session-memory.provider"].config == {"root": str(tmp_path / "runtime/session-memory")}
    assert capabilities["workspace.initializer"].config == {"language": "zh"}
    assert capabilities["session.store"].plugin == "sage.session.mysql"
    assert capabilities["execution.scheduler"].config == {
        "max_concurrent_runs": 8,
        "max_concurrent_runs_per_tenant": 2,
        "max_pending_items": 1024,
    }


def test_admin_save_pending_reset_and_conflict(client):
    admin = admin_headers(client)
    user, _ = identity(client, "plugin-not-admin")
    store = ServerPluginConfig(client.app.state.service.paths.data_root)
    initial = client.get("/api/plugins/server", headers=admin).json()["data"]
    selection = {"plugin": "sage.memory.filesystem-bm25", "config": {"root": str(store.path.parent / "memory")}}
    body = {"revision": initial["revision"], "changes": {"memory.provider": selection}}
    assert client.put("/api/plugins/server", headers=user, json=body).status_code == 403
    assert client.put("/api/plugins/server", headers={"Authorization": "Bearer invalid"}, json=body).status_code == 401
    response = client.put("/api/plugins/server", headers=admin, json=body)
    assert response.status_code == 200, response.text
    saved = response.json()["data"]
    assert saved["pending"] == ["memory.provider"]
    assert saved["saved"]["memory.provider"]["plugin"] == selection["plugin"]
    assert next(p for p in saved["providers"] if p["capability"] == "memory.provider")["plugin_id"] == "sage.memory.filesystem-bm25"
    assert store.read() == saved["saved"]
    assert server_v2_manifest(client.app.state.service.settings).runtime.capabilities["memory.provider"].config["root"] != selection["config"]["root"]
    assert client.put("/api/plugins/server", headers=admin, json=body).status_code == 409
    reset = client.put("/api/plugins/server", headers=admin, json={"revision": saved["revision"], "changes": {"memory.provider": None}})
    assert reset.status_code == 200
    assert reset.json()["data"]["saved"] == {}
    assert reset.json()["data"]["pending"] == []


@pytest.mark.parametrize("changes", [
    {"memory.provider": {"plugin": "sage.memory.filesystem-bm25", "config": {}}},
    {"memory.provider": {"plugin": "sage.context.summarizer.model"}},
    {"memory.provider": {"plugin": "nonexistent"}},
    {"memory.provider": {"plugin": "sage.memory.noop", "config": {"root": "/tmp"}}},
    {"context.summarizer": {"plugin": "sage.context.summarizer.model", "config": {"model": {}}}},
    {"context.summarizer": {"plugin": "sage.context.summarizer.model", "config": {"timeout_seconds": 0}}},
    {"memory.provider": {"plugin": "sage.memory.noop", "scope": "run"}},
    {"session.store": {"plugin": "sage.session.ephemeral"}},
    {"model.provider": None},
])
def test_invalid_server_plugin_changes_are_atomic(client, changes):
    admin = admin_headers(client)
    before = client.get("/api/plugins/server", headers=admin).json()["data"]
    changes = {"context.token-estimator": {"plugin": "sage.context.token-estimator.unicode-heuristic"}, **changes}
    response = client.put("/api/plugins/server", headers=admin, json={"revision": before["revision"], "changes": changes})
    assert response.status_code == 422, response.text
    after = client.get("/api/plugins/server", headers=admin).json()["data"]
    assert after["saved"] == before["saved"]
    assert after["revision"] == before["revision"]


async def test_startup_loads_durable_memory_and_agent_inherits_server_defaults(service):
    store = ServerPluginConfig(service.settings.data_root)
    selections = {
        "memory.provider": {"plugin": "sage.memory.filesystem-bm25", "config": {"root": str(service.settings.data_root / "memory")}},
        "context.summarizer": {"plugin": "sage.context.summarizer.model", "config": {"timeout_seconds": 45, "model_binding": "primary"}},
    }
    store.save(selections, revision({}))
    await service.start()
    try:
        provider = service.application.service("memory.provider")
        assert provider.plugin_id == "sage.memory.filesystem-bm25"
        assert (await provider.health())["storage"] == "sqlite-fts5"
        assert provider.database_path.exists()
        from app.v2.server.catalog.records import AgentRecord
        agent = AgentRecord(id="configured", name="Configured")
        data = agent.package.model_dump(mode="json")
        data["manifest"]["runtime"]["capabilities"] = {"context.summarizer": {"plugin": "sage.context.summarizer.model", "config": {"max_source_tokens": 12000}}}
        from sagents.v2.agent.management import AgentPackageBundle
        agent = agent.model_copy(update={"package": AgentPackageBundle.model_validate(data)})
        manifest = server_v2_run_manifest(service.settings, agent=agent)
        assert manifest.runtime.capabilities["memory.provider"].plugin == provider.plugin_id
        assert manifest.runtime.capabilities["context.summarizer"].config == {"timeout_seconds": 45, "model_binding": "primary", "max_source_tokens": 12000}
        # A changed file cannot silently alter the running host or new Runs.
        store.save({"memory.provider": None}, revision(store.read()))
        assert server_v2_manifest(service.settings).runtime.capabilities["memory.provider"].plugin == provider.plugin_id
    finally:
        await service.close()


def test_public_plugin_defaults_reflect_active_overrides_without_host_secrets(client):
    host = client.app.state.service
    host.settings = replace(host.settings, mysql_url="mysql://secret", plugin_overrides={
        "context.summarizer": {"plugin": "sage.context.summarizer.extractive", "config": {"max_source_tokens": 14000}},
    })
    user, _ = identity(client, "plugin-defaults")
    data = client.get("/api/plugins", headers=user).json()["data"]
    assert data["defaults"]["context.summarizer"] == "sage.context.summarizer.extractive"
    assert data["default_config"]["context.summarizer"]["max_source_tokens"] == 14000
    assert "session.store" not in data["default_config"]
    assert "mysql://secret" not in str(data)
