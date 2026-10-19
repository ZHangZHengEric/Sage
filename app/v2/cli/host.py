"""CLI 宿主端口：为每个真实 Run 绑定本地 workspace 沙箱，并组装 ``SAgent``。

沙箱策略在这里以数据形式给出（策略即数据），``sagents.v2`` 只负责执行和校验；
agent 自身无法选择或降低沙箱类型。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from sagents.v2 import SAgentApplication, SAgentBuilder
from sagents.v2.agent.policy import DefaultToolPolicy
from sagents.v2.model import ModelProvider
from sagents.v2.package.manifest.root import SageManifest
from sagents.v2.runtime.execution import (
    LocalExecutionPolicy, LocalWorkspaceExecutionBindingProvider,
)
from sagents.v2.runtime.execution.sandbox import (
    FileOperation,
    FileSystemPolicy,
    NetworkMode,
    NetworkPolicy,
    ProcessPolicy,
    ResourceLimits,
)
from sagents.v2.runtime.execution.sandbox.read_only_shell import (
    READ_ONLY_SHELL_EXECUTABLES,
)

from app.v2.cli.approvals import WorkspaceApprovalMemory

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
# 保护 hooks 与 config；配置受保护子路径时，沙箱拒绝可写进程请求。
DEFAULT_PROTECTED_PATHS: tuple[str, ...] = (".git/hooks", ".git/config")


@dataclass(frozen=True)
class WorkspaceSandboxSettings:
    """CLI 本地 workspace 沙箱的策略参数。"""

    # 内核硬限制来自管理员委派的 cgroup 子树与 XFS project 挂载，由宿主配置
    # 交给 provider。CLI 不接受这份配置，所以不声称自己拥有这些限制；沙箱
    # 仍然隔离，只是按采样计量。
    resources: ResourceLimits = field(
        default_factory=lambda: ResourceLimits(require_hard_limits=False)
    )
    network_mode: str = "none"
    network_hosts: tuple[str, ...] = ()
    network_ports: tuple[int, ...] = ()
    network_proxy: str | None = None
    network_allow_private: bool = False
    process_enabled: bool = True
    read_only: bool = False
    allowed_executables: tuple[str, ...] = DEFAULT_ALLOWED_EXECUTABLES
    allowed_env_names: tuple[str, ...] = DEFAULT_ALLOWED_ENV_NAMES
    protected_paths: tuple[str, ...] = DEFAULT_PROTECTED_PATHS
    max_wall_time_seconds: float = 300
    max_output_bytes: int = 4 * 1024 * 1024
    max_file_bytes: int = 64 * 1024 * 1024
    # Omitted filesystem quotas follow the configured resource budget. Hosts
    # can still explicitly impose a narrower filesystem limit.
    max_total_bytes: int | None = None


class LocalWorkspaceBindingProvider(LocalWorkspaceExecutionBindingProvider):
    """Translate CLI policy data into the standard SDK local binding."""

    def __init__(self, workspace, *, settings=None, issuer=None, sandbox_provider=None):
        workspace = Path(workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError(f"workspace must be a directory: {workspace}")
        self.settings = settings or WorkspaceSandboxSettings()
        settings = self.settings
        filesystem = FileSystemPolicy(
            allowed_operations=(
                frozenset({FileOperation.READ, FileOperation.LIST})
                if settings.read_only
                else frozenset(FileOperation)
            ),
            protected_paths=settings.protected_paths,
            max_file_bytes=settings.max_file_bytes,
            max_total_bytes=(
                settings.max_total_bytes
                if settings.max_total_bytes is not None
                else settings.resources.disk_mb * 1024**2
            ),
        )
        # 只读（plan）模式下进程只能在 OS 只读沙箱内跑受限检查语法：
        # 白名单换成该语法能启动的命令，bash/python 等一概不在其中。
        allowed_executables = (
            tuple(sorted(READ_ONLY_SHELL_EXECUTABLES))
            if settings.read_only
            else settings.allowed_executables
        )
        process = ProcessPolicy(
            enabled=settings.process_enabled,
            allow_shell=True,
            read_only=settings.read_only,
            allowed_executables=allowed_executables,
            allowed_env_names=settings.allowed_env_names,
            max_wall_time_seconds=settings.max_wall_time_seconds,
            max_output_bytes=settings.max_output_bytes,
        )
        mode = NetworkMode(settings.network_mode)
        options = {"mode": mode}
        if mode in {NetworkMode.ALLOWLIST, NetworkMode.PROXY}:
            options.update(
                allowed_hosts=settings.network_hosts,
                allowed_ports=settings.network_ports,
                proxy_url=settings.network_proxy,
                deny_private_networks=not settings.network_allow_private,
                allowed_schemes=("http", "https"),
            )
        elif (
            settings.network_hosts
            or settings.network_ports
            or settings.network_proxy
            or settings.network_allow_private
        ):
            raise ValueError(
                "network host/port/proxy/private settings require allowlist or proxy mode"
            )
        elif mode == NetworkMode.UNRESTRICTED:
            options["deny_private_networks"] = False
        network = NetworkPolicy.model_validate(options)
        from sagents.v2.runtime.execution.sandbox.local_support.network import (
            validate_shell_network,
        )

        validate_shell_network(network)
        super().__init__(workspace, issuer=issuer, sandbox_provider=sandbox_provider,
            policy=LocalExecutionPolicy(filesystem=filesystem, process=process,
                                        network=network, resources=settings.resources))


async def build_cli_application(
    *,
    package: SageManifest,
    models=None,
    session_root: str | Path,
    bindings: LocalWorkspaceBindingProvider,
    model_provider: ModelProvider | None = None,
    tool_policy: DefaultToolPolicy | None = None,
    approval_store: str | Path | None = None,
) -> SAgentApplication:
    """用唯一组合根 ``SAgentBuilder`` 构建 CLI 使用的 ``SAgentApplication``。

    ``model_provider`` 仅供测试/脚本化场景注入；生产路径由 App models 配置与 Agent 的模型 ID 决定。
    ``tool_policy`` 是 ``--approval-mode`` 决定的审批策略（见 ``app.v2.cli.approvals``），
    None 时沿用引擎默认。审批记忆在 Kernel 的 session 作用域之上叠加 ``workspace``
    作用域，文件放在 ``approval_store``（默认 ``session_root/approvals``，宿主目录、
    不进用户仓库）下、按 ``bindings.workspace`` 分文件。调用方通过
    ``application.loaded_agents`` 获取已加载版本，显式传给 entrypoint；
    用 ``application.close()`` 释放全部资源。
    """

    from sagents.v2.agent.policy import SessionApprovalMemory
    from sagents.v2.composition.defaults import default_runtime
    from sagents.v2.package.manifest.runtime import CapabilitySelection, merge_capability_selections
    from sagents.v2.runtime.extensions import (
        CapabilityOffer, ExtensionDependency, ExtensionDescriptor, ExtensionRegistration, ExtensionScope,
    )
    builder = SAgentBuilder()
    choices = {}
    for capability, value in (
        ("execution.binding", bindings), ("model.provider", model_provider),
        ("agent.tool-policy", tool_policy),
    ):
        if value is None:
            continue
        plugin_id = "com.sage.cli." + capability.replace(".", "-")
        builder.register(ExtensionRegistration(
            descriptor=ExtensionDescriptor(
                plugin_id=plugin_id, name=capability, version="2.0.0",
                provides=(CapabilityOffer(capability=capability, api_version="2"),),
                supported_scopes=frozenset({ExtensionScope.PROCESS}),
                config_schema={"type": "object", "additionalProperties": False},
            ), factory=lambda context, deps, value=value: value, ownership="borrowed",
        ))
        choices[capability] = CapabilitySelection(plugin=plugin_id, scope=ExtensionScope.PROCESS)
    store_root = (
        Path(approval_store).expanduser()
        if approval_store is not None
        else Path(session_root).expanduser() / "approvals"
    )
    builder.register(ExtensionRegistration(
        descriptor=ExtensionDescriptor(
            plugin_id="com.sage.cli.approval-memory.workspace", name="Workspace approvals", version="2.0.0",
            provides=(CapabilityOffer(capability="agent.approval-memory", api_version="2"),),
            dependencies=(ExtensionDependency(capability="derived-state.store"),),
            supported_scopes=frozenset({ExtensionScope.PROCESS}),
            config_schema={"type": "object", "properties": {
                "store_root": {"type": "string"}, "workspace": {"type": "string"},
            }, "required": ["store_root", "workspace"], "additionalProperties": False},
        ), factory=lambda context, deps: WorkspaceApprovalMemory(
            SessionApprovalMemory(deps.require("derived-state.store")),
            store_root=Path(context.config["store_root"]), workspace=Path(context.config["workspace"]),
        ),
    ))
    choices["derived-state.store"] = CapabilitySelection(plugin="sage.derived-state.session")
    choices["agent.approval-memory"] = CapabilitySelection(
        plugin="com.sage.cli.approval-memory.workspace",
        config={"store_root": str(store_root.resolve()), "workspace": str(bindings.workspace)},
    )
    defaults = default_runtime(session_root)
    effective = package.runtime.model_copy(update={"state_root": str(Path(session_root).expanduser().resolve()), "capabilities": {
        **merge_capability_selections({"session.store": defaults.capabilities["session.store"]},
                                      package.runtime.capabilities), **choices,
    }})
    application = await builder.build(runtime=effective, models=models)
    try:
        from app.v2.cli.package import builtin_dependencies
        loaded = {}
        async def load(manifest):
            children = {}
            for name, child in builtin_dependencies(manifest).items():
                children[name] = loaded.get(child.metadata.id) or await load(child)
            handle = await application.load_agent(manifest, subagents=children)
            loaded[manifest.metadata.id] = handle
            return handle
        await load(package)
    except BaseException:
        await application.close()
        raise
    return application
