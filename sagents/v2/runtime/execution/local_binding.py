"""Reusable local workspace binding provider for the standard Builder."""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path

from sagents.v2.agent.multi_agent import WorkspaceSharingPolicy
from sagents.v2.contracts.execution import ExecutionConfigurationSnapshot
from sagents.v2.contracts.errors import ErrorCategory, RuntimeErrorInfo, SageV2Error
from .configuration import LocalExecutionPolicy
from .configuration import DEFAULT_ALLOWED_EXECUTABLES as DEFAULT_ALLOWED_EXECUTABLES
from .configuration import DEFAULT_ALLOWED_ENV_NAMES as DEFAULT_ALLOWED_ENV_NAMES
from .sandbox.local_support.interpreter import inspect_isolation_python
from sagents.v2.runtime.execution import (
    ExecutionBindingRequest,
    RunExecutionBinding,
)
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ResolvedSandboxSpec,
    ResourceLimits,
    SandboxGrantIssuer,
)

class LocalWorkspaceExecutionBindingProvider:
    """``ExecutionBindingProvider`` for a local-workspace sandbox."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        issuer: SandboxGrantIssuer | None = None,
        sandbox_provider: LocalWorkspaceSandboxProvider | None = None,
        private_workspace_root: str | Path | None = None,
        read_only: bool = False,
        process_enabled: bool = True,
        resources: ResourceLimits | None = None,
        network: NetworkPolicy | None = None,
        policy: LocalExecutionPolicy | None = None,
        command_path: str | None = None,
        read_paths: tuple[str, ...] = (),
        isolation_python: str | None = None,
        child_workspace_policy: str = "shared_parent",
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.workspace_root = self.workspace.as_posix()
        self.private_workspace_root = (
            Path(private_workspace_root).expanduser().resolve()
            if private_workspace_root is not None
            else self.workspace.parent
            / f".{self.workspace.name}.sage-private-workspaces"
        )
        if (
            self.private_workspace_root == self.workspace
            or self.workspace in self.private_workspace_root.parents
        ):
            raise ValueError(
                "private workspace root must be outside the shared workspace"
            )
        self.issuer = issuer or SandboxGrantIssuer()
        self.sandbox_provider = sandbox_provider or LocalWorkspaceSandboxProvider(
            self.issuer.verification_key, command_path=command_path,
            read_paths=read_paths, isolation_python=isolation_python,
        )
        if sandbox_provider is not None and (command_path is not None or read_paths or isolation_python is not None):
            raise ValueError("tool environment must be configured on the supplied sandbox provider")
        self.read_only = read_only
        self.child_workspace_policy = WorkspaceSharingPolicy(child_workspace_policy)
        self.process_enabled = process_enabled
        self.network = network or NetworkPolicy()
        # 内核硬限制来自管理员委派的 cgroup 子树与 XFS project 挂载，随 provider
        # 一起配置；默认构造的 provider 没有它们，所以默认不声称拥有。配了的宿主
        # 由 runtime_config 把 require_hard_limits 传进来。
        self.resources = resources or ResourceLimits(require_hard_limits=False)
        if policy is not None and (resources is not None or network is not None):
            raise ValueError("policy cannot be combined with resources/network")
        self.policy = policy or LocalExecutionPolicy(
            resources=self.resources, network=self.network,
        )
        if read_only:
            self.policy = self.policy.model_copy(update={
                "filesystem": self.policy.filesystem.model_copy(update={
                    "allowed_operations": frozenset({FileOperation.READ, FileOperation.LIST}),
                }),
                "process": self.policy.process.model_copy(update={"read_only": True}),
            })
        elif not process_enabled:
            self.policy = self.policy.model_copy(update={
                "process": self.policy.process.model_copy(update={"enabled": False}),
            })
        self.bindings: list[RunExecutionBinding] = []
        self._lock = asyncio.Lock()
        self._closed = False

    async def accept_configuration(self, command, *, context, parent_command=None):
        """Freeze before create_run; never trust a caller-supplied snapshot."""
        try:
            if parent_command is not None:
                snapshot = parent_command.config.execution_snapshot
                if snapshot is None:
                    raise ValueError("parent Run has no accepted execution configuration")
                policy = LocalExecutionPolicy.model_validate(snapshot.policy).narrow(
                    command.config.execution_policy
                )
                relationship = command.config.metadata.get("workspace_policy", snapshot.child_workspace_policy)
                if relationship not in {"shared_parent", "private_child", "read_only_parent"}:
                    raise ValueError("unknown child workspace relationship")
                if snapshot.child_workspace_policy != "shared_parent" and relationship != snapshot.child_workspace_policy:
                    raise ValueError("child workspace relationship exceeds the accepted parent authorization")
                if relationship == "read_only_parent":
                    policy = policy.narrow({"filesystem": {"allowed_operations": ["read", "list"]},
                                            "process": {"read_only": True}})
                values = snapshot.model_dump(mode="json")
                values["workspace_policy"] = relationship
                values["policy"] = policy.model_dump(mode="json")
            else:
                policy = self.policy.narrow(command.config.execution_policy)
                relationship = WorkspaceSharingPolicy(command.config.metadata.get("workspace_policy", "shared_parent")).value
                if relationship == "read_only_parent":
                    policy = policy.narrow({"filesystem": {"allowed_operations": ["read", "list"]},
                                            "process": {"read_only": True}})
                interpreter = await asyncio.to_thread(
                    inspect_isolation_python, self.sandbox_provider.isolation_python,
                    forbidden_roots=(self.workspace, self.private_workspace_root),
                )
                values = dict(
                    schema_version="sage.execution/v1",
                    provider_id=self.sandbox_provider.provider_id,
                    workspace_root=self.workspace_root,
                    private_workspace_root=str(self.private_workspace_root),
                    workspace_policy=relationship,
                    child_workspace_policy=self.child_workspace_policy.value,
                    policy=policy.model_dump(mode="json"),
                    tool_environment={
                        "command_path": self.sandbox_provider.command_path,
                        "read_paths": list(self.sandbox_provider.read_paths),
                        "interpreter": interpreter,
                    },
                )
            values["configuration_id"] = ExecutionConfigurationSnapshot.identity(values)
            snapshot = ExecutionConfigurationSnapshot.model_validate(values)
            return command.model_copy(update={"config": command.config.model_copy(
                update={"execution_snapshot": snapshot, "metadata": {
                    **command.config.metadata, "workspace_policy": snapshot.workspace_policy,
                }}, deep=True,
            )})
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            raise self._incompatible(str(exc)) from exc

    @staticmethod
    def _incompatible(message):
        return SageV2Error(RuntimeErrorInfo(
            code="execution.configuration_incompatible", category=ErrorCategory.VALIDATION,
            message=message, message_key="error.execution.configuration_incompatible",
            message_params={"reason": message}, safe_to_resume=False,
        ))

    async def _restore_configuration(self, snapshot):
        if snapshot is None:
            raise self._incompatible("Run has no accepted execution configuration")
        try:
            # Revalidate nested dictionaries, including the durable digest.
            snapshot = ExecutionConfigurationSnapshot.model_validate(snapshot.model_dump(mode="json"))
            if (snapshot.provider_id != self.sandbox_provider.provider_id
                    or snapshot.workspace_root != self.workspace_root
                    or snapshot.private_workspace_root != str(self.private_workspace_root)):
                raise ValueError("accepted workspace/provider is unavailable")
            interpreter = snapshot.tool_environment["interpreter"]
            actual = await asyncio.to_thread(
                inspect_isolation_python, interpreter["executable"],
                forbidden_roots=(self.workspace, self.private_workspace_root),
            )
            if actual != interpreter:
                raise ValueError("accepted isolation Python or runtime paths changed")
            for path in snapshot.tool_environment["read_paths"]:
                if not Path(path).is_dir():
                    raise ValueError(f"accepted runtime directory is unavailable: {path}")
            return snapshot, LocalExecutionPolicy.model_validate(snapshot.policy)
        except (KeyError, ValueError, OSError, subprocess.SubprocessError) as exc:
            raise self._incompatible(str(exc)) from exc

    def sandbox_spec(
        self,
        *,
        workspace: Path | None = None,
        read_only: bool | None = None,
        policy: LocalExecutionPolicy | None = None,
        tool_environment: dict | None = None,
    ) -> ResolvedSandboxSpec:
        resolved_workspace = (workspace or self.workspace).resolve()
        selected = policy or self.policy
        effective_read_only = self.read_only if read_only is None else read_only
        filesystem = selected.filesystem.model_copy(update={
            "allowed_operations": (
                selected.filesystem.allowed_operations & {FileOperation.READ, FileOperation.LIST}
                if effective_read_only else selected.filesystem.allowed_operations
            ),
            "allowed_roots": (resolved_workspace.as_posix(),),
            "max_total_bytes": min(
                selected.filesystem.max_total_bytes or selected.resources.disk_mb * 1024**2,
                selected.resources.disk_mb * 1024**2,
            ),
        })
        process = selected.process.model_copy(update={
            "enabled": selected.process.enabled,
            "read_only": selected.process.read_only or effective_read_only,
        })
        network = selected.network
        policy_source = json.dumps(
            {
                "filesystem": filesystem.model_dump(mode="json"),
                "process": process.model_dump(mode="json"),
                "network": network.model_dump(mode="json"),
                "resources": selected.resources.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        policy_hash = f"sha256:{hashlib.sha256(policy_source.encode()).hexdigest()}"
        spec_source = json.dumps(
            {
                "policy_hash": policy_hash,
                "workspace_root": resolved_workspace.as_posix(),
                "host_workspace": str(resolved_workspace),
                "tool_environment": tool_environment,
            },
            sort_keys=True,
        )
        spec_hash = f"sha256:{hashlib.sha256(spec_source.encode()).hexdigest()}"
        return ResolvedSandboxSpec(
            spec_hash=spec_hash,
            workspace_root=resolved_workspace.as_posix(),
            architecture="native",
            filesystem=filesystem,
            process=process,
            network=network,
            resources=selected.resources,
            policy_hash=policy_hash,
            metadata={"host_workspace": str(resolved_workspace),
                      **({"tool_environment": tool_environment} if tool_environment else {})},
        )

    async def acquire(self, request: ExecutionBindingRequest) -> RunExecutionBinding:
        snapshot, accepted_policy = await self._restore_configuration(request.configuration)
        if getattr(request.workspace_policy, "value", request.workspace_policy) != snapshot.workspace_policy:
            raise self._incompatible("binding relationship differs from the accepted Run configuration")
        policy = WorkspaceSharingPolicy(
            str(getattr(request.workspace_policy, "value", request.workspace_policy))
        )
        workspace = self.workspace
        if policy == WorkspaceSharingPolicy.PRIVATE_CHILD:
            digest = hashlib.sha256(request.run_id.encode()).hexdigest()[:24]
            workspace = self.private_workspace_root / digest
        effective_read_only = (
            accepted_policy.process.read_only or policy == WorkspaceSharingPolicy.READ_ONLY_PARENT
        )
        async with self._lock:
            if self._closed:
                raise RuntimeError("Local execution binding provider is closed")
            if policy == WorkspaceSharingPolicy.PRIVATE_CHILD:
                workspace.mkdir(parents=True, exist_ok=True)
                if workspace.is_symlink() or workspace.resolve().parent != self.private_workspace_root.resolve():
                    raise self._incompatible("private workspace escaped its accepted root")
            self.bindings = [value for value in self.bindings if not value.closed]
            existing = next((value for value in self.bindings if value.run_id == request.run_id), None)
            if existing is not None:
                if (existing.configuration_id != snapshot.configuration_id
                        or existing.parent_run_id != request.parent_run_id):
                    raise self._incompatible("live Run lease differs from its accepted configuration")
                handle = await self.sandbox_provider.attach(existing.sandbox.ref, request.context)
                binding = replace(existing, agent_id=request.agent_id, sandbox=handle)
                binding.lifecycle = request.lifecycle
                self.bindings.append(binding)
                return binding
            parent = next((value for value in self.bindings
                           if value.run_id == request.parent_run_id), None)
            if parent is not None and policy != WorkspaceSharingPolicy.PRIVATE_CHILD:
                workspace = Path(parent.workspace_root)
            if request.parent_run_id and policy != WorkspaceSharingPolicy.PRIVATE_CHILD and parent is None:
                raise SageV2Error(RuntimeErrorInfo(
                    code="execution.parent_binding_not_ready", category=ErrorCategory.RESOURCE_LOST,
                    message="shared workspace requires the parent resource lease; use standard Run recovery",
                    retryable=True, safe_to_resume=True,
                ))
            if (request.parent_run_id and policy == WorkspaceSharingPolicy.SHARED_PARENT
                    and parent.configuration is not None
                    and parent.configuration.policy == snapshot.policy
                    and parent.configuration.tool_environment == snapshot.tool_environment):
                handle = await self.sandbox_provider.share_run(
                    request.parent_run_id,
                    request.context,
                    run_id=request.run_id, resume=True,
                )
                workspace = handle.filesystem.row.root
            else:
                handle = await self.sandbox_provider.provision(
                    self.sandbox_spec(
                        workspace=workspace,
                        read_only=effective_read_only, policy=accepted_policy,
                        tool_environment=snapshot.tool_environment,
                    ),
                    request.context,
                    run_id=request.run_id,
                )
            binding = RunExecutionBinding(
                run_id=request.run_id,
                parent_run_id=request.parent_run_id,
                agent_id=request.agent_id,
                workspace_root=workspace.as_posix(),
                workspace_policy=policy,
                sandbox=handle,
                grant_issuer=self.issuer,
                host_workspace=None if effective_read_only else str(workspace),
                diagnostics={
                    "configuration_id": snapshot.configuration_id,
                    "workspace_policy": policy.value,
                    "sandbox": handle.ref.model_dump(mode="json"),
                    "interpreter": snapshot.tool_environment["interpreter"],
                    "runtime_read_paths": snapshot.tool_environment["read_paths"],
                    "capabilities": (await self.sandbox_provider.capabilities()).model_dump(mode="json"),
                },
            )
            binding.lifecycle = getattr(request, "lifecycle", None)
            binding.configuration_id = snapshot.configuration_id
            binding.configuration = snapshot.model_copy(deep=True)
            self.bindings.append(binding)
            return binding

    async def close(self) -> None:
        async with self._lock:
            if self._closed and not self.bindings:
                return
            self._closed = True
            bindings = tuple(reversed(self.bindings))
        results = await asyncio.gather(
            *(binding.close() for binding in bindings),
            return_exceptions=True,
        )
        failed = [binding for binding, result in zip(bindings, results) if isinstance(result, BaseException)]
        async with self._lock:
            # A failed lease remains owned and inspectable. Its shared close
            # future preserves an unknown outcome without replaying side effects.
            self.bindings[:] = failed
        errors = [value for value in results if isinstance(value, BaseException)]
        if errors:
            raise RuntimeError(
                f"{len(errors)} Local execution binding(s) failed to close"
            ) from errors[0]
