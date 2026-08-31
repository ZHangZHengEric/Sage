"""SAgents V2 module for model/middleware/recording.py."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any

from sagents.v2.contracts.common import utc_now
from sagents.v2.runtime.observability.contracts import DiagnosticSink
from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelEventKind,
    ModelRequest,
    ModelStreamEvent,
)
from sagents.v2.model.provider import ModelProvider


class RecordingModelProvider:
    """ModelProvider decorator that records every attempted model request."""

    def __init__(
        self,
        provider: ModelProvider,
        *,
        sink: DiagnosticSink,
        session_id_resolver: Callable[[str], Awaitable[str]],
        provider_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        self.provider = provider
        self.sink = sink
        self.session_id_resolver = session_id_resolver
        self.provider_metadata = dict(provider_metadata or {})

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return await self.provider.capabilities(model_binding)

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        return self._stream(request)

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        session_id = await self.session_id_resolver(request.run_id)
        diagnostic_request = getattr(self.provider, "diagnostic_request", None)
        try:
            wire_request = (
                diagnostic_request(request) if diagnostic_request is not None else None
            )
        except Exception as exc:
            await self.sink.begin_model_request(
                session_id=session_id,
                request=request,
                provider=self.provider_metadata,
            )
            await self.sink.fail_model_request(
                session_id=session_id,
                request=request,
                error=exc,
            )
            raise
        await self.sink.begin_model_request(
            session_id=session_id,
            request=request,
            provider=self.provider_metadata,
            wire_request=wire_request,
        )
        finalized = False
        first_token_at = None
        first_token_persisted = False

        async def persist_first_token() -> None:
            nonlocal first_token_persisted
            if first_token_at is None or first_token_persisted:
                return
            recorder = getattr(self.sink, "record_model_first_token", None)
            if recorder is not None:
                await recorder(
                    session_id=session_id,
                    request=request,
                    observed_at=first_token_at,
                )
            first_token_persisted = True

        try:
            async for event in self.provider.stream(request):
                if (
                    first_token_at is None
                    and event.kind
                    in {ModelEventKind.TEXT_DELTA, ModelEventKind.REASONING_DELTA}
                    and event.delta
                ):
                    # Capture the observation before yielding, but defer the
                    # diagnostic write so it never delays the first token.
                    first_token_at = utc_now()
                if event.kind == ModelEventKind.COMPLETED:
                    assert event.response is not None
                    await persist_first_token()
                    await self.sink.complete_model_request(
                        session_id=session_id,
                        request=request,
                        response=event.response,
                    )
                    finalized = True
                yield event
        except Exception as exc:
            await persist_first_token()
            await self.sink.fail_model_request(
                session_id=session_id,
                request=request,
                error=exc,
            )
            finalized = True
            raise
        finally:
            if not finalized:
                await persist_first_token()
                await self.sink.fail_model_request(
                    session_id=session_id,
                    request=request,
                    error=RuntimeError("model stream closed before completion"),
                )
