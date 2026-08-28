"""Replaceable Model capability port consumed by AgentLoopEngine."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelRequest,
    ModelStreamEvent,
)


class ModelProvider(Protocol):
    """Normalize a concrete model API into v2 streaming model events.

    Provider events are not RuntimeEvents. AgentLoopEngine assigns Turn/Step/Item
    identity and commits the canonical runtime lifecycle.
    """

    async def capabilities(self, model_binding: str) -> ModelCapabilities: ...
    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]: ...
