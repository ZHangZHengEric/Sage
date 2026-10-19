from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.v2.server.catalog.records import apply_upsert, empty_catalog
from app.v2.server.routers.schemas.catalog import ModelBody
from app.v2.server.runtime.models import ServerModelClients, _build_catalog_provider
from tests.app.v2.server.conftest import register_and_login
from tests.app.v2.server.fakes import MemoryCatalogStore


async def _save_demo_model(catalog: MemoryCatalogStore, user_id: str = "user-1"):
    return await catalog.upsert_model(
        user_id,
        {
            "protocol": "openai-chat-completions",
            "base_url": "https://example.invalid/v1",
            "model": "demo-model",
            "api_key": "sk-test",
            "is_default": True,
        },
    )


@pytest.mark.asyncio
async def test_transport_pool_has_no_session_owner_routing(monkeypatch):
    pool = ServerModelClients()
    assert not hasattr(pool, "bind_session_user")
    assert not hasattr(pool, "stream")
    await pool.close()


def test_catalog_uses_orcarouter_default_base_url_when_omitted():
    record, _ = apply_upsert(
        empty_catalog(),
        {
            "protocol": "orcarouter",
            "model": "orcarouter-model",
            "api_key": "test-key",
        },
    )
    assert record.base_url == "https://api.orcarouter.ai/v1"


def test_catalog_preserves_custom_base_url_for_orcarouter():
    record, _ = apply_upsert(
        empty_catalog(),
        {
            "protocol": "orcarouter",
            "base_url": "https://gateway.example/v1",
            "model": "orcarouter-model",
            "api_key": "test-key",
        },
    )
    assert record.base_url == "https://gateway.example/v1"


@pytest.mark.parametrize("base_url", [None, "https://gateway.example/v1"])
def test_orcarouter_api_payload_builds_openai_compatible_provider(monkeypatch, base_url):
    from sagents.v2.model import OpenAIChatCompletionsModelProvider

    monkeypatch.setattr(
        "sagents.v2.model.plugins.openai_compatible.AsyncOpenAI",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    payload = {"protocol": "orcarouter", "model": "orcarouter/auto", "api_key": "test-key"}
    if base_url is not None:
        payload["base_url"] = base_url
    record, _ = apply_upsert(empty_catalog(), ModelBody(**payload).model_dump())
    provider = _build_catalog_provider(record)

    assert isinstance(provider, OpenAIChatCompletionsModelProvider)
    assert provider.config.base_url == (base_url or "https://api.orcarouter.ai/v1")
    assert provider.config.model == "orcarouter/auto"
    assert provider.raw_client.api_key == "test-key"
    assert provider.raw_client.base_url == provider.config.base_url


@pytest.mark.parametrize("base_url", [None, "https://gateway.example/v1"])
@pytest.mark.timeout(30)
def test_orcarouter_model_api_saves_default_or_custom_endpoint(client, base_url):
    token = register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"protocol": "orcarouter", "model": "orcarouter/auto", "api_key": "test-key"}
    if base_url is not None:
        payload["base_url"] = base_url

    response = client.post("/api/models", json=payload, headers=headers)

    assert response.status_code == 200
    model = response.json()["data"]
    assert model["protocol"] == "orcarouter"
    assert model["base_url"] == (base_url or "https://api.orcarouter.ai/v1")
    assert "api_key" not in model
    assert client.get("/api/models", headers=headers).json()["data"] == [model]


@pytest.mark.timeout(30)
def test_model_detail_exposes_key_only_in_authorized_detail_scope(client):
    alice_token = register_and_login(client, "alice")
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    alice_id = client.get("/api/auth/session", headers=alice_headers).json()["data"]["user_id"]
    created = client.post("/api/models", headers=alice_headers, json={
        "model": "demo", "api_key": "detail-test-key", "base_url": "https://example.invalid/v1",
    }).json()["data"]
    path = f"/api/models/{created['id']}"
    detail = client.get(path, headers=alice_headers)
    assert detail.status_code == 200
    assert detail.json()["data"]["api_key"] == "detail-test-key"
    assert detail.headers["cache-control"] == "no-store"
    assert "api_key" not in client.get("/api/models", headers=alice_headers).json()["data"][0]
    bob_token = register_and_login(client, "bob")
    bob_headers = {"Authorization": f"Bearer {bob_token}"}
    assert client.get(path, headers=bob_headers).status_code == 404
    assert client.get(path, headers={**bob_headers, "X-Sage-View-User": alice_id}).status_code == 403
    admin_token = client.post("/api/auth/login", json={"username": "admin", "password": "admin12345"}).json()["data"]["access_token"]
    admin_view = {"Authorization": f"Bearer {admin_token}", "X-Sage-View-User": alice_id}
    assert client.get(path, headers=admin_view).json()["data"]["api_key"] == "detail-test-key"
    assert client.get("/api/models/missing", headers=alice_headers).status_code == 404
