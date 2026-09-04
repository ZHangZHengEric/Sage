"""CLI 宿主端口：为每个真实 Run 绑定本地 workspace 沙箱，并组装 ``SAgent``。

沙箱策略在这里以数据形式给出（策略即数据），``sagents.v2`` 只负责执行和校验；
agent 自身无法选择或降低沙箱类型。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.agent.policy import DefaultToolPolicy
from sagents.v2.model import ModelProvider
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.runtime.execution import (
    ExecutionBindingRequest,
    RunExecutionBinding,
)
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    NetworkPolicy,
    ProcessPolicy,
    ResolvedSandboxSpec,
    SandboxGrantIssuer,
)
from sagents.v2.runtime.execution.sandbox import LocalWorkspaceSandboxProvider

# 与 desktop_v2 的本地 workspace 沙箱保持同一档默认值，行为可对照。
DEFAULT_ALLOWED_EXECUTABLES: tuple[str, ...] = (
    "bash",
    "sh",
    "git",
    "rg",
    "python",
    "python3",
    "pytest",
    "npm",
    "node",
)
DEFAULT_ALLOWED_ENV_NAMES: tuple[str, ...] = ("PATH", "PYTHONPATH")
# 文件 API 拒绝写入这些子路径；本地 provider 无 OS 隔离，不能限制 shell 的文件访问。
# hooks 会被 git 执行，config 决定远端与别名；进程操作仍需独立审批。
DEFAULT_PROTECTED_PATHS: tuple[str, ...] = (".git/hooks", ".git/config")


@dataclass(frozen=True)
class WorkspaceSandboxSettings:
    """CLI 本地 workspace 沙箱的策略参数。"""

    process_enabled: bool = True
    read_only: bool = False
    allowed_executables: tuple[str, ...] = DEFAULT_ALLOWED_EXECUTABLES
    allowed_env_names: tuple[str, ...] = DEFAULT_ALLOWED_ENV_NAMES
    protected_paths: tuple[str, ...] = DEFAULT_PROTECTED_PATHS
    max_wall_time_seconds: float = 300
    max_output_bytes: int = 4 * 1024 * 1024
    max_file_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 4 * 1024 * 1024 * 1024


class LocalWorkspaceBindingProvider:
    """``ExecutionBindingProvider`` 实现：每个 Run 一个绑定到宿主目录的本地沙箱。

    workspace 以宿主真实路径暴露给模型（对齐 Codex 的 in-process 体验），
    allowed_roots 同样限定为该路径。
    """

    def __init__(
        self,
        workspace: str | Path,
        *,
        settings: WorkspaceSandboxSettings | None = None,
        issuer: SandboxGrantIssuer | None = None,
        sandbox_provider: LocalWorkspaceSandboxProvider | None = None,
    ) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError(f"workspace must be a directory: {self.workspace}")
        self.workspace_root = self.workspace.as_posix()
        self.settings = settings or WorkspaceSandboxSettings()
        self.issuer = issuer or SandboxGrantIssuer()
        self.sandbox_provider = sandbox_provider or LocalWorkspaceSandboxProvider(
            self.issuer.verification_key
        )
        self.bindings: list[RunExecutionBinding] = []

    def sandbox_spec(self) -> ResolvedSandboxSpec:
        settings = self.settings
        filesystem = FileSystemPolicy(
            allowed_operations=(
                frozenset({FileOperation.READ, FileOperation.LIST})
                if settings.read_only
                else frozenset(FileOperation)
            ),
            allowed_roots=(self.workspace_root,),
            protected_paths=settings.protected_paths,
            max_file_bytes=settings.max_file_bytes,
            max_total_bytes=settings.max_total_bytes,
        )
        process = ProcessPolicy(
            enabled=settings.process_enabled,
            read_only=settings.read_only,
            allowed_executables=settings.allowed_executables,
            allowed_env_names=settings.allowed_env_names,
            max_wall_time_seconds=settings.max_wall_time_seconds,
            max_output_bytes=settings.max_output_bytes,
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
            {"policy_hash": policy_hash, "workspace_root": self.workspace_root},
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
            lifecycle=request.lifecycle,
        )
        self.bindings.append(binding)
        return binding

    async def close(self) -> None:
        # 沙箱句柄由各 Run 的 binding 自己关闭；provider 本身无进程级资源。
        return None


async def build_cli_application(
    *,
    package: SageManifest,
    session_root: str | Path,
    bindings: LocalWorkspaceBindingProvider,
    model_provider: ModelProvider | None = None,
    tool_policy: DefaultToolPolicy | None = None,
) -> SAgentApplication:
    """用唯一组合根 ``SAgentBuilder`` 构建 CLI 使用的 ``SAgentApplication``。

    ``model_provider`` 仅供测试/脚本化场景注入；生产路径由 manifest 的模型路由决定。
    ``tool_policy`` 是 ``--approval-mode`` 决定的审批策略（见 ``app.cli.v2.approvals``），
    None 时沿用引擎默认。调用方通过 ``application.entrypoint()`` 取 ``SAgent``，
    用 ``application.close()`` 释放全部资源。
    """

    builder = (
        SAgentBuilder()
        .with_defaults(session_root=Path(session_root).expanduser())
        .with_execution_binding_provider(bindings)
    )
    if model_provider is not None:
        builder = builder.with_model_provider(model_provider)
    if tool_policy is not None:
        builder = builder.with_tool_policy(tool_policy)
    return await builder.build(package)
