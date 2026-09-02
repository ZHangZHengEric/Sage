"""Desktop host binding: per-Run local workspace sandbox and grant issuer."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from sagents.v2.agent.multi_agent import WorkspaceSharingPolicy
from sagents.v2.runtime.execution import (
    ExecutionBindingRequest,
    RunExecutionBinding,
)
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    LocalWorkspaceSandboxProvider,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)

DEFAULT_ALLOWED_EXECUTABLES: tuple[str, ...] = (
    "git",
    "rg",
    "python",
    "python3",
    "pytest",
    "flutter",
    "dart",
    "npm",
    "node",
    "bash",
    "sh",
)
DEFAULT_ALLOWED_ENV_NAMES: tuple[str, ...] = ("PATH", "PYTHONPATH")


class DesktopExecutionBindingProvider:
    """``ExecutionBindingProvider`` for Desktop's local-workspace sandbox."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        issuer: SandboxGrantIssuer | None = None,
        sandbox_provider: LocalWorkspaceSandboxProvider | None = None,
        private_workspace_root: str | Path | None = None,
        read_only: bool = False,
        process_enabled: bool = True,
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
            self.issuer.verification_key
        )
        self.read_only = read_only
        self.process_enabled = process_enabled
        self.bindings: list[RunExecutionBinding] = []
        self._lock = asyncio.Lock()
        self._closed = False

    def sandbox_spec(
        self,
        *,
        workspace: Path | None = None,
        read_only: bool | None = None,
    ) -> ResolvedSandboxSpec:
        resolved_workspace = (workspace or self.workspace).resolve()
        effective_read_only = self.read_only if read_only is None else read_only
        filesystem = FileSystemPolicy(
            allowed_operations=(
                frozenset({FileOperation.READ, FileOperation.LIST})
                if effective_read_only
                else frozenset(FileOperation)
            ),
            allowed_roots=(resolved_workspace.as_posix(),),
            max_file_bytes=64 * 1024 * 1024,
            max_total_bytes=4 * 1024 * 1024 * 1024,
        )
        process = ProcessPolicy(
            enabled=self.process_enabled and not effective_read_only,
            read_only=effective_read_only,
            allowed_executables=DEFAULT_ALLOWED_EXECUTABLES,
            allowed_env_names=DEFAULT_ALLOWED_ENV_NAMES,
            max_wall_time_seconds=300,
            max_output_bytes=4 * 1024 * 1024,
        )
        network = NetworkPolicy()
        policy_source = json.dumps(
            {
                "filesystem": filesystem.model_dump(mode="json"),
                "process": process.model_dump(mode="json"),
                "network": network.model_dump(mode="json"),
            },
            sort_keys=True,
        )
        policy_hash = f"sha256:{hashlib.sha256(policy_source.encode()).hexdigest()}"
        spec_source = json.dumps(
            {
                "policy_hash": policy_hash,
                "workspace_root": resolved_workspace.as_posix(),
                "host_workspace": str(resolved_workspace),
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
            policy_hash=policy_hash,
            metadata={"host_workspace": str(resolved_workspace)},
        )

    async def acquire(self, request: ExecutionBindingRequest) -> RunExecutionBinding:
        policy = WorkspaceSharingPolicy(
            str(getattr(request.workspace_policy, "value", request.workspace_policy))
        )
        workspace = self.workspace
        if policy == WorkspaceSharingPolicy.PRIVATE_CHILD:
            digest = hashlib.sha256(request.run_id.encode()).hexdigest()[:24]
            workspace = self.private_workspace_root / digest
        effective_read_only = (
            self.read_only or policy == WorkspaceSharingPolicy.READ_ONLY_PARENT
        )
        async with self._lock:
            if self._closed:
                raise RuntimeError("Desktop execution binding provider is closed")
            if policy == WorkspaceSharingPolicy.PRIVATE_CHILD:
                workspace.mkdir(parents=True, exist_ok=True)
            self.bindings = [value for value in self.bindings if not value.closed]
            handle = await self.sandbox_provider.provision(
                self.sandbox_spec(
                    workspace=workspace,
                    read_only=effective_read_only,
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
            )
            binding.lifecycle = getattr(request, "lifecycle", None)
            self.bindings.append(binding)
            return binding

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            bindings = tuple(reversed(self.bindings))
            self.bindings.clear()
        results = await asyncio.gather(
            *(binding.close() for binding in bindings),
            return_exceptions=True,
        )
        errors = [value for value in results if isinstance(value, BaseException)]
        if errors:
            raise RuntimeError(
                f"{len(errors)} Desktop execution binding(s) failed to close"
            ) from errors[0]
