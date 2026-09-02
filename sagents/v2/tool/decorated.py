"""Catalog/executor loader for Tool methods declared with :func:`tool`."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.contracts.items import JsonBlock, TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.tool.contracts import (
    ReconcileResult,
    ReconcileState,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.decorators import decorated_tool_definition
from sagents.v2.tool.plugins.ephemeral import InMemoryToolCatalog, InMemoryToolExecutor


DecoratedHandler = Callable[..., Any]


@dataclass(frozen=True)
class ToolInvocation:
    """Runtime-owned values injected into a decorated Tool implementation."""

    call: ToolCall
    request_context: RequestContext


class DecoratedToolProvider:
    """Load decorated methods from one or more Tool implementation objects.

    Built-in tools must enter a catalog through this loader. This keeps the
    schema declaration next to the implementation and prevents a second
    hand-written catalog or parallel global manager.
    """

    def __init__(self, *owners: object) -> None:
        definitions: dict[str, ToolDefinition] = {}
        handlers: dict[str, Any] = {}
        reconcilers: dict[str, Any] = {}
        for owner in owners:
            for _, method in inspect.getmembers(owner, callable):
                definition = decorated_tool_definition(method)
                if definition is None:
                    continue
                if definition.name in definitions:
                    raise SageV2Error(
                        RuntimeErrorInfo(
                            code="tool.duplicate_name",
                            category=ErrorCategory.CONFLICT,
                            message=f"tool {definition.name!r} is declared more than once",
                        )
                    )
                definitions[definition.name] = definition
                handlers[definition.name] = self._handler(method)
                reconcile = getattr(owner, f"reconcile_{definition.name}", None)
                if callable(reconcile):
                    reconcilers[definition.name] = reconcile
        self.definitions = tuple(definitions[name] for name in sorted(definitions))
        self.catalog = InMemoryToolCatalog(self.definitions)
        self.executor = InMemoryToolExecutor(definitions, handlers)
        self._reconcilers = reconcilers

    @staticmethod
    def _handler(method: DecoratedHandler):
        parameters = inspect.signature(method).parameters

        async def execute(
            call: ToolCall, context: RequestContext
        ) -> ToolExecutionResult:
            arguments = dict(call.arguments)
            if "invocation" in parameters:
                arguments["invocation"] = ToolInvocation(call, context)
            if "request_context" in parameters:
                arguments["request_context"] = context
            value = method(**arguments)
            result = await value if inspect.isawaitable(value) else value
            if isinstance(result, ToolExecutionResult):
                return result
            content = (
                (TextBlock(text=result),)
                if isinstance(result, str)
                else (JsonBlock(value=result),)
            )
            return ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=content,
            )

        return execute

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        return await self.catalog.list_tools(run_id=run_id)

    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition:
        return await self.catalog.get_tool(name, run_id=run_id)

    async def execute(
        self, call: ToolCall, context: RequestContext
    ) -> ToolExecutionResult:
        return await self.executor.execute(call, context)

    async def reconcile(
        self, operation_id: str, context: RequestContext
    ) -> ReconcileResult:
        return await self.executor.reconcile(operation_id, context)

    async def reconcile_call(
        self, call: ToolCall, context: RequestContext
    ) -> ReconcileResult:
        """Use the cached result first, then ask a Tool-specific verifier.

        The call-aware hook matters after a worker restart: the in-memory result
        cache is gone, but structured local Tools can often verify their effect
        directly from the workspace instead of asking the user to guess.
        """

        cached = await self.executor.reconcile(call.operation_id, context)
        if cached.state != ReconcileState.UNKNOWN:
            return cached
        reconcile = self._reconcilers.get(call.tool_name)
        if reconcile is None:
            return cached
        value = reconcile(call, context)
        result = await value if inspect.isawaitable(value) else value
        if not isinstance(result, ReconcileResult):
            raise TypeError(
                f"reconcile_{call.tool_name} must return ReconcileResult"
            )
        return result
