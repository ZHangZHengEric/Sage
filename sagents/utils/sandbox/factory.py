"""
沙箱工厂 - 统一创建沙箱实例

支持多种远程沙箱提供者，通过配置选择:
- opensandbox: OpenSandbox (默认)
- kubernetes: Kubernetes Pod
- firecracker: Firecracker MicroVM
- custom: 自定义提供者
"""

from datetime import timedelta
from typing import Dict, Optional, Type

from .interface import ISandboxHandle, SandboxType
from .config import SandboxConfig


class SandboxProviderFactory:
    """
    沙箱工厂 - 统一创建沙箱实例
    """

    # 本地和直通模式提供者
    _providers: Dict[SandboxType, Type[ISandboxHandle]] = {}

    # 远程沙箱提供者映射
    _remote_providers: Dict[str, Optional[Type[ISandboxHandle]]] = {
        "opensandbox": None,
        "kubernetes": None,
        "firecracker": None,
    }

    @classmethod
    def _get_remote_provider(cls, provider_name: str) -> Type[ISandboxHandle]:
        """获取远程沙箱提供者类（延迟导入）"""
        if provider_name not in cls._remote_providers:
            raise ValueError(f"Unknown remote provider: {provider_name}")

        if cls._remote_providers[provider_name] is None:
            # 延迟导入
            if provider_name == "opensandbox":
                from .providers.remote.opensandbox import OpenSandboxProvider

                cls._remote_providers[provider_name] = OpenSandboxProvider
            elif provider_name == "kubernetes":
                from .providers.remote.kubernetes import KubernetesSandboxProvider

                cls._remote_providers[provider_name] = KubernetesSandboxProvider
            elif provider_name == "firecracker":
                from .providers.remote.firecracker import FirecrackerSandboxProvider

                cls._remote_providers[provider_name] = FirecrackerSandboxProvider

        return cls._remote_providers[provider_name]

    @classmethod
    def _get_local_provider(cls) -> Type[ISandboxHandle]:
        """获取本地沙箱提供者（延迟导入）"""
        if SandboxType.LOCAL not in cls._providers:
            from .providers.local.local import LocalSandboxProvider

            cls._providers[SandboxType.LOCAL] = LocalSandboxProvider
        return cls._providers[SandboxType.LOCAL]

    @classmethod
    def _get_passthrough_provider(cls) -> Type[ISandboxHandle]:
        """获取直通模式提供者（延迟导入）"""
        if SandboxType.PASSTHROUGH not in cls._providers:
            from .providers.passthrough.passthrough import PassthroughSandboxProvider

            cls._providers[SandboxType.PASSTHROUGH] = PassthroughSandboxProvider
        return cls._providers[SandboxType.PASSTHROUGH]

    @classmethod
    async def create(cls, config: Optional[SandboxConfig] = None) -> ISandboxHandle:
        """
        创建沙箱实例

        Usage:
            # local 模式 - 需要 volume_mounts 包含 sandbox_agent_workspace
            config = SandboxConfig(
                mode=SandboxType.LOCAL,
                sandbox_id="agent-001",
                volume_mounts=[
                    VolumeMount("/tmp/agent_001", "/workspace"),
                    VolumeMount("/shared/data", "/data"),
                ]
            )
            sandbox = SandboxProviderFactory.create(config)

            # remote 模式 - 只需要 sandbox_id
            config = SandboxConfig(
                mode=SandboxType.REMOTE,
                sandbox_id="opensandbox-abc123",
                remote_provider="opensandbox",
                remote_server_url="https://...",
            )
            sandbox = SandboxProviderFactory.create(config)
        """
        if config is None:
            raise ValueError("config is required")

        # 确保有沙箱ID
        sandbox_id = config.sandbox_id
        if not sandbox_id:
            raise ValueError("sandbox_id is required in config")

        # 根据模式创建对应实例
        if config.mode == SandboxType.LOCAL:
            provider_class = cls._get_local_provider()
            if not config.sandbox_agent_workspace:
                raise ValueError("sandbox_agent_workspace is required for local sandbox")
            return provider_class(
                sandbox_id=sandbox_id,
                sandbox_agent_workspace=config.sandbox_agent_workspace,
                volume_mounts=config.volume_mounts,
                cpu_time_limit=config.cpu_time_limit,
                memory_limit_mb=config.memory_limit_mb,
                allowed_paths=config.allowed_paths,
                linux_isolation_mode=config.linux_isolation_mode,
                macos_isolation_mode=config.macos_isolation_mode,
            )

        elif config.mode == SandboxType.REMOTE:
            # 根据 remote_provider 选择具体的远程沙箱实现
            provider_class = cls._get_remote_provider(config.remote_provider)
            provider_config = dict(config.remote_provider_config)

            # 构建通用参数
            common_kwargs = {
                "sandbox_id": sandbox_id,
                "workspace_mount": provider_config.pop("workspace_mount", None),
                "mount_paths": config.volume_mounts,
                "virtual_workspace": config.sandbox_agent_workspace or "/sage-workspace",
                "timeout": timedelta(seconds=config.remote_timeout),
            }

            # 根据提供者类型添加特定参数
            if config.remote_provider == "opensandbox":
                if not config.remote_server_url:
                    raise ValueError("OpenSandbox requires server_url")
                return provider_class(
                    **common_kwargs,
                    server_url=config.remote_server_url,
                    api_key=config.remote_api_key,
                    image=config.remote_image,
                    persistent=config.remote_persistent,
                    sandbox_ttl=config.remote_sandbox_ttl,
                    **provider_config
                )

            elif config.remote_provider == "kubernetes":
                return provider_class(
                    **common_kwargs,
                    namespace=provider_config.get("namespace", "default"),
                    image=config.remote_image,
                    resources=provider_config.get("resources", {}),
                    **{
                        k: v
                        for k, v in provider_config.items()
                        if k not in ["namespace", "resources"]
                    }
                )

            elif config.remote_provider == "firecracker":
                return provider_class(
                    **common_kwargs,
                    microvm_config=provider_config.get("microvm_config", {}),
                    **{
                        k: v
                        for k, v in provider_config.items()
                        if k != "microvm_config"
                    }
                )

            else:
                # 自定义提供者，传递所有配置
                return provider_class(**common_kwargs, **provider_config)

        else:  # PASSTHROUGH
            provider_class = cls._get_passthrough_provider()
            if not config.sandbox_agent_workspace:
                raise ValueError("sandbox_agent_workspace is required for passthrough sandbox")
            return provider_class(
                sandbox_id=sandbox_id,
                sandbox_agent_workspace=config.sandbox_agent_workspace,
                volume_mounts=config.volume_mounts,
            )

    @classmethod
    def register_local_provider(cls, mode: SandboxType, provider_class: Type[ISandboxHandle]):
        """注册本地/直通模式提供者"""
        cls._providers[mode] = provider_class

    @classmethod
    def register_remote_provider(cls, name: str, provider_class: Type[ISandboxHandle]):
        """注册远程沙箱提供者

        Args:
            name: 提供者名称，如 "opensandbox", "kubernetes"
            provider_class: 提供者类，必须继承 RemoteSandboxProvider
        """
        cls._remote_providers[name] = provider_class
