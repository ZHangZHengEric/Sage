"""Standard binding for explicitly selected, process-local memory sandboxes."""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from uuid import uuid4

from pydantic import Field, field_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.execution import ExecutionConfigurationSnapshot
from sagents.v2.runtime.extensions import (
    CapabilityOffer,
    ExtensionDependency,
    ExtensionDescriptor,
    ExtensionRegistration,
    ExtensionScope,
)
from sagents.v2.runtime.execution.binding import RunExecutionBinding
from sagents.v2.runtime.execution.configuration import LocalExecutionPolicy
from sagents.v2.runtime.execution.plugins._shared.binding import incompatible_configuration
from sagents.v2.runtime.execution.sandbox import (
    InMemorySandboxProvider,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)


class EphemeralExecutionBindingConfig(StrictModel):
    workspace_root: str = "/workspace"
    policy: LocalExecutionPolicy = Field(
        default_factory=lambda: LocalExecutionPolicy.model_validate(
            {
                "process": {"enabled": False},
                "resources": {"require_hard_limits": False},
            }
        )
    )

    @field_validator("workspace_root")
    @classmethod
    def canonical_workspace(cls, value):
        if (
            not value.startswith("/")
            or value == "/"
            or str(PurePosixPath(value)) != value
            or ".." in PurePosixPath(value).parts
        ):
            raise ValueError(
                "workspace_root must be a canonical absolute virtual directory"
            )
        return value


class EphemeralExecutionBindingProvider:
    """Memory files survive suspension within this App; restart fails explicitly.

    There is no native process or host filesystem access. Child Runs get their
    own workspace; sharing requires a binding with Run-owned sharing support.
    """

    plugin_id = "sage.execution.binding.ephemeral"
    name = "Process-local memory binding"
    description = "Independent virtual files with explicit process-local recovery limits."

    def __init__(self, config, store):
        self.config, self.store = config, store
        self.issuer = SandboxGrantIssuer()
        self.provider = InMemorySandboxProvider(self.issuer.verification_key)
        self.identity = uuid4().hex
        self.refs = {}
        self.closed = False
        self.lock = asyncio.Lock()

    async def accept_configuration(self, command, *, context, parent_command=None):
        policy = self.config.policy.narrow(command.config.execution_policy)
        if parent_command is not None:
            parent = parent_command.config.execution_snapshot
            await self._restore(parent)
            policy = LocalExecutionPolicy.model_validate(parent.policy).narrow(
                command.config.execution_policy
            )
        relationship = command.config.metadata.get(
            "workspace_policy", "private_child" if parent_command else "shared_parent"
        )
        if parent_command is not None and relationship != "private_child":
            raise incompatible_configuration(
                "memory bindings require independent child workspaces"
            )
        if relationship == "read_only_parent":
            policy = policy.narrow(
                {
                    "filesystem": {"allowed_operations": ["read", "list"]},
                    "process": {"read_only": True},
                }
            )
        caps = await self.provider.capabilities()
        if (
            policy.process.enabled
            or policy.network.mode.value != "none"
            or policy.resources.require_hard_limits
        ):
            raise incompatible_configuration(
                "memory binding has no native processes, network or hard resource limits"
            )
        values = dict(
            schema_version="sage.execution/v1",
            provider_id=self.provider.provider_id,
            workspace_root=self.config.workspace_root,
            private_workspace_root=self.config.workspace_root,
            workspace_policy=relationship,
            child_workspace_policy="private_child",
            policy=policy.model_dump(mode="json"),
            tool_environment={
                "process_instance": self.identity,
                "capabilities": caps.model_dump(mode="json"),
            },
        )
        values["configuration_id"] = ExecutionConfigurationSnapshot.identity(values)
        snapshot = ExecutionConfigurationSnapshot.model_validate(values)
        return command.model_copy(
            update={
                "config": command.config.model_copy(
                    update={
                        "execution_snapshot": snapshot,
                        "metadata": {
                            **command.config.metadata,
                            "workspace_policy": relationship,
                        },
                    },
                    deep=True,
                )
            }
        )

    async def _restore(self, snapshot):
        if snapshot is not None:
            try:
                snapshot = ExecutionConfigurationSnapshot.model_validate(
                    snapshot.model_dump(mode="json")
                )
            except ValueError as error:
                raise incompatible_configuration(
                    str(error)
                ) from error
        if (
            self.closed
            or snapshot is None
            or snapshot.provider_id != self.provider.provider_id
            or snapshot.tool_environment.get("process_instance") != self.identity
        ):
            raise incompatible_configuration(
                "original process-local memory sandbox is unavailable; it cannot be recovered after restart"
            )
        return snapshot

    async def acquire(self, request):
        snapshot = await self._restore(request.configuration)
        if (
            str(getattr(request.workspace_policy, "value", request.workspace_policy))
            != snapshot.workspace_policy
        ):
            raise incompatible_configuration(
                "binding relationship differs from the accepted configuration"
            )
        policy = LocalExecutionPolicy.model_validate(snapshot.policy)
        async with self.lock:
            if self.closed:
                raise RuntimeError("memory binding is closed")
            ref = self.refs.get(request.run_id)
            if ref is None:
                spec = ResolvedSandboxSpec(
                    spec_hash=snapshot.configuration_id,
                    policy_hash=snapshot.configuration_id,
                    workspace_root=snapshot.workspace_root,
                    architecture="portable",
                    filesystem=policy.filesystem.model_copy(
                        update={"allowed_roots": (snapshot.workspace_root,)}
                    ),
                    process=policy.process,
                    network=policy.network,
                    resources=policy.resources,
                )
                handle = await self.provider.provision(
                    spec, request.context, run_id=request.run_id
                )
                self.refs[request.run_id] = handle.ref
            else:
                handle = await self.provider.attach(ref, request.context)
        owner = self

        class Lease:
            ref, filesystem, process, network = (
                handle.ref,
                handle.filesystem,
                handle.process,
                handle.network,
            )

            async def status(self):
                return await handle.status()

            async def suspend(self):
                return await handle.suspend()

            async def close(self):
                await handle.close()
                run = await owner.store.get_run(request.run_id)
                if run.state.value in {"completed", "failed", "cancelled"}:
                    await handle.destroy()
                    owner.refs.pop(request.run_id, None)

            async def destroy(self):
                await handle.destroy()
                owner.refs.pop(request.run_id, None)

            def describe_environment(self):
                return {
                    "os": "memory",
                    "workspace_root": snapshot.workspace_root,
                    "process_available": False,
                }

        return RunExecutionBinding(
            run_id=request.run_id,
            parent_run_id=request.parent_run_id,
            agent_id=request.agent_id,
            workspace_root=snapshot.workspace_root,
            workspace_policy=request.workspace_policy,
            sandbox=Lease(),
            grant_issuer=self.issuer,
            configuration_id=snapshot.configuration_id,
            configuration=snapshot,
            diagnostics={
                "configuration_id": snapshot.configuration_id,
                "sandbox": handle.ref.model_dump(mode="json"),
                "capabilities": (await self.provider.capabilities()).model_dump(
                    mode="json"
                ),
                "interpreter": None,
                "runtime_read_paths": [],
                "recovery": "same_process",
            },
        )

    async def close(self):
        from sagents.v2.runtime.execution.sandbox.contracts import TerminateMode

        async with self.lock:
            self.closed = True
            refs = tuple(self.refs.items())
        for run_id, ref in refs:
            await self.provider.terminate(ref, TerminateMode.FORCE)
            self.refs.pop(run_id, None)


def ephemeral_execution_binding_registration():
    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id=EphemeralExecutionBindingProvider.plugin_id,
            name="Process-local memory binding",
            description="Independent virtual files with explicit process-local recovery limits.",
            version="1.0.0",
            provides=(
                CapabilityOffer(capability="execution.binding", api_version="2"),
            ),
            dependencies=(ExtensionDependency(capability="session.store"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            built_in=True,
            config_schema=EphemeralExecutionBindingConfig.model_json_schema(),
        ),
        factory=lambda context, dependencies: EphemeralExecutionBindingProvider(
            EphemeralExecutionBindingConfig.model_validate(context.config),
            dependencies.require("session.store"),
        ),
        config_model=EphemeralExecutionBindingConfig,
    )
