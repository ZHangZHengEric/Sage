from __future__ import annotations

from contextvars import ContextVar

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model.contracts import ModelCapabilities, ModelRequest, ModelStreamEvent
from sagents.v2.model.provider import ModelProvider

from app.server_v2.repositories.catalog import CatalogStore

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
    ) -> None:
        self._catalog = catalog
        self._fallback = fallback
        self._cache: dict[str, ModelProvider] = {}

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return await (await self._resolve()).capabilities(model_binding)

    async def stream(self, request: ModelRequest):
        provider = await self._resolve()
        async for event in provider.stream(request):
            yield event

    async def _resolve(self) -> ModelProvider:
        user_id = _current_user_id.get()
        if user_id:
            record = await self._catalog.default_model(user_id)
            if record is not None:
                key = record.cache_key()
                cached = self._cache.get(key)
                if cached is None:
                    cached = record.to_provider()
                    self._cache[key] = cached
                return cached
        if self._fallback is not None:
            return self._fallback
        raise SageV2Error(
            RuntimeErrorInfo(
                code="server.model_not_configured",
                category=ErrorCategory.VALIDATION,
                message="configure a model before starting a run",
            )
        )
