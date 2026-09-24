from __future__ import annotations

import asyncio
import inspect
from contextlib import asynccontextmanager
from contextvars import ContextVar

from app.server_v2.catalog.repository import CatalogStore
from app.server_v2.runtime.model_pool import ModelClientPool
from sagents.v2._concurrency import auxiliary_capacity
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model.contracts import ModelCapabilities, ModelRequest
from sagents.v2.model.protocols import (
    create_registered_model_provider,
    resolve_model_protocol,
)
from sagents.v2.model.provider import ModelProvider
from sagents.v2.package.manifest.models import ModelRoute
from sagents.v2.runtime.credentials.contracts import CredentialMaterial
from sagents.v2.runtime.session.contracts import SessionStore

_current_user_id: ContextVar[str | None] = ContextVar(
    "server_v2_model_user", default=None
)


def bind_model_user(user_id: str | None):
    return _current_user_id.set(user_id)


def reset_model_user(token) -> None:
    _current_user_id.reset(token)


class HostModelProvider:
    """Resolve the current user's catalog model, then the host fallback."""

    def __init__(
        self,
        catalog: CatalogStore,
        *,
        fallback: ModelProvider | None = None,
        session_store: SessionStore | None = None,
        max_clients: int = 64,
    ) -> None:
        self._catalog = catalog
        self._fallback = fallback
        self.session_store = session_store
        self._session_users: dict[str, str] = {}
        self.pool = ModelClientPool(
            create_catalog_provider, close_model_provider, max_clients=max_clients
        )
        self._session_bindings: dict[str, int] = {}

    def bind_session_user(self, session_id: str, user_id: str) -> None:
        current = self._session_users.get(session_id)
        if current is not None and current != user_id:
            raise ValueError("session model binding belongs to another user")
        self._session_users[session_id] = user_id
        self._session_bindings[session_id] = (
            self._session_bindings.get(session_id, 0) + 1
        )

    def unbind_session_user(self, session_id: str) -> None:
        remaining = self._session_bindings.get(session_id, 0) - 1
        if remaining > 0:
            self._session_bindings[session_id] = remaining
        else:
            self._session_bindings.pop(session_id, None)
            self._session_users.pop(session_id, None)

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        async with self._borrow() as provider:
            return await provider.capabilities(model_binding)

    async def probe_capabilities(self, request):
        async with self._borrow() as provider:
            return await provider.probe_capabilities(request)

    async def stream(self, request: ModelRequest):
        async with self._borrow(run_id=request.run_id) as provider:
            stream = provider.stream(request)
            try:
                async for event in stream:
                    yield event
            finally:
                closer = getattr(stream, "aclose", None)
                if closer is not None:
                    await closer()

    async def _user_id(self, run_id: str | None = None) -> str | None:
        if run_id:
            # A long-lived worker may inherit an earlier caller's ContextVar.
            # An explicit Run identity is authoritative; never guess another
            # user's model if its Session cannot be resolved.
            if self.session_store is None:
                raise RuntimeError("session store is not attached")
            try:
                run = await self.session_store.get_run(run_id)
            except SageV2Error:
                return None
            return self._session_users.get(run.session_id)
        return _current_user_id.get()

    async def close(self) -> None:
        await self.pool.close()
        self._session_users.clear()
        self._session_bindings.clear()
        self.session_store = None

    @asynccontextmanager
    async def _borrow(self, run_id: str | None = None):
        user_id = await self._user_id(run_id)
        if user_id:
            record = await self._catalog.default_model(user_id)
            if record is not None:
                lease = await self.pool.acquire(user_id, record)
                try:
                    yield lease.provider
                finally:
                    await lease.close()
                return
        if self._fallback is not None:
            yield self._fallback
            return
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.model_not_configured",
                category=ErrorCategory.VALIDATION,
                message="configure a model before starting a run",
            )
        )


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
    route = ModelRoute(
        provider=resolve_model_protocol(record.protocol).value,
        base_url=record.base_url,
        model=record.model,
    )
    credential = CredentialMaterial(
        credential_id=f"catalog-{record.id}",
        secret=record.api_key,
        source="host",
    )
    return create_registered_model_provider(route, credential)
