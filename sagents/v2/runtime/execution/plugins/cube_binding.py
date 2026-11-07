"""Opt-in Cube execution binding: persistent workspace, Run-owned compute."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import Field, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.execution import ExecutionConfigurationSnapshot
from sagents.v2.runtime.execution.binding import RunExecutionBinding
from sagents.v2.runtime.execution.configuration import (
    DEFAULT_ALLOWED_EXECUTABLES,
    DEFAULT_ALLOWED_ENV_NAMES,
    _require_narrower,
)
from sagents.v2.runtime.execution.plugins._shared.binding import (
    incompatible_configuration,
)
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LifecyclePolicy,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxDurability,
    SandboxGrantIssuer,
    SandboxReleaseDisposition,
)
from sagents.v2.runtime.execution.sandbox.plugins.cube import CubeVolumeSandboxProvider
from sagents.v2.runtime.execution.sandbox.plugins.cube.files import cube_file_call


class CubeExecutionPolicy(StrictModel):
    filesystem: FileSystemPolicy = Field(
        default_factory=lambda: FileSystemPolicy(
            allowed_operations=frozenset(FileOperation), max_file_bytes=8 << 20
        )
    )
    process: ProcessPolicy = Field(
        default_factory=lambda: ProcessPolicy(
            enabled=True,
            allowed_executables=DEFAULT_ALLOWED_EXECUTABLES,
            allow_shell=True,
            allowed_env_names=DEFAULT_ALLOWED_ENV_NAMES,
            max_wall_time_seconds=300,
        )
    )
    resources: ResourceLimits = Field(
        default_factory=lambda: ResourceLimits(require_hard_limits=False)
    )
    network: NetworkPolicy = Field(default_factory=NetworkPolicy)

    @model_validator(mode="after")
    def supported_policy(self):
        if (
            self.filesystem.allowed_roots != ("/workspace",)
            or self.filesystem.allow_symlinks
        ):
            raise ValueError("Cube workspace requires /workspace without symlinks")
        if (
            self.filesystem.max_total_bytes is not None
            or self.resources.require_hard_limits
        ):
            raise ValueError("Cube binding cannot enforce hard CPU/memory/disk quotas")
        if (
            self.filesystem.max_file_bytes is None
            or self.filesystem.max_file_bytes > 8 << 20
        ):
            raise ValueError("Cube file operations require a limit of at most 8 MiB")
        if self.network.mode.value not in {"none", "unrestricted"}:
            raise ValueError("Cube binding supports none/unrestricted network")
        if (
            self.network.mode.value == "unrestricted"
            and self.network.deny_private_networks
        ):
            raise ValueError(
                "Cube unrestricted network does not filter private addresses"
            )
        if self.process.allow_background_jobs:
            raise ValueError("use managed Shell jobs instead of detached processes")
        if self.process.enabled and self.filesystem.allowed_operations not in {
            frozenset(FileOperation),
            frozenset({FileOperation.READ, FileOperation.LIST}),
        }:
            raise ValueError(
                "native processes require full operations or read/list only"
            )
        if self.filesystem.allowed_operations <= {
            FileOperation.READ,
            FileOperation.LIST,
        }:
            object.__setattr__(
                self, "process", self.process.model_copy(update={"read_only": True})
            )
        if (
            self.filesystem.protected_paths
            and self.process.enabled
            and not self.process.read_only
        ):
            raise ValueError("Cube writable processes cannot enforce protected paths")
        return self

    def narrow(self, overrides):
        source = self.model_dump(mode="json")
        for key, values in (overrides or {}).items():
            if key not in source or not isinstance(values, dict):
                raise ValueError("unknown Cube execution policy section")
            source[key] = {**source[key], **values}
        selected = type(self).model_validate(source)
        if (
            self.process.allowed_executables
            and not selected.process.allowed_executables
        ):
            raise ValueError("execution policy cannot remove its executable allowlist")
        _require_narrower(
            self.model_dump(mode="json"), selected.model_dump(mode="json")
        )
        return selected


class CubeExecutionBindingConfig(StrictModel):
    workspace_user_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    api_url: str = Field(min_length=1)
    template_id: str = Field(min_length=1)
    proxy_node_ip: str = Field(min_length=1)
    api_key: str | None = Field(
        default=None, repr=False, json_schema_extra={"writeOnly": True}
    )
    volume_driver: str | None = None
    policy: CubeExecutionPolicy = Field(default_factory=CubeExecutionPolicy)
    child_workspace_policy: str = "shared_parent"

    @model_validator(mode="after")
    def validate_children(self):
        if self.child_workspace_policy not in {
            "shared_parent",
            "private_child",
            "read_only_parent",
        }:
            raise ValueError("unknown child workspace policy")
        return self


class _OwnedCubeHandle:
    def __init__(self, handle):
        self.handle = handle
        self._close_task = None

    def __getattr__(self, name):
        return getattr(self.handle, name)

    async def close(self):
        if self._close_task is None:

            async def release():
                provider = self.handle.provider
                row = provider._row(self.handle.ref)
                await self.handle.close()
                if row.attached_clients == 0:
                    from sagents.v2.runtime.execution.sandbox.contracts import (
                        TerminateMode,
                    )

                    await provider.terminate(self.handle.ref, TerminateMode.FORCE)
                    await provider.purge_terminated(self.handle.ref)

            self._close_task = asyncio.create_task(release())
        await asyncio.shield(self._close_task)

    async def initialize_workspace(self, initializer):
        if self.handle.provider._row(self.handle.ref).spec.process.read_only:
            return

        # Existing initializers operate on Paths. Render seeds temporarily,
        # then create only absent remote entries; tenant files stay authoritative.
        def initialize():
            sandbox = self.handle.provider._row(self.handle.ref).sandbox
            with TemporaryDirectory(prefix="sage-workspace-seed-") as directory:
                root = Path(directory)
                initializer.initialize(root)
                for path in sorted(root.rglob("*")):
                    relative = path.relative_to(root).as_posix()
                    if path.is_symlink():
                        raise ValueError("workspace initializer produced a symlink")
                    if path.is_dir():
                        cube_file_call(sandbox, "mkdir", relative)
                    elif path.is_file():
                        try:
                            cube_file_call(
                                sandbox,
                                "write",
                                relative,
                                data=base64.b64encode(path.read_bytes()).decode(),
                                max_bytes=8 << 20,
                                overwrite=False,
                            )
                        except FileExistsError:
                            pass

        from sagents.v2.concurrency import bounded_to_thread

        await bounded_to_thread("skill-io", initialize)


class CubeExecutionBindingProvider:
    plugin_id = "sage.execution.binding.cube-volume"
    name = "Cube Volume execution binding"
    description = "Run-owned remote compute over a persistent Cube workspace."

    def __init__(self, config, *, sandbox_provider=None, issuer=None):
        self.config = CubeExecutionBindingConfig.model_validate(config)
        self.issuer = issuer or SandboxGrantIssuer()
        self.sandbox_provider = sandbox_provider or CubeVolumeSandboxProvider(
            self.issuer.verification_key,
            **{
                key: getattr(self.config, key)
                for key in (
                    "api_url",
                    "template_id",
                    "proxy_node_ip",
                    "api_key",
                    "volume_driver",
                )
            },
        )
        self.bindings = []
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def idle(self):
        return not self._lock.locked() and all(
            binding.closed for binding in self.bindings
        )

    def _environment(self):
        return {
            "process_instance": self.sandbox_provider.process_instance,
            **{
                key: getattr(self.config, key)
                for key in (
                    "workspace_user_id",
                    "agent_id",
                    "api_url",
                    "template_id",
                    "proxy_node_ip",
                    "volume_driver",
                )
            },
        }

    async def accept_configuration(self, command, *, context, parent_command=None):
        try:
            if parent_command is not None:
                parent = parent_command.config.execution_snapshot
                self._validate(parent)
                values = parent.model_dump(mode="json")
                policy = CubeExecutionPolicy.model_validate(parent.policy).narrow(
                    command.config.execution_policy
                )
                relationship = command.config.metadata.get(
                    "workspace_policy", parent.child_workspace_policy
                )
                if (
                    parent.child_workspace_policy != "shared_parent"
                    and relationship != parent.child_workspace_policy
                ):
                    raise ValueError(
                        "child workspace relationship exceeds parent authorization"
                    )
            else:
                policy = self.config.policy.narrow(command.config.execution_policy)
                relationship = command.config.metadata.get(
                    "workspace_policy", "shared_parent"
                )
                values = dict(
                    schema_version="sage.execution/v1",
                    provider_id=self.sandbox_provider.provider_id,
                    workspace_root="/workspace",
                    private_workspace_root="cube:private",
                    child_workspace_policy=self.config.child_workspace_policy,
                    tool_environment=self._environment(),
                )
            if relationship not in {
                "shared_parent",
                "private_child",
                "read_only_parent",
            }:
                raise ValueError("unknown child workspace relationship")
            if relationship == "read_only_parent":
                policy = policy.narrow(
                    {
                        "filesystem": {"allowed_operations": ["read", "list"]},
                        "process": {"read_only": True},
                    }
                )
            if relationship == "private_child":
                values["tool_environment"] = {
                    **values["tool_environment"],
                    "workspace_scope": hashlib.sha256(
                        json.dumps(
                            [command.parent_run_id, command.idempotency_key]
                        ).encode()
                    ).hexdigest(),
                }
            values.update(
                workspace_policy=relationship, policy=policy.model_dump(mode="json")
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
        except (ValueError, KeyError) as exc:
            raise incompatible_configuration(str(exc)) from exc

    def _validate(self, snapshot):
        if snapshot is None:
            raise incompatible_configuration(
                "Run has no accepted Cube execution configuration"
            )
        snapshot = ExecutionConfigurationSnapshot.model_validate(
            snapshot.model_dump(mode="json")
        )
        if (
            snapshot.provider_id != self.sandbox_provider.provider_id
            or snapshot.workspace_root != "/workspace"
            or any(
                snapshot.tool_environment.get(key) != value
                for key, value in self._environment().items()
            )
        ):
            raise incompatible_configuration(
                "accepted Cube execution configuration is unavailable"
            )
        return snapshot

    def sandbox_spec(self, snapshot):
        snapshot = self._validate(snapshot)
        policy = CubeExecutionPolicy.model_validate(snapshot.policy)
        return ResolvedSandboxSpec(
            spec_hash=snapshot.configuration_id,
            policy_hash=snapshot.configuration_id,
            workspace_root="/workspace",
            architecture="native",
            filesystem=policy.filesystem,
            process=policy.process,
            network=policy.network,
            resources=policy.resources,
            lifecycle=LifecyclePolicy(
                durability=SandboxDurability.DURABLE_EXTERNAL,
                safe_pause_behavior=SandboxReleaseDisposition.TERMINATE,
                unsafe_pause_behavior=SandboxReleaseDisposition.TERMINATE,
            ),
            metadata={
                "cube_agent_id": self.config.agent_id,
                "cube_workspace_user_id": self.config.workspace_user_id,
                "cube_workspace_scope": snapshot.tool_environment.get(
                    "workspace_scope"
                ),
            },
        )

    async def acquire(self, request):
        snapshot = self._validate(request.configuration)
        if (
            str(getattr(request.workspace_policy, "value", request.workspace_policy))
            != snapshot.workspace_policy
        ):
            raise incompatible_configuration(
                "binding relationship differs from accepted Cube configuration"
            )
        async with self._lock:
            if self._closed:
                raise RuntimeError("Cube execution binding provider is closed")
            self.bindings = [value for value in self.bindings if not value.closed]
            existing = next(
                (value for value in self.bindings if value.run_id == request.run_id),
                None,
            )
            if existing is not None:
                if (
                    existing.configuration_id != snapshot.configuration_id
                    or existing.parent_run_id != request.parent_run_id
                ):
                    raise incompatible_configuration(
                        "live Cube Run lease differs from its accepted configuration"
                    )
                handle = await self.sandbox_provider.attach(
                    existing.sandbox.ref, request.context
                )
                binding = replace(existing, sandbox=_OwnedCubeHandle(handle))
                self.bindings.append(binding)
                return binding
            handle = await self.sandbox_provider.provision(
                self.sandbox_spec(snapshot), request.context, run_id=request.run_id
            )
            binding = RunExecutionBinding(
                run_id=request.run_id,
                agent_id=request.agent_id,
                parent_run_id=request.parent_run_id,
                workspace_root="/workspace",
                workspace_policy=snapshot.workspace_policy,
                sandbox=_OwnedCubeHandle(handle),
                grant_issuer=self.issuer,
                configuration_id=snapshot.configuration_id,
                configuration=snapshot,
                diagnostics={
                    "sandbox": handle.ref.model_dump(mode="json"),
                    "workspace_backend": "cube-volume",
                },
            )
            self.bindings = [value for value in self.bindings if not value.closed]
            self.bindings.append(binding)
            return binding

    async def close(self):
        async with self._lock:
            self._closed = True
            results = await asyncio.gather(
                *(binding.close() for binding in self.bindings), return_exceptions=True
            )
            self.bindings = [binding for binding in self.bindings if not binding.closed]
            errors = [result for result in results if isinstance(result, BaseException)]
            if errors:
                raise RuntimeError("Cube compute cleanup failed") from errors[0]


def cube_execution_binding_registration():
    import importlib.util
    from sagents.v2.runtime.extensions import (
        ExtensionDescriptor,
        ExtensionRegistration,
        ExtensionScope,
        CapabilityOffer,
    )
    from sagents.v2.runtime.extensions.contracts import ExtensionAvailability

    return ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id=CubeExecutionBindingProvider.plugin_id,
            name=CubeExecutionBindingProvider.name,
            description=CubeExecutionBindingProvider.description,
            version="1.0.0",
            built_in=True,
            provides=(
                CapabilityOffer(capability="execution.binding", api_version="2"),
            ),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema=CubeExecutionBindingConfig.model_json_schema(),
            availability=ExtensionAvailability(
                available=importlib.util.find_spec("cubesandbox") is not None,
                reason="Install Sage's cube extra to enable Cube execution",
            ),
        ),
        config_model=CubeExecutionBindingConfig,
        factory=lambda context, deps: CubeExecutionBindingProvider(context.config),
    )
