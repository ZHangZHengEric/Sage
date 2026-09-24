from __future__ import annotations

from types import SimpleNamespace

import pytest
from sagents.v2.model.contracts import ModelEventKind, ModelRequest

from app.server_v2.infrastructure.models import HostModelProvider
from tests.app.server_v2.conftest import scripted_hello
from tests.app.server_v2.fakes import MemoryCatalogStore


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
async def test_host_provider_uses_session_bind_when_contextvar_empty(monkeypatch):
    catalog = MemoryCatalogStore()
    await _save_demo_model(catalog)
    monkeypatch.setattr(
        "app.server_v2.infrastructure.models._build_catalog_provider",
        lambda record: scripted_hello(),
    )

    async def get_run(run_id: str):
        assert run_id == "run_sagents"
        return SimpleNamespace(session_id="thread-1")

    provider = HostModelProvider(catalog, session_store=SimpleNamespace(get_run=get_run))
    provider.bind_session_user("thread-1", "user-1")

    events = [
        event
        async for event in provider.stream(
            ModelRequest(
                request_id="request_1",
                run_id="run_sagents",
                model_binding="primary",
                messages=(),
            )
        )
    ]
    assert any(event.kind == ModelEventKind.TEXT_DELTA for event in events)
