"""Optional observability ports that never participate in Session recovery."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from sagents.v2.model.contracts import ModelRequest, ModelResponse


class DiagnosticSink(Protocol):
    """Record model diagnostics independently from authoritative Session data."""

    async def begin_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        provider: Mapping[str, Any],
        wire_request: Mapping[str, Any] | None = None,
    ) -> None: ...

    async def complete_model_request(
        self,
        *,
        session_id: str,
        request: ModelRequest,
        response: ModelResponse,
    ) -> None: ...

    async def fail_model_request(
        self, *, session_id: str, request: ModelRequest, error: Exception
    ) -> None: ...


class NoopDiagnosticSink:
    """Default sink used when a host does not opt into diagnostics."""

    async def begin_model_request(self, **kwargs: Any) -> None:
        return None

    async def complete_model_request(self, **kwargs: Any) -> None:
        return None

    async def fail_model_request(self, **kwargs: Any) -> None:
        return None
