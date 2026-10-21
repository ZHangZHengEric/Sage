"""Web edits survive persistence and reach model construction and Run manifests."""

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from sagents.v2.model.capability_contracts import ModelCapabilityProbeStatus

from types import SimpleNamespace

import pytest

from app.v2.server.catalog.records import apply_upsert, empty_catalog
from app.v2.server.config.manifest import server_v2_run_manifest
from app.v2.server.runtime.model_pool import ModelClientPool
from app.v2.server.runtime.models import _build_catalog_provider
from sagents.v2.model.capability_contracts import (
    ModelCapabilityProfile,
    ModelCapabilityProbeOutcome,
)
from tests.app.v2.server.conftest import register_and_login


def profile(record):
    return ModelCapabilityProfile(
        plugin_id="sage.model.openai-chat-completions",
        plugin_version="3.0.0",
        protocol="openai-chat-completions",
        route_fingerprint=record.fingerprint(),
        effective_max_output_tokens=2048,
        outcomes=tuple(
            ModelCapabilityProbeOutcome(name=name, status=cast('ModelCapabilityProbeStatus', "supported"))
            for name in (
                "connection",
                "multimodal",
                "structured_output",
                "json_object",
                "tool_calling",
                "reasoning_control",
            )
        ),
        invocation_strategy={"max_output_tokens_field": "max_completion_tokens"},
    )


def test_catalog_model_options_preserved_on_default_change_and_invalidate_profile():
    catalog = empty_catalog()
    record, catalog = apply_upsert(
        catalog,
        {
            "model": "demo",
            "api_key": "secret",
            "request": {
                "max_output_tokens": 4096,
                "temperature": 0.4,
                "extra": {"seed": 7},
            },
            "limits": {"context_window": 128000},
            "capabilities": {"multimodal": True},
        },
    )
    record, catalog = apply_upsert(
        catalog,
        {
            **record.public_dict(),
            "api_key": "",
            "capability_profile": profile(record).model_dump(),
        },
    )
    assert record.capability_profile is not None
    record, catalog = apply_upsert(
        catalog, {"id": record.id, "model": record.model, "is_default": True}
    )
    assert record.request.temperature == 0.4
    assert record.request.extra == {"seed": 7}
    assert record.capability_profile is not None
    key = ModelClientPool._key("alice", record)
    changed, _ = apply_upsert(catalog, {"id": record.id, "model": "other"})
    assert changed.capability_profile is None
    assert ModelClientPool._key("alice", changed) != key
    assert "secret" not in str(record.public_dict())


def test_options_and_profile_reach_provider_and_app_catalog(monkeypatch):
    monkeypatch.setattr(
        "sagents.v2.model.plugins.openai_compatible.AsyncOpenAI",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    record, _ = apply_upsert(
        empty_catalog(),
        {
            "model": "demo",
            "api_key": "secret",
            "request": {
                "max_output_tokens": 4096,
                "temperature": 0.4,
                "extra": {"seed": 7},
            },
        },
    )
    record.capability_profile = profile(record)
    provider = _build_catalog_provider(record)
    assert getattr(provider, 'config').default_temperature == 0.4
    assert getattr(provider, 'config').default_max_output_tokens == 2048
    assert getattr(provider, 'config').max_output_tokens_field == "max_completion_tokens"
    from app.v2.server.catalog.model_config import app_models
    from app.v2.server.catalog.records import UserCatalog
    catalog = app_models(UserCatalog(models=[record], agents=[], default_agent_id=""))
    route = catalog.models[record.id]
    assert route.request.temperature == 0.4
    assert route.request.extra == {"seed": 7}
    assert route.capability_profile == record.capability_profile
    assert "secret" not in catalog.model_dump_json()


def test_web_model_round_trip_and_agent_budgets(client):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    payload = {
        "model": "gemini-demo",
        "protocol": "gemini-generate-content",
        "api_key": "test-key",
        "request": {
            "max_output_tokens": 8192,
            "temperature": 0,
            "top_p": 0.7,
            "reasoning_effort": "high",
            "extra": {"thinking_budget": 1024},
        },
        "limits": {"context_window": 128000},
        "capabilities": {"multimodal": True, "tool_calling": True},
    }
    response = client.post("/api/models", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    saved = response.json()["data"]
    detail = client.get(f"/api/models/{saved['id']}", headers=headers).json()["data"]
    assert detail["request"] == saved["request"]
    assert detail["limits"]["context_window"] == 128000
    agent = client.post(
        "/api/agents",
        headers=headers,
        json={"name": "Budgeted", "budgets": {"max_steps": 12, "output_tokens": 2048}},
    ).json()["data"]
    edited = client.put(
        f"/api/agents/{agent['id']}", headers=headers, json={"name": "Renamed"}
    ).json()["data"]
    assert (
        edited["package"]["manifest"]["agents"][agent["id"]]["budgets"]["max_steps"]
        == 12
    )
    from app.v2.server.catalog.records import AgentRecord

    record = AgentRecord.model_validate(
        {key: edited[key] for key in ("id", "name", "package")}
    )
    assert (
        server_v2_run_manifest(agent=record).agents[record.id].budgets.output_tokens
        == 2048
    )
    assert (
        client.post(
            "/api/agents",
            headers=headers,
            json={"name": "Too many", "budgets": {"max_steps": 10001}},
        ).status_code
        == 422
    )


def test_probe_uses_own_credentials_does_not_save_and_always_closes(
    client, monkeypatch
):
    from app.v2.server.runtime import models

    closed = []
    seen = []

    async def create(record):
        seen.append(record)

        async def probe(request):
            assert request.route_fingerprint == record.fingerprint()
            return profile(record)

        return SimpleNamespace(probe_capabilities=probe)

    async def close(provider):
        closed.append(provider)

    monkeypatch.setattr(models, "create_catalog_provider", create)
    monkeypatch.setattr(models, "close_model_provider", close)
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    saved = client.post(
        "/api/models", headers=headers, json={"model": "demo", "api_key": "own-secret"}
    ).json()["data"]
    response = client.post(
        "/api/models/probe",
        headers=headers,
        json={"id": saved["id"], "model": "draft", "api_key": ""},
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert seen[0].api_key.get_secret_value() == "own-secret"
    assert len(closed) == 1
    assert (
        client.get("/api/models", headers=headers).json()["data"][0]["model"] == "demo"
    )
    assert "own-secret" not in response.text
    foreign = {"Authorization": f"Bearer {register_and_login(client, 'bob')}"}
    denied = client.post(
        "/api/models/probe", headers=foreign, json={"id": saved["id"], "model": "demo"}
    )
    assert denied.status_code == 422
    assert len(seen) == 1

    async def fail(record):
        async def probe(request):
            raise RuntimeError("probe failed")

        return SimpleNamespace(probe_capabilities=probe)

    monkeypatch.setattr(models, "create_catalog_provider", fail)
    with pytest.raises(RuntimeError, match="probe failed"):
        client.post(
            "/api/models/probe",
            headers=headers,
            json={"model": "demo", "api_key": "temp"},
        )
    assert len(closed) == 2


def test_stale_probe_plugin_version_is_not_advertised_or_applied(monkeypatch):
    monkeypatch.setattr(
        "sagents.v2.model.plugins.openai_compatible.AsyncOpenAI",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    record, _ = apply_upsert(empty_catalog(), {"model": "demo", "api_key": "key"})
    record.capability_profile = profile(record).model_copy(
        update={"plugin_version": "obsolete"}
    )
    assert record.public_dict()["capability_profile"] is None
    assert getattr(_build_catalog_provider(record), 'config').max_output_tokens_field == "auto"


@pytest.mark.asyncio
async def test_probe_admission_limits_parallel_work_and_releases_after_error():
    from app.v2.server.catalog.service import CatalogService
    from sagents.v2.contracts.errors import SageV2Error

    service = CatalogService(None, mcp_plugins=None, a2a_plugins=None, skills=None)
    async with service.model_probe_slot("alice"):
        with pytest.raises(SageV2Error, match="探测正在进行"):
            async with service.model_probe_slot("alice"):
                pass
    with pytest.raises(RuntimeError):
        async with service.model_probe_slot("alice"):
            raise RuntimeError("failed")
    async with service.model_probe_slot("alice"):
        assert service._probing_users == {"alice"}
    assert service._probing_users == set()


def test_agent_fast_model_create_update_and_clear_use_app_model_ids(client):
    headers = {"Authorization": f"Bearer {register_and_login(client)}"}
    ids = []
    for name in ("primary", "fast"):
        response = client.post("/api/models", headers=headers, json={"model": name, "api_key": "test-key"})
        assert response.status_code == 200, response.text
        ids.append(response.json()["data"]["id"])
    response = client.post("/api/agents", headers=headers, json={"name": "With fast model", "model_id": ids[0], "fast_model_id": ids[1]})
    assert response.status_code == 200, response.text
    agent = response.json()["data"]
    for fast_id in (ids[1], ids[0], ""):
        response = client.put(f"/api/agents/{agent['id']}", headers=headers, json={"name": agent["name"], "model_id": ids[0], "fast_model_id": fast_id})
        assert response.status_code == 200, response.text
        saved = response.json()["data"]
        manifest = saved["package"]["manifest"]
        assert "models" not in manifest and "credentials" not in manifest
        bindings = manifest["agents"][agent["id"]]["models"]
        assert bindings["primary"] == ids[0]
        assert bindings.get("fast", "") == fast_id
        assert saved["fast_model_id"] == (fast_id or None)
