"""
沙箱配置 - 支持环境变量、YAML文件和代码配置
"""

import os
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from .interface import SandboxType


@dataclass
class VolumeMount:
    """卷挂载配置（类似 docker -v）
    
    Examples:
        VolumeMount(host_path="/shared/data", mount_path="/data")
        VolumeMount(host_path="/assets", mount_path="/assets")
    """
    host_path: str       # 宿主机源路径
    mount_path: str      # 沙箱内挂载路径（绝对路径）
    read_only: bool = False
    
    def __post_init__(self):
        # 确保路径是绝对路径
        self.host_path = os.path.abspath(self.host_path)
        if os.name == "nt" and os.path.isabs(self.mount_path):
            self.mount_path = os.path.abspath(self.mount_path)
        elif not self.mount_path.startswith('/'):
            self.mount_path = '/' + self.mount_path

    @property
    def sandbox_path(self) -> str:
        """兼容远程沙箱实现中使用的字段名。"""
        return self.mount_path

    @sandbox_path.setter
    def sandbox_path(self, value: str) -> None:
        if os.name == "nt" and os.path.isabs(value):
            self.mount_path = os.path.abspath(value)
        else:
            self.mount_path = value if value.startswith("/") else f"/{value}"


# 向后兼容别名
MountPath = VolumeMount


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
    sandbox_id: Optional[str] = None  # 沙箱ID，用于持久化和识别

    # ===== 工作区配置 =====
    # sandbox_agent_workspace: 沙箱内虚拟工作区路径（所有模式都需要）
    # volume_mounts: 额外的目录挂载（宿主机路径 -> 沙箱内路径，可选）
    sandbox_agent_workspace: Optional[str] = None  # 沙箱内虚拟工作区路径
    volume_mounts: List[VolumeMount] = field(default_factory=list)  # 额外卷挂载

    # ===== 本地沙箱配置 =====
    cpu_time_limit: int = 300
    memory_limit_mb: int = 4096
    allowed_paths: Optional[List[str]] = None
    linux_isolation_mode: str = "bwrap"
    macos_isolation_mode: str = "seatbelt"

    # ===== 远程沙箱配置 =====
    remote_provider: str = "opensandbox"
    remote_server_url: Optional[str] = None
    remote_api_key: Optional[str] = None
    remote_image: str = "opensandbox/code-interpreter:v1.0.2"
    remote_timeout: int = 1800
    remote_persistent: bool = True
    remote_sandbox_ttl: int = 3600
    remote_provider_config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    async def from_env(cls, sandbox_id: Optional[str] = None) -> "SandboxConfig":
        """从环境变量加载配置

        Args:
            sandbox_id: 沙箱ID（必填）
        """
        if not sandbox_id:
            raise ValueError("sandbox_id is required and must be provided explicitly")

        mode_str = os.environ.get("SAGE_SANDBOX_MODE", "local").lower()
        mode = SandboxType(mode_str)

        # 解析路径映射环境变量
        # 格式: "/host/path1:/sandbox/path1,/host/path2:/sandbox/path2"
        volume_mounts = []
        mount_paths_env = os.environ.get("SAGE_SANDBOX_MOUNT_PATHS", "")
        if mount_paths_env:
            for mapping in mount_paths_env.split(","):
                if ":" in mapping:
                    host_path, sandbox_path = mapping.split(":", 1)
                    volume_mounts.append(VolumeMount(
                        host_path=host_path.strip(),
                        mount_path=sandbox_path.strip()
                    ))

        return cls(
            mode=mode,
            sandbox_id=sandbox_id,
            volume_mounts=volume_mounts,
            # 本地配置
            cpu_time_limit=int(os.environ.get("SAGE_LOCAL_CPU_TIME_LIMIT", "300")),
            memory_limit_mb=int(os.environ.get("SAGE_LOCAL_MEMORY_LIMIT_MB", "4096")),
            linux_isolation_mode=os.environ.get("SAGE_LOCAL_LINUX_ISOLATION", "bwrap"),
            macos_isolation_mode=os.environ.get("SAGE_LOCAL_MACOS_ISOLATION", "seatbelt"),
            # 远程配置
            remote_provider=os.environ.get("SAGE_REMOTE_PROVIDER", "opensandbox"),
            remote_server_url=os.environ.get("OPENSANDBOX_URL"),
            remote_api_key=os.environ.get("OPENSANDBOX_API_KEY"),
            remote_image=os.environ.get("OPENSANDBOX_IMAGE", "opensandbox/code-interpreter:v1.0.2"),
            remote_timeout=int(os.environ.get("OPENSANDBOX_TIMEOUT", "1800")),
        )

    @classmethod
    async def from_yaml(cls, config_path: str) -> "SandboxConfig":
        """从YAML配置文件加载"""
        try:
            import yaml
        except ImportError:
            raise ImportError("PyYAML is required for YAML config. Install with: pip install pyyaml")

        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)

        sandbox_config = config.get('sandbox', {})

        # 解析路径映射
        volume_mounts = []
        for mp in sandbox_config.get('volume_mounts', []):
            volume_mounts.append(VolumeMount(
                host_path=mp['host_path'],
                mount_path=mp['mount_path']
            ))

        return cls(
            mode=SandboxType(sandbox_config.get('mode', 'local')),
            sandbox_id=sandbox_config.get('sandbox_id'),
            volume_mounts=volume_mounts,
            # 本地配置
            cpu_time_limit=sandbox_config.get('local', {}).get('cpu_time_limit', 300),
            memory_limit_mb=sandbox_config.get('local', {}).get('memory_limit_mb', 4096),
            linux_isolation_mode=sandbox_config.get('local', {}).get('linux_isolation_mode', 'bwrap'),
            macos_isolation_mode=sandbox_config.get('local', {}).get('macos_isolation_mode', 'seatbelt'),
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
