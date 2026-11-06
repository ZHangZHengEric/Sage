"""Authenticated Server adapter for the optional standard Cube binding."""

from __future__ import annotations

import asyncio

from pydantic import Field

from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.execution import ExecutionConfigurationSnapshot
from sagents.v2.runtime.execution.plugins._shared.binding import (
    incompatible_configuration,
)
from sagents.v2.runtime.execution.plugins.cube_binding import (
    CubeExecutionBindingConfig,
    CubeExecutionBindingProvider,
    CubeExecutionPolicy,
)
from app.v2.server.storage.workspaces import workspace_user


class ServerCubeBindingConfig(StrictModel):
    owner: str
    agent_id: str
    policy: CubeExecutionPolicy = Field(default_factory=CubeExecutionPolicy)


class ServerCubeBindingProvider:
    def __init__(self, host, config, store):
        from sagents.v2.runtime.session import AuthorizedSessionAccess

        self.host = host
        self.config = ServerCubeBindingConfig.model_validate(config)
        self.access = AuthorizedSessionAccess(store)
        self._providers = {}

    def _authorize(self, context):
        if (
            context.actor.principal_id != self.config.owner
            or context.actor.tenant_id != self.config.owner
        ):
            raise PermissionError("Server Cube resources belong to another owner")

    def _provider(self, user):
        if user not in self._providers:
            # Closed tenant bindings are reconstructible from admitted snapshots.
            # Retain active providers, but do not accumulate one cache per tenant.
            for key, provider in tuple(self._providers.items()):
                if len(self._providers) < 64:
                    break
                if not provider._lock.locked() and all(
                    binding.closed for binding in provider.bindings
                ):
                    self._providers.pop(key)
            settings = self.host.settings
            config = CubeExecutionBindingConfig(
                workspace_user_id=user,
                agent_id=self.config.agent_id,
                api_url=settings.cube_api_url,
                template_id=settings.cube_template_id,
                proxy_node_ip=settings.cube_proxy_node_ip,
                volume_driver=settings.cube_volume_driver,
                policy=self.config.policy,
            )
            self._providers[user] = CubeExecutionBindingProvider(
                config,
                sandbox_provider=self.host.execution.sandbox_provider,
                issuer=self.host.execution.sandbox_grant_issuer,
            )
        return self._providers[user]

    async def accept_configuration(self, command, *, context, parent_command=None):
        self._authorize(context)
        user = (
            parent_command.config.execution_snapshot.tool_environment[
                "workspace_user_id"
            ]
            if parent_command is not None
            and parent_command.config.execution_snapshot is not None
            else workspace_user(command, self.config.owner)
        )
        accepted = await self._provider(user).accept_configuration(
            command, context=context, parent_command=parent_command
        )
        existing = (
            await self.access.find_start_run(
                command.session_id, command.idempotency_key, context
            )
            if command.session_id
            else None
        )
        previous = existing[1].config.execution_snapshot if existing else None
        if (
            previous is not None
            and previous.provider_id == accepted.config.execution_snapshot.provider_id
        ):
            # Keep retries of an admitted request stable across Server restarts.
            # All other request/configuration changes still reach the store's
            # digest check. Acquisition continues to reject old process leases.
            values = accepted.config.execution_snapshot.model_dump(mode="json")
            values["tool_environment"]["process_instance"] = previous.tool_environment[
                "process_instance"
            ]
            values["configuration_id"] = ExecutionConfigurationSnapshot.identity(values)
            snapshot = ExecutionConfigurationSnapshot.model_validate(values)
            accepted = accepted.model_copy(
                update={
                    "config": accepted.config.model_copy(
                        update={"execution_snapshot": snapshot}
                    )
                }
            )
        return accepted

    async def acquire(self, request):
        self._authorize(request.context)
        command = await self.access.get_start_command(request.run_id, request.context)
        if (
            command.config.execution_snapshot is None
            or command.config.execution_snapshot != request.configuration
        ):
            raise incompatible_configuration(
                "Cube binding differs from the admitted Run configuration"
            )
        user = command.config.execution_snapshot.tool_environment["workspace_user_id"]
        return await self._provider(user).acquire(request)

    async def close(self):
        results = await asyncio.gather(
            *(provider.close() for provider in tuple(self._providers.values())),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise RuntimeError("Cube tenant cleanup failed") from errors[0]
