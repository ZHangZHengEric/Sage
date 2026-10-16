"""Public App catalog contract and immutable revision recovery boundaries."""
import asyncio

import pytest
from pydantic import ValidationError
from sagents.v2 import SAgentBuilder
from sagents.v2.model.catalog import model_catalog_input
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.testing.plugins import ScriptedModelProvider


def package(package_id="assistant", model_id="shared"):
    return {"metadata": {"id": package_id, "name": package_id, "version": "1"},
            "agents": {"main": {"name": "Assistant", "instructions": {"inline": "Help."},
                                "models": {"primary": model_id}}},
            "entrypoint": {"agent": "main"}}


def config(model="first"):
    return {"models": {"shared": {"provider": "openai-responses", "model": model,
                                  "request": {"reasoning_effort": "high"},
                                  "capabilities": {"multimodal": True}}}}


def builder(tmp_path):
    return SAgentBuilder().with_defaults(session_root=tmp_path).with_model_provider(ScriptedModelProvider(()))


@pytest.mark.parametrize("field", ["models", "credentials"])
def test_package_rejects_model_connection_entrypoints(field):
    value = package()
    value[field] = {}
    with pytest.raises(ValidationError):
        SageManifest.model_validate(value)


def test_catalog_inputs_and_references(tmp_path):
    import json
    path = tmp_path / "models.json"
    path.write_text(json.dumps(config()))
    assert model_catalog_input(path) == model_catalog_input(config_text=path.read_text())
    assert set(model_catalog_input(config()).selected(iter(["shared"])).models) == {"shared"}
    with pytest.raises(ValueError, match="mutually exclusive"):
        model_catalog_input(path, config_text="{}")
    with pytest.raises(ValueError, match="unknown App credential"):
        model_catalog_input({"models": {"x": {"provider": "openai-responses", "model": "x", "credential": "missing"}}})


@pytest.mark.asyncio
async def test_model_update_reloads_same_package_without_mutating_old_handle(tmp_path):
    app = await builder(tmp_path).build(models=config())
    try:
        old = await app.load_agent(package())
        await app.update_model("shared", config("second")["models"]["shared"])
        new = await app.load_agent(package())
        assert old.composition_hash != new.composition_hash
        assert old._resolved.model_routes["shared"]["model"] == "first"
        assert new._resolved.model_routes["shared"]["model"] == "second"
        assert await app.load_agent(package()) is new
        assert old._resolved.model_routes["shared"]["request"]["reasoning_effort"] == "high"
        snapshot = app.models
        snapshot.models.clear()
        assert "shared" in app.models.models
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_unrelated_models_do_not_change_agent_identity(tmp_path):
    app = await builder(tmp_path).build(models=config())
    try:
        first = await app.load_agent(package())
        await app.update_model("other", {"provider": "openai-responses", "model": "other"})
        assert await app.load_agent(package()) is first
        second = await app.load_agent(package("another"))
        assert second._resolved.model_routes == first._resolved.model_routes
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_invalid_catalog_update_is_atomic_and_unknown_ids_fail(tmp_path):
    app = await builder(tmp_path).build(models=config())
    try:
        old = app.models
        with pytest.raises(ValidationError):
            await app.update_model("shared", {"provider": "openai-responses", "model": "x", "typo": True})
        assert app.models == old
        with pytest.raises(ValueError, match="unknown App model IDs"):
            await app.load_agent(package(model_id="missing"))
        assert app.loaded_agents == ()
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_old_catalog_revision_restores_from_archive(tmp_path):
    app = await builder(tmp_path).build(models=config())
    old = await app.load_agent(package())
    archived = app._loaded_agents.store.read(old.composition_hash)
    await app.close()
    app = await builder(tmp_path).build(models=config("replacement"))
    try:
        new = await app.load_agent(package())
        restored = await app._loaded_agents.load(archived, historical=True, expected_hash=old.composition_hash)
        assert restored.composition_hash == old.composition_hash
        assert restored._resolved.model_routes["shared"]["model"] == "first"
        assert app.loaded_agents == (new,)
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_parallel_catalog_updates_do_not_lose_entries(tmp_path):
    app = await builder(tmp_path).build(models=config())
    try:
        await asyncio.gather(*(app.update_model(f"model-{i}", {"provider": "openai-responses", "model": str(i)}) for i in range(12)))
        assert len(app.models.models) == 13
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_registry_uses_current_app_catalog_for_new_packages(tmp_path):
    app = await builder(tmp_path).build(models=config())
    try:
        await app.load_agent(package())
        await app.update_model("later", {"provider": "openai-responses", "model": "later"})
        registry = app.service("package.registry")
        draft = await registry.save_draft(SageManifest.model_validate(package("new-agent", "later")))
        assert draft.package_id == "new-agent"
    finally:
        await app.close()
