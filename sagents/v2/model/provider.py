"""Replaceable Model capability port consumed by AgentLoopEngine."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelRequest,
    ModelStreamEvent,
)
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.model.capability_contracts import (
    ModelCapabilityProbeRequest,
    ModelCapabilityProfile,
)

# Auxiliary classification/ranking calls should never inherit the main model's
# long request timeout. The selected plugin still owns failure semantics.
DEFAULT_AUXILIARY_MODEL_TIMEOUT_SECONDS = 60.0


def auxiliary_model_timeout_error(
    *,
    code: str,
    operation: str,
    timeout_seconds: float,
    plugin_id: str,
) -> SageV2Error:
    """Create the typed error emitted by strict auxiliary model plugins."""

    return SageV2Error(
        RuntimeErrorInfo(
            code=code,
            category=ErrorCategory.PROVIDER_TRANSIENT,
            message=f"{operation} timed out after {timeout_seconds:g} seconds",
            retryable=True,
            safe_to_resume=True,
            metadata={
                "plugin_id": plugin_id,
                "timeout_seconds": timeout_seconds,
            },
        )
    )


class ModelProvider(Protocol):
    """Normalize a concrete model API into v2 streaming model events.

    Provider events are not RuntimeEvents. AgentLoopEngine assigns Turn/Step/Item
    identity and commits the canonical runtime lifecycle.
    """

    async def capabilities(self, model_binding: str) -> ModelCapabilities: ...
    async def probe_capabilities(
        self, request: ModelCapabilityProbeRequest
    ) -> ModelCapabilityProfile: ...
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...
