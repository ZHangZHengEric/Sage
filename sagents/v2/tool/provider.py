"""Tool discovery and execution ports used across the side-effect barrier."""

from __future__ import annotations

from typing import Awaitable, Protocol

from sagents.v2.tool.contracts import (
    ReconcileResult,
    ToolCancellationResult,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.contracts.principals import RequestContext


class ToolCatalog(Protocol):
    """Expose model-visible schemas plus runtime-only side-effect metadata."""

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]: ...
    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition: ...


class ToolExecutor(Protocol):
    """Execute or reconcile a ToolCall after Kernel policy authorization."""

    async def execute(
        self, call: ToolCall, context: RequestContext
    ) -> ToolExecutionResult: ...

    async def reconcile(
        self, operation_id: str, context: RequestContext
    ) -> ReconcileResult: ...


class CancellableToolExecutor(Protocol):
    """Optional port implemented only by executors with real cancellation."""

    async def cancel(
        self, operation_id: str, context: RequestContext
    ) -> ToolCancellationResult: ...


class RunScopedToolState(Protocol):
    """Optional bounded-state hook for providers shared by multiple Runs."""

    def release_run(self, run_id: str) -> None | Awaitable[None]: ...
