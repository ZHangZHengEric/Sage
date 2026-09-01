"""Official diagnostic-sink plugin: discard every model-request projection."""

from __future__ import annotations

from typing import Any


class NoopDiagnosticSink:
    """Safe default used until a host explicitly selects a diagnostic sink."""

    plugin_id = "sage.observability.noop"

    async def begin_model_request(self, **kwargs: Any) -> None:
        return None

    async def complete_model_request(self, **kwargs: Any) -> None:
        return None

    async def record_model_first_token(self, **kwargs: Any) -> None:
        return None

    async def fail_model_request(self, **kwargs: Any) -> None:
        return None
