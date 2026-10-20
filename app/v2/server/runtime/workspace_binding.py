"""Resolve trusted tenant workspaces at admission, independently of revisions."""
from __future__ import annotations

import asyncio
from pathlib import Path

from sagents.v2.runtime.execution.plugins.local_binding.registration import LocalExecutionBindingConfig
from sagents.v2.runtime.execution.plugins.local_binding import LocalWorkspaceExecutionBindingProvider


class ServerExecutionBindingConfig(LocalExecutionBindingConfig):
    owner: str
    agent_id: str


class ServerWorkspaceBindingProvider:
    def __init__(self, host, config, store):
        self.host = host
        from sagents.v2.runtime.session import AuthorizedSessionAccess
        self.access = AuthorizedSessionAccess(store)
        self.config = ServerExecutionBindingConfig.model_validate(config)
        self._providers = {}
        self._lock = asyncio.Lock()
        self._idle = asyncio.Condition(self._lock)
        self._pending = {}
        self._closed = False

    def _authorize(self, context):
        if context.actor.principal_id != self.config.owner or context.actor.tenant_id != self.config.owner:
            raise PermissionError("Server execution resources belong to another owner")

    def _provider(self, workspace):
        from sagents.v2.runtime.execution.plugins.local_binding.registration import local_execution_binding_registration
        from types import SimpleNamespace
        values = self.config.model_dump(mode="python", exclude={"owner", "agent_id"})
        values.update(workspace=str(workspace), private_workspace_root=str(workspace.parent / ".sage-private-workspaces"))
        return local_execution_binding_registration().factory(SimpleNamespace(config=values), None)

    async def accept_configuration(self, command, *, context, parent_command=None):
        from app.v2.server.storage.workspaces import workspace_user
        self._authorize(context)
        # Child Runs inherit the exact admitted parent mapping, including private
        # workspace relationships; root metadata has already passed ingress auth.
        workspace = (Path(parent_command.config.execution_snapshot.workspace_root)
                     if parent_command is not None and parent_command.config.execution_snapshot is not None
                     else self.host.paths.workspace_dir(workspace_user(command, self.config.owner), self.config.agent_id))
        provider = self._provider(workspace)
        try:
            return await provider.accept_configuration(command, context=context, parent_command=parent_command)
        finally:
            await provider.close()

    async def acquire(self, request):
        self._authorize(request.context)
        if request.configuration is None:
            raise LocalWorkspaceExecutionBindingProvider._incompatible("Run has no accepted execution configuration")
        # Only durable, authorized commands can establish the host path. The
        # caller's request snapshot alone cannot redirect execution resources.
        command = await self.access.get_start_command(request.run_id, request.context)
        if command.config.execution_snapshot != request.configuration:
            raise LocalWorkspaceExecutionBindingProvider._incompatible("binding differs from the admitted execution configuration")
        workspace = Path(request.configuration.workspace_root)
        async with self._lock:
            if self._closed:
                raise RuntimeError("Server execution binding provider is closed")
            for key, provider in tuple(self._providers.items()):
                if key != str(workspace) and not self._pending.get(key) and all(binding.closed for binding in provider.bindings):
                    await provider.close()
                    del self._providers[key]
            provider = self._providers.get(str(workspace))
            if provider is None:
                provider = self._provider(workspace)
                self._providers[str(workspace)] = provider
            key = str(workspace)
            self._pending[key] = self._pending.get(key, 0) + 1
        try:
            return await provider.acquire(request)
        finally:
            async with self._idle:
                count = self._pending[key] - 1
                if count:
                    self._pending[key] = count
                else:
                    self._pending.pop(key, None)
                self._idle.notify_all()

    async def close(self):
        async with self._idle:
            self._closed = True
            while self._pending:
                await self._idle.wait()
            for key, provider in tuple(self._providers.items()):
                await provider.close()
                del self._providers[key]
