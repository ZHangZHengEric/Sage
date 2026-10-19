"""Run drivers that bind execution resources before composing an Agent loop."""

from __future__ import annotations

from sagents.v2.runtime.execution import (
    ExecutionBindingProvider,
    ExecutionBindingRequest,
    RunExecutionBinding,
)


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
        self._closing_resources = None

    async def _ensure_loop(self, context):
        if self.loop is not None:
            return self.loop
        if self._lock is None:
            import asyncio

            self._lock = asyncio.Lock()
        async with self._lock:
            if self.loop is not None:
                return self.loop
            from sagents.v2.runtime.execution.environment import RunExecutionEnvironment, _bind_execution_environment
            command = await self.runtime.session_store.get_start_command(self.run_id)
            if self.provider is None:
                with _bind_execution_environment(RunExecutionEnvironment(self.run_id, command, context)):
                    built = await self.loop_builder(context)
                if isinstance(built, tuple):
                    self.loop, self.scope_handle = built
                else:
                    self.loop = built
                return self.loop
            policy = str(
                command.config.execution_snapshot.workspace_policy if command.config.execution_snapshot is not None
                else command.config.metadata.get("workspace_policy") or "shared_parent"
            )
            request = ExecutionBindingRequest(
                run_id=self.run_id,
                parent_run_id=command.parent_run_id,
                agent_id=self.agent_id,
                workspace_policy=policy,
                context=context,
                configuration=command.config.execution_snapshot,
            )
            binding = await self.provider.acquire(request)
            self.binding = binding
            try:
                binding.validate_for(request)
                await self.runtime.record_execution_binding(binding, context)
                with _bind_execution_environment(RunExecutionEnvironment(
                    self.run_id, command, context, binding.sandbox,
                    binding.grant_issuer, binding.workspace_root,
                )):
                    loop = self.loop_builder(binding)
                    if hasattr(loop, "__await__"):
                        loop = await loop
                if isinstance(loop, tuple):
                    loop, self.scope_handle = loop
            except BaseException as exc:
                try:
                    await binding.close()
                    self.binding = None
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
        if self._closing_resources is None:
            # Close independent resources even when one owner fails. Successful
            # cleanup is removed from the retry set, preserving external effects.
            controller = getattr(self.loop, "delegated_run_controller", None)
            self._closing_resources = _CompositeRunResource(self.binding, self.scope_handle, controller)
        await self._closing_resources.close()


class _CompositeRunResource:
    def __init__(self, *resources) -> None:
        self.resources = tuple(resource for resource in resources if resource is not None)
        self._pending = list(dict((id(value), value) for value in self.resources).values())
        self._close_lock = None

    @property
    def provider_scopes(self):
        scopes = []
        for resource in self.resources:
            if hasattr(resource, "providers") and hasattr(resource, "context"):
                scopes.append(resource)
            elif isinstance(resource, _CompositeRunResource):
                scopes.extend(resource.provider_scopes)
        return tuple(scopes)

    async def close(self) -> None:
        import asyncio
        if self._close_lock is None:
            self._close_lock = asyncio.Lock()
        async with self._close_lock:
            errors = []
            for resource in reversed(tuple(self._pending)):
                try:
                    closed = resource.close()
                    if hasattr(closed, "__await__"):
                        await closed
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._pending = [value for value in self._pending if value is not resource]
            if errors:
                for other in errors[1:]:
                    errors[0].add_note(f"additional Run resource cleanup failure: {other}")
                raise errors[0]
