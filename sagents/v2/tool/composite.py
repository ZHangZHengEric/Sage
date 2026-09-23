"""SAgents V2 module for tool/composite.py."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping

from sagents.v2.tool.contracts import (
    ReconcileResult,
    ReconcileState,
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

    ``granted_catalogs`` grants whole catalogs rather than names.  Some Tools
    are not the Agent's to choose from: an external catalog declares its own
    Tools at runtime, so no static list on the Agent could name them, and
    composing such a catalog into a Run without granting it produces Tools that
    are visible and then refused at call time.  The grant is resolved per Run
    rather than captured here, because the catalog behind it changes while a
    composed Agent is still cached.
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
        granted_catalogs: tuple[ToolCatalog, ...] = (),
    ) -> None:
        self._catalog = catalog
        self._base_allowed = frozenset(allowed_names) - self._CONTROL_TOOLS
        self._command_reader = command_reader
        self._fallback_invocation_mode = fallback_invocation_mode
        self._granted_catalogs = tuple(granted_catalogs)

    async def _granted(self, run_id: str) -> frozenset[str]:
        """Name what the wholly granted catalogs are offering this Run.

        Discovery degrades per server rather than per Run — an external
        provider that is down costs its own Tools and nothing else. Letting an
        exception out here would undo that by turning a provider that is merely
        unreachable into a Run that cannot list its Tools at all.
        """

        names: set[str] = set()
        for catalog in self._granted_catalogs:
            try:
                names.update(
                    definition.name
                    for definition in await catalog.list_tools(run_id=run_id)
                )
            except Exception:
                continue
        return frozenset(names)

    async def _allowed(self, run_id: str) -> frozenset[str]:
        try:
            command = await self._command_reader(run_id)
            mode = str(getattr(command, "invocation_mode", None) or "normal")
            configured = getattr(
                getattr(command, "config", None), "enabled_tools", None
            )
        except SageV2Error as exc:
            if self._fallback_invocation_mode is None or not exc.info.code.endswith(
                ".not_found"
            ):
                raise
            mode = self._fallback_invocation_mode
            configured = None
        base = self._base_allowed
        if configured is not None:
            base &= frozenset(configured)
        if self._granted_catalogs:
            # Outside the ``configured`` intersection on purpose: that list
            # narrows the Agent's own declared Tools, and cannot name Tools
            # that only exist once an external provider has been asked.
            base |= (await self._granted(run_id)) - self._CONTROL_TOOLS
        return base | self._MODE_GRANTS.get(mode, frozenset())

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
        self._operation_routes: dict[str, ToolExecutor] = {}
        self._operation_run_ids: dict[str, str] = {}

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
        self._operation_routes[call.operation_id] = executor
        self._operation_run_ids[call.operation_id] = call.owner_run_id
        return await executor.execute(call, context)

    async def release_run(self, run_id: str) -> None:
        errors = await _release_run_from_providers(
            tuple(dict.fromkeys(self._routes.values())), run_id
        )
        for operation_id, owner_run_id in tuple(self._operation_run_ids.items()):
            if owner_run_id == run_id:
                self._operation_run_ids.pop(operation_id, None)
                self._operation_routes.pop(operation_id, None)
        if errors:
            raise errors[0]

    async def cancel(self, operation_id: str, context: RequestContext):
        from sagents.v2.tool.contracts import (
            ToolCancellationResult,
            ToolCancellationState,
        )

        executor = self._operation_routes.get(operation_id)
        cancel = getattr(executor, "cancel", None)
        if not callable(cancel):
            return ToolCancellationResult(
                operation_id=operation_id,
                state=ToolCancellationState.NOT_SUPPORTED,
            )
        return await cancel(operation_id, context)

    async def reconcile(
        self, operation_id: str, context: RequestContext
    ) -> ReconcileResult:
        # Reconciliation intentionally queries every route because operation IDs
        # are globally stable while tool definitions may change after restore.
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

    async def reconcile_call(
        self, call: ToolCall, context: RequestContext
    ) -> ReconcileResult:
        executor = self._routes.get(call.tool_name)
        if executor is None:
            return ReconcileResult(
                operation_id=call.operation_id, state=ReconcileState.UNKNOWN
            )
        reconcile_call = getattr(executor, "reconcile_call", None)
        if callable(reconcile_call):
            return await reconcile_call(call, context)
        return await executor.reconcile(call.operation_id, context)


class CompositeToolExecutor:
    """Late-bound executor chain for run-scoped catalogs assembled by modes."""

    def __init__(self, executors: tuple[ToolExecutor, ...]) -> None:
        self._executors = executors
        self._operation_routes: dict[str, ToolExecutor] = {}
        self._operation_run_ids: dict[str, str] = {}

    async def execute(self, call: ToolCall, context: RequestContext):
        last_missing = None
        for executor in self._executors:
            self._operation_routes[call.operation_id] = executor
            self._operation_run_ids[call.operation_id] = call.owner_run_id
            try:
                return await executor.execute(call, context)
            except SageV2Error as exc:
                if exc.info.code != "tool.not_found":
                    raise
                if self._operation_routes.get(call.operation_id) is executor:
                    self._operation_routes.pop(call.operation_id, None)
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

    async def release_run(self, run_id: str) -> None:
        errors = await _release_run_from_providers(
            tuple(dict.fromkeys(self._executors)), run_id
        )
        for operation_id, owner_run_id in tuple(self._operation_run_ids.items()):
            if owner_run_id == run_id:
                self._operation_run_ids.pop(operation_id, None)
                self._operation_routes.pop(operation_id, None)
        if errors:
            raise errors[0]

    async def cancel(self, operation_id: str, context: RequestContext):
        from sagents.v2.tool.contracts import (
            ToolCancellationResult,
            ToolCancellationState,
        )

        executor = self._operation_routes.get(operation_id)
        cancel = getattr(executor, "cancel", None)
        if not callable(cancel):
            return ToolCancellationResult(
                operation_id=operation_id,
                state=ToolCancellationState.NOT_SUPPORTED,
            )
        return await cancel(operation_id, context)

    async def reconcile(self, operation_id: str, context: RequestContext):
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

    async def reconcile_call(self, call: ToolCall, context: RequestContext):
        from sagents.v2.tool.contracts import ReconcileState

        pending = None
        for executor in self._executors:
            call_aware = getattr(executor, "reconcile_call", None)
            result = (
                await call_aware(call, context)
                if callable(call_aware)
                else await executor.reconcile(call.operation_id, context)
            )
            if result.state in {ReconcileState.SUCCEEDED, ReconcileState.FAILED}:
                return result
            if result.state == ReconcileState.PENDING:
                pending = result
        return pending or ReconcileResult(
            operation_id=call.operation_id, state=ReconcileState.UNKNOWN
        )


async def _release_run_from_providers(
    providers: tuple[ToolExecutor, ...], run_id: str
) -> tuple[Exception, ...]:
    """Attempt every ordinary cleanup while preserving cancellation semantics."""

    errors: list[Exception] = []
    for provider in providers:
        release = getattr(provider, "release_run", None)
        if not callable(release):
            continue
        try:
            result = release(run_id)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            errors.append(exc)
    return tuple(errors)
