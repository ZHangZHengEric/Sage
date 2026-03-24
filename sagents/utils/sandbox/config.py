"""
沙箱配置 - 支持环境变量、YAML文件和代码配置
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from .interface import SandboxType


@dataclass
class MountPath:
    """路径映射配置"""
    host_path: str
    sandbox_path: str
    read_only: bool = False


@dataclass
class SandboxConfig:
    """沙箱配置

    配置优先级（从高到低）：
    1. 代码中显式传入的配置
    2. 环境变量
    3. YAML配置文件
    4. 默认值
    """

    # ===== 核心配置 =====
    mode: SandboxType = SandboxType.LOCAL
    sandbox_id: Optional[str] = None  # 沙箱ID，用于持久化和识别（user_id/agent_id/session_id）

    # ===== 工作区配置 =====
    workspace: str = "."  # 宿主机工作区根目录
    virtual_workspace: str = "/sage-workspace"  # 沙箱内虚拟工作区路径

    # ===== 路径映射配置 =====
    mount_paths: List[MountPath] = field(default_factory=list)  # 额外的路径映射

    # ===== 本地沙箱配置 =====
    cpu_time_limit: int = 300
    memory_limit_mb: int = 4096
    allowed_paths: Optional[List[str]] = None
    linux_isolation_mode: str = "subprocess"
    macos_isolation_mode: str = "subprocess"

    # ===== 远程沙箱配置 =====
    remote_provider: str = "opensandbox"  # 远程沙箱提供者: opensandbox | kubernetes | firecracker | custom
    remote_server_url: Optional[str] = None
    remote_api_key: Optional[str] = None
    remote_image: str = "opensandbox/code-interpreter:v1.0.2"
    remote_timeout: int = 1800
    remote_persistent: bool = True  # 是否持久化沙箱
    remote_sandbox_ttl: int = 3600  # 沙箱存活时间（秒）
    remote_provider_config: Dict[str, Any] = field(default_factory=dict)  # 特定提供者的额外配置

    @classmethod
    def from_env(cls, sandbox_id: Optional[str] = None, workspace: Optional[str] = None, virtual_workspace: Optional[str] = None) -> "SandboxConfig":
        """从环境变量加载配置
        
        Args:
            sandbox_id: 沙箱ID（必填，不允许从环境变量读取）
            workspace: 宿主机工作区路径（必填，不允许从环境变量读取）
            virtual_workspace: 虚拟工作区路径（必填，不允许从环境变量读取）
        """
        # 必填参数检查
        if not sandbox_id:
            raise ValueError("sandbox_id is required and must be provided explicitly")
        if not workspace:
            raise ValueError("workspace is required and must be provided explicitly")
        if not virtual_workspace:
            raise ValueError("virtual_workspace is required and must be provided explicitly")
        
        mode_str = os.environ.get("SAGE_SANDBOX_MODE", "local").lower()
        mode = SandboxType(mode_str)

        # 解析路径映射环境变量
        # 格式: "/host/path1:/sandbox/path1,/host/path2:/sandbox/path2"
        mount_paths = []
        mount_paths_env = os.environ.get("SAGE_SANDBOX_MOUNT_PATHS", "")
        if mount_paths_env:
            for mapping in mount_paths_env.split(","):
                if ":" in mapping:
                    host_path, sandbox_path = mapping.split(":", 1)
                    mount_paths.append(MountPath(
                        host_path=host_path.strip(),
                        sandbox_path=sandbox_path.strip(),
                        read_only=False
                    ))

        return cls(
            mode=mode,
            sandbox_id=sandbox_id,
            workspace=workspace,
            virtual_workspace=virtual_workspace,
            mount_paths=mount_paths,
            # 本地配置
            cpu_time_limit=int(os.environ.get("SAGE_LOCAL_CPU_TIME_LIMIT", "300")),
            memory_limit_mb=int(os.environ.get("SAGE_LOCAL_MEMORY_LIMIT_MB", "4096")),
            linux_isolation_mode=os.environ.get("SAGE_LOCAL_LINUX_ISOLATION", "subprocess"),
            macos_isolation_mode=os.environ.get("SAGE_LOCAL_MACOS_ISOLATION", "subprocess"),
            # 远程配置
            remote_provider=os.environ.get("SAGE_REMOTE_PROVIDER", "opensandbox"),
            remote_server_url=os.environ.get("OPENSANDBOX_URL"),
            remote_api_key=os.environ.get("OPENSANDBOX_API_KEY"),
            remote_image=os.environ.get("OPENSANDBOX_IMAGE", "opensandbox/code-interpreter:v1.0.2"),
            remote_timeout=int(os.environ.get("OPENSANDBOX_TIMEOUT", "1800")),
        )

    @classmethod
    def from_yaml(cls, config_path: str) -> "SandboxConfig":
        """从YAML配置文件加载"""
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required for YAML config. Install with: pip install pyyaml")

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        sandbox_config = config.get('sandbox', {})

        # 解析路径映射
        mount_paths = []
        for mp in sandbox_config.get('mount_paths', []):
            mount_paths.append(MountPath(
                host_path=mp['host_path'],
                sandbox_path=mp['sandbox_path'],
                read_only=mp.get('read_only', False)
            ))

        return cls(
            mode=SandboxType(sandbox_config.get('mode', 'local')),
            sandbox_id=sandbox_config.get('sandbox_id'),
            workspace=sandbox_config.get('workspace', '.'),
            virtual_workspace=sandbox_config.get('virtual_workspace', '/sage-workspace'),
            mount_paths=mount_paths,
            # 本地配置
            cpu_time_limit=sandbox_config.get('local', {}).get('cpu_time_limit', 300),
            memory_limit_mb=sandbox_config.get('local', {}).get('memory_limit_mb', 4096),
            linux_isolation_mode=sandbox_config.get('local', {}).get('linux_isolation_mode', 'subprocess'),
            macos_isolation_mode=sandbox_config.get('local', {}).get('macos_isolation_mode', 'subprocess'),
            # 远程配置
            remote_provider=sandbox_config.get('remote', {}).get('provider', 'opensandbox'),
            remote_server_url=sandbox_config.get('remote', {}).get('server_url'),
            remote_api_key=sandbox_config.get('remote', {}).get('api_key'),
            remote_image=sandbox_config.get('remote', {}).get('image', 'opensandbox/code-interpreter:v1.0.2'),
            remote_timeout=sandbox_config.get('remote', {}).get('timeout', 1800),
            remote_persistent=sandbox_config.get('remote', {}).get('persistent', True),
            remote_sandbox_ttl=sandbox_config.get('remote', {}).get('sandbox_ttl', 3600),
            remote_provider_config=sandbox_config.get('remote', {}).get('provider_config', {}),
        )
