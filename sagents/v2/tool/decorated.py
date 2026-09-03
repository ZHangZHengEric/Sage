"""Catalog/executor loader for Tool methods declared with :func:`tool`."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate

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
from sagents.v2.tool._idempotency import call_fingerprint


DecoratedHandler = Callable[..., Any]


class _DecoratedToolCatalog:
    def __init__(self, tools: tuple[ToolDefinition, ...]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("tool names must be unique")

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        return tuple(self._tools[name] for name in sorted(self._tools))

    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"tool {name!r} is not registered",
                )
            ) from exc


class _DecoratedToolExecutor:
    """Private executor owned by the decorated-tool adapter."""

    def __init__(
        self, definitions: dict[str, ToolDefinition], handlers: dict[str, Any]
    ):
        self._definitions = dict(definitions)
        self._handlers = dict(handlers)
        self._lock = asyncio.Lock()
        self._results: dict[str, ToolExecutionResult] = {}
        self._inflight: dict[str, asyncio.Future[ToolExecutionResult]] = {}
        self._operation_keys: dict[str, str] = {}
        self._call_fingerprints: dict[str, str] = {}

    async def execute(
        self, call: ToolCall, context: RequestContext
    ) -> ToolExecutionResult:
        definition = self._definitions.get(call.tool_name)
        handler = self._handlers.get(call.tool_name)
        if definition is None or handler is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"tool {call.tool_name!r} is not executable",
                    metadata={"side_effect_state": "not_applied"},
                )
            )
        try:
            validate(instance=call.arguments, schema=definition.input_schema)
        except JsonSchemaValidationError as exc:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.arguments_invalid",
                    category=ErrorCategory.VALIDATION,
                    message=exc.message,
                    safe_to_resume=True,
                    metadata={"side_effect_state": "not_applied"},
                )
            ) from exc

        fingerprint = call_fingerprint(call)
        async with self._lock:
            bound = self._call_fingerprints.get(call.idempotency_key)
            if bound is not None and bound != fingerprint:
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="tool.idempotency_conflict",
                        category=ErrorCategory.CONFLICT,
                        message=(
                            "idempotency key was already bound to a different Tool call"
                        ),
                        safe_to_resume=True,
                        metadata={"side_effect_state": "not_applied"},
                    )
                )
            existing = self._results.get(call.idempotency_key)
            if existing is not None:
                return existing
            future = self._inflight.get(call.idempotency_key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._inflight[call.idempotency_key] = future
                self._operation_keys[call.operation_id] = call.idempotency_key
                self._call_fingerprints[call.idempotency_key] = fingerprint
                owner = True
            else:
                owner = False
        if not owner:
            return await asyncio.shield(future)
        try:
            result = await handler(call, context)
            if (
                result.tool_call_id != call.tool_call_id
                or result.operation_id != call.operation_id
            ):
                raise SageV2Error(
                    RuntimeErrorInfo(
                        code="tool.result_identity_mismatch",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message="tool result identity does not match call",
                    )
                )
            async with self._lock:
                self._results[call.idempotency_key] = result
                if not future.done():
                    future.set_result(result)
            return result
        except BaseException as exc:
            async with self._lock:
                if not future.done():
                    future.set_exception(exc)
                    future.exception()
            raise
        finally:
            async with self._lock:
                self._inflight.pop(call.idempotency_key, None)
                self._operation_keys.pop(call.operation_id, None)

    async def reconcile(
        self, operation_id: str, context: RequestContext
    ) -> ReconcileResult:
        del context
        async with self._lock:
            result = next(
                (
                    value
                    for value in self._results.values()
                    if value.operation_id == operation_id
                ),
                None,
            )
            key = self._operation_keys.get(operation_id)
            pending = key in self._inflight if key is not None else False
        if result is not None:
            return ReconcileResult(
                operation_id=operation_id,
                state=ReconcileState.SUCCEEDED,
                result=result,
            )
        return ReconcileResult(
            operation_id=operation_id,
            state=ReconcileState.PENDING if pending else ReconcileState.UNKNOWN,
        )


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
        self.catalog = _DecoratedToolCatalog(self.definitions)
        self.executor = _DecoratedToolExecutor(definitions, handlers)
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
            raise TypeError(f"reconcile_{call.tool_name} must return ReconcileResult")
        return result
