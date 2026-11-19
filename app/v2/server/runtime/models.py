from __future__ import annotations

import asyncio
import inspect
from functools import partial

from app.v2.server.config.video_storage import authorize_video_storage

from app.v2.server.runtime.model_pool import ModelClientPool
from sagents.v2.concurrency import auxiliary_capacity
from sagents.v2.model.protocols import (
    create_registered_model_provider,
)
from sagents.v2.runtime.credentials.contracts import CredentialMaterial

class ServerModelClients:
    """Shared transport pool. Agent routes are resolved by registered Run providers."""
    def __init__(self, *, max_clients=64, video_storage_profiles=None):
        self._video_storage_profiles = dict(video_storage_profiles or {})
        self.pool = ModelClientPool(create_catalog_provider, close_model_provider, max_clients=max_clients)

    async def acquire(self, owner_id, record):
        storage = authorize_video_storage(record.request.extra, owner_id, self._video_storage_profiles)
        factory = partial(create_catalog_provider, video_storage=storage) if storage is not None else None
        return await self.pool.acquire(owner_id, record, factory=factory)

    async def close(self):
        await self.pool.close()


async def close_model_provider(provider) -> None:
    closer = getattr(provider, "close", None) or getattr(provider, "aclose", None)
    if closer is not None:
        result = closer()
        if inspect.isawaitable(result):
            await result


async def create_catalog_provider(record, *, video_storage=None):
    """Bound synchronous SDK setup and settle ownership if its caller cancels."""
    async with auxiliary_capacity("model-init"):
        build = (
            _build_catalog_provider
            if video_storage is None else partial(_build_catalog_provider, video_storage=video_storage)
        )
        building = asyncio.create_task(asyncio.to_thread(build, record))
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


def _build_catalog_provider(record, *, video_storage=None):
    route = record.route()
    if video_storage is not None:
        extra = {key: value for key, value in route.request.extra.items()
                 if key != "video_storage_profile"}
        route = route.model_copy(update={"request": route.request.model_copy(update={"extra": extra})})
    credential = CredentialMaterial(
        credential_id=f"catalog-{record.id}",
        secret=record.api_key,
        source="host",
    )
    return create_registered_model_provider(route, credential, video_storage=video_storage)
