"""Plugin inventory and persisted, scoped Agent overrides."""

from app.v2.server.catalog.plugins import AGENT_DEFAULTS, plugin_options
from app.v2.server.config.manifest import server_v2_run_manifest
from tests.app.v2.server.test_file_downloads import identity
from tests.app.v2.server.test_session_diagnostics import admin_headers


def test_all_builtin_plugins_and_defaults_are_visible(client):
    assert client.get("/api/plugins").status_code == 401
    user, _ = identity(client, "plugin-viewer")
    response = client.get("/api/plugins", headers=user)
    assert response.status_code == 200
    data = response.json()["data"]
    assert len(data["plugins"]) == len(plugin_options())
    assert len(data["plugins"]) > 30
    by_id = {p["id"]: p for p in data["plugins"]}
    for cap, plugin in AGENT_DEFAULTS.items():
        assert cap in by_id[plugin]["capabilities"]
    assert data["defaults"]["context.summarizer"] == "sage.context.summarizer.model"
    assert data["default_config"]["context.summarizer"]["model_binding"] == "primary"
    model = by_id["sage.context.summarizer.model"]
    assert "model" not in model["schema"]["properties"]
    assert model["schema"]["properties"]["timeout_seconds"]["default"] == 300
    assert client.get("/api/plugins/server", headers=user).status_code == 403
    server = client.get("/api/plugins/server", headers=admin_headers(client))
    assert server.status_code == 200
    assert server.json()["data"]["providers"]


def test_agent_plugin_selection_roundtrips_and_is_used_by_run_manifest(client):
    user, _ = identity(client, "plugin-owner")
    selection = {
        "context.summarizer": {
            "plugin": "sage.context.summarizer.model",
            "config": {"max_source_tokens": 16000, "timeout_seconds": 30},
        }
    }
    result = client.post(
        "/api/agents", headers=user, json={"name": "Configured", "plugins": selection}
    )
    assert result.status_code == 200, result.text
    record = result.json()["data"]
    agent_id = record["id"]
    from app.v2.server.catalog.records import AgentRecord

    agent = AgentRecord.model_validate(
        {
            **{k: v for k, v in record.items() if k != "package_ref"},
            "model_id": record.get("model_id") or "",
        }
    )
    manifest = server_v2_run_manifest(agent=agent)
    actual = manifest.runtime.capabilities["context.summarizer"]
    assert actual.config["max_source_tokens"] == 16000
    assert actual.config["timeout_seconds"] == 30
    # Omission preserves; an explicit empty object resets managed selections.
    updated = client.put(
        f"/api/agents/{agent_id}", headers=user, json={"name": "Renamed"}
    )
    assert updated.status_code == 200
    assert (
        updated.json()["data"]["package"]["manifest"]["runtime"]["capabilities"][
            "context.summarizer"
        ]["config"]["timeout_seconds"]
        == 30
    )
    reset = client.put(
        f"/api/agents/{agent_id}", headers=user, json={"name": "Reset", "plugins": {}}
    )
    assert reset.status_code == 200
    assert (
        "context.summarizer"
        not in reset.json()["data"]["package"]["manifest"]["runtime"]["capabilities"]
    )


def test_agent_cannot_replace_host_plugins_or_injected_dependencies(client):
    user, _ = identity(client, "plugin-validation")
    for selection in [
        {"session.store": {"plugin": "sage.session.mysql"}},
        {"context.summarizer": {"plugin": "sage.context.reducer.window"}},
        {
            "context.summarizer": {
                "plugin": "sage.context.summarizer.model",
                "config": {"model": {}},
            }
        },
        {
            "context.summarizer": {
                "plugin": "sage.context.summarizer.model",
                "config": {"timeout_seconds": 0},
            }
        },
    ]:
        response = client.post(
            "/api/agents", headers=user, json={"name": "Invalid", "plugins": selection}
        )
        assert response.status_code in (400, 422), response.text


async def test_materialized_defaults_use_model_summary_and_honor_explicit_fallback(
    service,
):
    from sagents.v2.context.plugins.summarizer_model import ModelConversationSummarizer
    from sagents.v2.context.plugins.summarizer_extractive import (
        ExtractiveConversationSummarizer,
    )
    from sagents.v2.testing.plugins import ScriptedModelProvider
    from app.v2.server.config.manifest import server_v2_manifest
    from sagents.v2.package.manifest.runtime import CapabilitySelection

    await service.start()
    try:
        model = ScriptedModelProvider(())
        manifest = server_v2_manifest(service.settings)
        ports = await service.application.materialize_agent(
            manifest, tenant_id="owner", agent_id="main", model=model
        )
        assert isinstance(ports.summarizer, ModelConversationSummarizer)
        assert ports.summarizer.model is model
        assert ports.summarizer.model_binding == "primary"
        runtime = manifest.runtime.model_copy(
            update={
                "capabilities": {
                    **manifest.runtime.capabilities,
                    "context.summarizer": CapabilitySelection(
                        plugin="sage.context.summarizer.extractive"
                    ),
                }
            }
        )
        explicit = manifest.model_copy(update={"runtime": runtime})
        ports = await service.application.materialize_agent(
            explicit, tenant_id="owner", agent_id="main", model=model
        )
        assert isinstance(ports.summarizer, ExtractiveConversationSummarizer)
    finally:
        await service.close()
