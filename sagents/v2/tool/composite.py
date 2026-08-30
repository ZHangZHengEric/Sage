"""SAgents V2 module for tool/composite.py."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from sagents.v2.tool.contracts import (
    ReconcileResult,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.provider import ToolCatalog, ToolExecutor
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.principals import RequestContext


class FilteredToolCatalog:
    """Least-privilege view over a catalog for one resolved Agent/Run."""

    def __init__(self, catalog: ToolCatalog, allowed_names) -> None:
        self._catalog = catalog
        self._allowed_names = frozenset(allowed_names)

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        return tuple(
            definition
            for definition in await self._catalog.list_tools(run_id=run_id)
            if definition.name in self._allowed_names
        )

    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition:
        if name not in self._allowed_names:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.not_enabled",
                    category=ErrorCategory.POLICY_DENIED,
                    message=f"tool {name!r} is outside this run's resolved tool set",
                    safe_to_resume=True,
                )
            )
        return await self._catalog.get_tool(name, run_id=run_id)


class InvocationGrantToolCatalog:
    """Catalog restricted by the durable Run invocation-mode grant.

    Runtime control tools are granted explicitly per invocation.  The same
    check protects both model-visible listing and direct lookup, so a provider
    cannot execute a hidden control tool by returning its name.
    """

    _CONTROL_TOOLS = frozenset({"goal_submit", "goal_complete"})
    _MODE_GRANTS = {
        "plan": frozenset({"goal_submit"}),
        "goal": frozenset({"goal_submit", "goal_complete"}),
    }

    def __init__(
        self,
        catalog: ToolCatalog,
        allowed_names,
        command_reader: Callable[[str], Awaitable[object]],
        *,
        fallback_invocation_mode: str | None = None,
    ) -> None:
        self._catalog = catalog
        self._base_allowed = frozenset(allowed_names) - self._CONTROL_TOOLS
        self._command_reader = command_reader
        self._fallback_invocation_mode = fallback_invocation_mode

    async def _allowed(self, run_id: str) -> frozenset[str]:
        try:
            command = await self._command_reader(run_id)
            mode = str(getattr(command, "invocation_mode", None) or "normal")
        except SageV2Error as exc:
            if self._fallback_invocation_mode is None or not exc.info.code.endswith(
                ".not_found"
            ):
                raise
            mode = self._fallback_invocation_mode
        return self._base_allowed | self._MODE_GRANTS.get(mode, frozenset())

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        allowed = await self._allowed(run_id)
        return tuple(
            definition
            for definition in await self._catalog.list_tools(run_id=run_id)
            if definition.name in allowed
        )

    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition:
        if name not in await self._allowed(run_id):
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.not_enabled",
                    category=ErrorCategory.POLICY_DENIED,
                    message=f"tool {name!r} is outside this run's resolved tool grant",
                    safe_to_resume=True,
                )
            )
        return await self._catalog.get_tool(name, run_id=run_id)


class ExcludingToolCatalog:
    """Hide names supplied by a higher-priority compatibility adapter."""

    def __init__(self, catalog: ToolCatalog, excluded_names) -> None:
        self._catalog = catalog
        self._excluded_names = frozenset(excluded_names)

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        return tuple(
            definition
            for definition in await self._catalog.list_tools(run_id=run_id)
            if definition.name not in self._excluded_names
        )

    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition:
        if name in self._excluded_names:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"tool {name!r} is supplied by another catalog",
                )
            )
        return await self._catalog.get_tool(name, run_id=run_id)


class CompositeToolCatalog:
    def __init__(self, catalogs: tuple[ToolCatalog, ...]) -> None:
        self._catalogs = catalogs

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        merged: dict[str, ToolDefinition] = {}
        for catalog in self._catalogs:
            for definition in await catalog.list_tools(run_id=run_id):
                if definition.name in merged:
                    raise self._duplicate(definition.name)
                merged[definition.name] = definition
        return tuple(merged[name] for name in sorted(merged))

    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition:
        matches = [
            definition
            for definition in await self.list_tools(run_id=run_id)
            if definition.name == name
        ]
        if not matches:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"tool {name!r} is not registered",
                )
            )
        return matches[0]

    @staticmethod
    def _duplicate(name):
        return SageV2Error(
            RuntimeErrorInfo(
                code="tool.duplicate_name",
                category=ErrorCategory.CONFLICT,
                message=f"multiple catalogs provide tool {name!r}",
            )
        )


class RoutedToolExecutor:
    def __init__(self, routes: Mapping[str, ToolExecutor]) -> None:
        self._routes = dict(routes)

    async def execute(
        self, call: ToolCall, context: RequestContext
    ) -> ToolExecutionResult:
        executor = self._routes.get(call.tool_name)
        if executor is None:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="tool.not_found",
                    category=ErrorCategory.VALIDATION,
                    message=f"tool {call.tool_name!r} has no execution route",
                )
            )
        return await executor.execute(call, context)

    async def reconcile(
        self, operation_id: str, context: RequestContext
    ) -> ReconcileResult:
        # Reconciliation intentionally queries every route because operation IDs
        # are globally stable while tool definitions may change after restore.
        from sagents.v2.tool.contracts import ReconcileState

        pending = None
        for executor in dict.fromkeys(self._routes.values()):
            result = await executor.reconcile(operation_id, context)
            if result.state in {ReconcileState.SUCCEEDED, ReconcileState.FAILED}:
                return result
            if result.state == ReconcileState.PENDING:
                pending = result
        return pending or ReconcileResult(
            operation_id=operation_id, state=ReconcileState.UNKNOWN
        )


class CompositeToolExecutor:
    """Late-bound executor chain for run-scoped catalogs assembled by modes."""

    def __init__(self, executors: tuple[ToolExecutor, ...]) -> None:
        self._executors = executors

    async def execute(self, call: ToolCall, context: RequestContext):
        last_missing = None
        for executor in self._executors:
            try:
                return await executor.execute(call, context)
            except SageV2Error as exc:
                if exc.info.code != "tool.not_found":
                    raise
                last_missing = exc
        if last_missing is not None:
            raise last_missing
        raise SageV2Error(
            RuntimeErrorInfo(
                code="tool.not_found",
                category=ErrorCategory.VALIDATION,
                message=f"tool {call.tool_name!r} has no execution provider",
            )
        )

    async def reconcile(self, operation_id: str, context: RequestContext):
        from sagents.v2.tool.contracts import ReconcileState

        pending = None
        for executor in self._executors:
            result = await executor.reconcile(operation_id, context)
            if result.state in {ReconcileState.SUCCEEDED, ReconcileState.FAILED}:
                return result
            if result.state == ReconcileState.PENDING:
                pending = result
        return pending or ReconcileResult(
            operation_id=operation_id, state=ReconcileState.UNKNOWN
        )
