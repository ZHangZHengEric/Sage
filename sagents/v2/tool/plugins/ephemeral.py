"""In-memory Tool Catalog/Executor plugin for tests and empty catalogs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate

from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDescriptor,
    ExtensionScope,
)
from sagents.v2.tool.contracts import (
    ReconcileResult,
    ReconcileState,
    ToolCall,
    ToolCancellationResult,
    ToolCancellationState,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool._idempotency import call_fingerprint
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.principals import RequestContext


ToolHandler = Callable[[ToolCall, RequestContext], Awaitable[ToolExecutionResult]]


class EphemeralToolPlugin:
    """Paired in-memory catalog/executor without restart durability."""

    plugin_id = "sage.tool.ephemeral"
    name = "Ephemeral Tool provider"
    description = "In-memory Tool catalog and executor without restart durability."
    descriptor = ExtensionDescriptor(
        plugin_id=plugin_id,
        version="2.0.0",
        name=name,
        description=description,
        provides=(
            CapabilityOffer(
                capability="tool.catalog", api_version="2", name="ephemeral"
            ),
            CapabilityOffer(
                capability="tool.executor", api_version="2", name="ephemeral"
            ),
        ),
        supported_scopes=frozenset(
            {ExtensionScope.PROCESS, ExtensionScope.AGENT, ExtensionScope.RUN}
        ),
        config_schema={
            "type": "object",
            "properties": {"tools": {}, "handlers": {}},
            "additionalProperties": False,
        },
        capabilities={"durable": False, "testing": True},
        built_in=True,
    )

    def __init__(
        self,
        tools: tuple[ToolDefinition, ...] = (),
        handlers: Mapping[str, ToolHandler] | None = None,
    ) -> None:
        self.catalog = InMemoryToolCatalog(tuple(tools))
        self.executor = InMemoryToolExecutor(
            {tool.name: tool for tool in tools},
            dict(handlers or {}),
        )
        self.definitions = tuple(tools)


class InMemoryToolCatalog:
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


class InMemoryToolExecutor:
    """Validate schemas and deduplicate concurrent calls by idempotency key."""

    def __init__(
        self,
        definitions: Mapping[str, ToolDefinition],
        handlers: Mapping[str, ToolHandler],
    ) -> None:
        self._definitions = dict(definitions)
        self._handlers = dict(handlers)
        self._lock = asyncio.Lock()
        self._results: dict[str, ToolExecutionResult] = {}
        self._inflight: dict[str, asyncio.Future[ToolExecutionResult]] = {}
        self._execution_tasks: dict[str, asyncio.Task] = {}
        self._call_fingerprints: dict[str, str] = {}
        self.calls: list[ToolCall] = []

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
                self._call_fingerprints[call.idempotency_key] = fingerprint
                owner = True
                self.calls.append(call)
                current_task = asyncio.current_task()
                if current_task is not None:
                    self._execution_tasks[call.operation_id] = current_task
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
                self._execution_tasks.pop(call.operation_id, None)

    async def cancel(
        self, operation_id: str, context: RequestContext
    ) -> ToolCancellationResult:
        del context
        async with self._lock:
            task = self._execution_tasks.get(operation_id)
            if task is None or task.done():
                return ToolCancellationResult(
                    operation_id=operation_id,
                    state=ToolCancellationState.TOO_LATE,
                )
            task.cancel()
        return ToolCancellationResult(
            operation_id=operation_id,
            state=ToolCancellationState.CANCELLED,
        )

    async def reconcile(
        self, operation_id: str, context: RequestContext
    ) -> ReconcileResult:
        async with self._lock:
            result = next(
                (
                    value
                    for value in self._results.values()
                    if value.operation_id == operation_id
                ),
                None,
            )
            inflight = any(
                call.operation_id == operation_id
                for call in self.calls
                if call.idempotency_key in self._inflight
            )
        if result is not None:
            return ReconcileResult(
                operation_id=operation_id, state=ReconcileState.SUCCEEDED, result=result
            )
        return ReconcileResult(
            operation_id=operation_id,
            state=ReconcileState.PENDING if inflight else ReconcileState.UNKNOWN,
        )
