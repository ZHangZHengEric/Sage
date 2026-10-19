from __future__ import annotations

import asyncio
import inspect
from contextvars import ContextVar

from app.v2.server.runtime.model_pool import ModelClientPool
from sagents.v2._concurrency import auxiliary_capacity
from sagents.v2.model.protocols import (
    create_registered_model_provider,
)
from sagents.v2.runtime.credentials.contracts import CredentialMaterial

_current_user_id: ContextVar[str | None] = ContextVar(
    "server_v2_model_user", default=None
)


def bind_model_user(user_id: str | None):
    return _current_user_id.set(user_id)


def reset_model_user(token) -> None:
    _current_user_id.reset(token)


class ServerModelClients:
    """Shared transport pool. Agent routes are resolved by registered Run providers."""
    def __init__(self, *, max_clients=64):
        self.pool = ModelClientPool(create_catalog_provider, close_model_provider, max_clients=max_clients)

    async def close(self):
        await self.pool.close()


async def close_model_provider(provider) -> None:
    closer = getattr(provider, "close", None) or getattr(provider, "aclose", None)
    if closer is not None:
        result = closer()
        if inspect.isawaitable(result):
            await result


async def create_catalog_provider(record):
    """Bound synchronous SDK setup and settle ownership if its caller cancels."""
    async with auxiliary_capacity("model-init"):
        building = asyncio.create_task(asyncio.to_thread(_build_catalog_provider, record))
        try:
            return await asyncio.shield(building)
        except asyncio.CancelledError:
            # SDK construction cannot be interrupted safely in a thread. Do
            # not abandon a newly created connection pool on cancellation.
            while not building.done():
                try:
                    await asyncio.shield(building)
                except asyncio.CancelledError:
                    pass
            await close_model_provider(building.result())
            raise


def _build_catalog_provider(record):
    route = record.route()
    credential = CredentialMaterial(
        credential_id=f"catalog-{record.id}",
        secret=record.api_key,
        source="host",
    )
    return create_registered_model_provider(route, credential)
