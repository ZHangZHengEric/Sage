"""Server-owned per-Run filtering for MCP and A2A providers."""

import inspect

from sagents.v2.tool import FilteredToolCatalog
from sagents.v2.tool.contracts import (
    ReconcileResult, ReconcileState, ToolCancellationResult, ToolCancellationState,
)
from sagents.v2.contracts.errors import SageV2Error


class ScopedExternalTools:
    """Expose only tools authorized in the durable StartRun configuration."""

    def __init__(self, provider, agents, *, command_reader):
        self.provider = provider
        self._grants = {name: frozenset(definition.tools) for name, definition in agents.items()}
        self._command_reader = command_reader
        self._operations: dict[str, str] = {}

    async def _catalog(self, run_id):
        # An unbound provider must fail closed, including during validation.
        names = ()
        if self._command_reader is not None:
            command = await self._command_reader(run_id)
            names = self._grants.get(command.agent_id, frozenset())
            if command.config.enabled_tools is not None:
                names = names.intersection(command.config.enabled_tools)
        return FilteredToolCatalog(self.provider, names)

    async def list_tools(self, *, run_id):
        return await (await self._catalog(run_id)).list_tools(run_id=run_id)

    async def get_tool(self, name, *, run_id):
        return await (await self._catalog(run_id)).get_tool(name, run_id=run_id)

    async def execute(self, call, context):
        # Only reject grants for tools owned by this provider. A missing tool
        # must let the executor chain reach runtime tools such as load_skill.
        await self.provider.get_tool(call.tool_name, run_id=call.owner_run_id)
        await self.get_tool(call.tool_name, run_id=call.owner_run_id)
        self._operations[call.operation_id] = call.owner_run_id
        return await self.provider.execute(call, context)

    async def reconcile(self, operation_id, context):
        if operation_id not in self._operations:
            return ReconcileResult(operation_id=operation_id, state=ReconcileState.UNKNOWN)
        return await self.provider.reconcile(operation_id, context)

    async def reconcile_call(self, call, context):
        try:
            await self.get_tool(call.tool_name, run_id=call.owner_run_id)
        except SageV2Error as exc:
            if exc.info.code not in {"tool.not_enabled", "tool.not_found"}:
                raise
            return ReconcileResult(operation_id=call.operation_id, state=ReconcileState.UNKNOWN)
        self._operations[call.operation_id] = call.owner_run_id
        reconcile_call = getattr(self.provider, "reconcile_call", None)
        if callable(reconcile_call):
            return await reconcile_call(call, context)
        return await self.provider.reconcile(call.operation_id, context)

    async def cancel(self, operation_id, context):
        cancel = getattr(self.provider, "cancel", None)
        if operation_id not in self._operations or not callable(cancel):
            return ToolCancellationResult(operation_id=operation_id, state=ToolCancellationState.NOT_SUPPORTED)
        return await cancel(operation_id, context)

    async def release_run(self, run_id):
        try:
            release = getattr(self.provider, "release_run", None)
            if callable(release):
                result = release(run_id)
                if inspect.isawaitable(result):
                    await result
        finally:
            for operation_id, owner in tuple(self._operations.items()):
                if owner == run_id:
                    self._operations.pop(operation_id)
