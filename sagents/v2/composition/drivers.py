"""Run drivers that bind execution resources before composing an Agent loop."""

from __future__ import annotations

from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from sagents.v2.runtime.execution import (
    ExecutionBindingProvider,
    ExecutionBindingRequest,
    RunExecutionBinding,
)
from sagents.v2.tool.official import OfficialToolRuntime


class _ExecutionBoundDriver:
    """Lazily compose a loop after the Runtime has allocated its Run ID."""

    def __init__(
        self,
        *,
        runtime,
        provider: ExecutionBindingProvider,
        run_id: str,
        agent_id: str,
        loop_builder,
    ) -> None:
        self.runtime = runtime
        self.provider = provider
        self.run_id = run_id
        self.agent_id = agent_id
        self.loop_builder = loop_builder
        self.binding: RunExecutionBinding | None = None
        self.scope_handle = None
        self.loop = None
        self._lock = None

    async def _ensure_loop(self, context):
        if self.loop is not None:
            return self.loop
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        async with self._lock:
            if self.loop is not None:
                return self.loop
            command = await self.runtime.session_store.get_start_command(self.run_id)
            policy = str(
                command.config.metadata.get("workspace_policy") or "shared_parent"
            )
            request = ExecutionBindingRequest(
                run_id=self.run_id,
                parent_run_id=command.parent_run_id,
                agent_id=self.agent_id,
                workspace_policy=policy,
                context=context,
            )
            binding = await self.provider.acquire(request)
            try:
                binding.validate_for(request)
                loop = self.loop_builder(binding)
                if hasattr(loop, "__await__"):
                    loop = await loop
                if isinstance(loop, tuple):
                    loop, self.scope_handle = loop
            except BaseException as exc:
                try:
                    await binding.close()
                except BaseException as close_exc:
                    raise exc from close_exc
                raise
            self.binding = binding
            self.loop = loop
            return self.loop

    async def execute(self, run_id, context):
        return await (await self._ensure_loop(context)).execute(run_id, context)

    async def resume(self, run_id, context):
        return await (await self._ensure_loop(context)).resume(run_id, context)

    async def recover_interrupted(self, run_id, context):
        loop = await self._ensure_loop(context)
        recover = getattr(loop, "recover_interrupted", None)
        return None if recover is None else await recover(run_id, context)

    async def on_suspended(self, context) -> None:
        if self.binding is not None:
            await self.binding.on_suspended(context)

    async def close(self) -> None:
        if self.scope_handle is not None:
            await self.scope_handle.close()
        if self.binding is not None:
            await self.binding.close()


class _OwnerValidatedCompatibilityDriver:
    """Fail closed when a pre-bound Tool runtime belongs to another Run."""

    def __init__(self, loop, tool_runtime: OfficialToolRuntime, run_id: str) -> None:
        self.loop = loop
        self.tool_runtime = tool_runtime
        self.run_id = run_id

    def _validate(self) -> None:
        if self.tool_runtime.sandbox.ref.owner_run_id != self.run_id:
            raise SageV2Error(
                RuntimeErrorInfo(
                    code="execution.binding_owner_mismatch",
                    category=ErrorCategory.AUTHORIZATION,
                    message=(
                        "with_tool_runtime sandbox owner does not match the actual "
                        "Run; use with_execution_binding_provider"
                    ),
                    safe_to_resume=False,
                )
            )

    async def execute(self, run_id, context):
        self._validate()
        return await self.loop.execute(run_id, context)

    async def resume(self, run_id, context):
        self._validate()
        return await self.loop.resume(run_id, context)

    async def recover_interrupted(self, run_id, context):
        self._validate()
        recover = getattr(self.loop, "recover_interrupted", None)
        return None if recover is None else await recover(run_id, context)


class _CompositeRunResource:
    def __init__(self, *resources) -> None:
        self.resources = resources

    async def close(self) -> None:
        for resource in reversed(self.resources):
            closed = resource.close()
            if hasattr(closed, "__await__"):
                await closed
