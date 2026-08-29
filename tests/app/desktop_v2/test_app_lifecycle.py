from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.desktop_v2.backend import app as app_module


class _SessionStore:
    close = AsyncMock()


class _Service:
    session_store = _SessionStore()
    initialize_agent_workspace = AsyncMock()


@pytest.mark.asyncio
async def test_v2_lifespan_initializes_and_closes_only_owned_components():
    service = _Service()
    app = app_module.create_app(service=service)

    async with app.router.lifespan_context(app):
        pass

    service.initialize_agent_workspace.assert_awaited_once()
    service.session_store.close.assert_awaited_once()
