"""SAgents V2 module for testing/plugins/scripted_model.py."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from sagents.v2.model.contracts import (
    ModelCapabilities,
    ModelRequest,
    ModelStreamEvent,
)
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)


@dataclass(frozen=True)
class ScriptedModelStep:
    events: tuple[ModelStreamEvent, ...]
    assertion: Callable[[ModelRequest], None] | None = None
    delay_yields: int = 0
    error: RuntimeErrorInfo | None = None


class ScriptedModelProvider:
    """Deterministic, concurrency-safe model provider for contract tests."""

    def __init__(
        self,
        steps: tuple[ScriptedModelStep, ...],
        *,
        capabilities: ModelCapabilities | None = None,
    ) -> None:
        self._steps = steps
        self._capabilities = capabilities or ModelCapabilities(
            supports_streaming=True,
            supports_tools=True,
            supports_parallel_tool_calls=True,
            supports_reasoning=True,
            supports_multimodal_input=True,
            supports_structured_output=True,
        )
        self._lock = asyncio.Lock()
        self._index = 0
        self.requests: list[ModelRequest] = []

    async def capabilities(self, model_binding: str) -> ModelCapabilities:
        return self._capabilities

    async def _claim_step(self, request: ModelRequest) -> ScriptedModelStep:
        async with self._lock:
            if self._index >= len(self._steps):
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="model.script_exhausted",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message="scripted model has no remaining response",
                    )
                )
            step = self._steps[self._index]
            self._index += 1
            self.requests.append(request)
            return step

    async def _stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        step = await self._claim_step(request)
        if step.assertion is not None:
            step.assertion(request)
        for _ in range(step.delay_yields):
            await asyncio.sleep(0)
        if step.error is not None:
            raise SageV2Error(step.error)
        for event in step.events:
            await asyncio.sleep(0)
            yield event

    def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        return self._stream(request)
