"""Desktop host binding: per-Run local workspace sandbox and grant issuer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
        read_only: bool = False,
        process_enabled: bool = True,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.workspace_root = self.workspace.as_posix()
        self.issuer = issuer or SandboxGrantIssuer()
        self.sandbox_provider = sandbox_provider or LocalWorkspaceSandboxProvider(
            self.issuer.verification_key
        )
        self.read_only = read_only
        self.process_enabled = process_enabled
        self.bindings: list[RunExecutionBinding] = []

    def sandbox_spec(self) -> ResolvedSandboxSpec:
        filesystem = FileSystemPolicy(
            allowed_operations=(
                frozenset({FileOperation.READ, FileOperation.LIST})
                if self.read_only
                else frozenset(FileOperation)
            ),
            allowed_roots=(self.workspace_root,),
            max_file_bytes=64 * 1024 * 1024,
            max_total_bytes=4 * 1024 * 1024 * 1024,
        )
        process = ProcessPolicy(
            enabled=self.process_enabled and not self.read_only,
            read_only=self.read_only,
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
                "workspace_root": self.workspace_root,
                "host_workspace": str(self.workspace),
            },
            sort_keys=True,
        )
        spec_hash = f"sha256:{hashlib.sha256(spec_source.encode()).hexdigest()}"
        return ResolvedSandboxSpec(
            spec_hash=spec_hash,
            workspace_root=self.workspace_root,
            architecture="native",
            filesystem=filesystem,
            process=process,
            network=network,
            policy_hash=policy_hash,
            metadata={"host_workspace": str(self.workspace)},
        )

    async def acquire(self, request: ExecutionBindingRequest) -> RunExecutionBinding:
        handle = await self.sandbox_provider.provision(
            self.sandbox_spec(), request.context, run_id=request.run_id
        )
        binding = RunExecutionBinding(
            run_id=request.run_id,
            parent_run_id=request.parent_run_id,
            agent_id=request.agent_id,
            workspace_root=self.workspace_root,
            workspace_policy=request.workspace_policy,
            sandbox=handle,
            grant_issuer=self.issuer,
        )
        binding.lifecycle = getattr(request, "lifecycle", None)
        self.bindings.append(binding)
        return binding

    async def close(self) -> None:
        return None
