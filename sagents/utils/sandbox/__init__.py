"""
沙箱模块 - 提供统一的沙箱接口

支持多种沙箱实现:
- 本地沙箱 (Local): 本地进程隔离
- 远程沙箱 (Remote): OpenSandbox、Kubernetes、Firecracker 等
- 直通模式 (Passthrough): 无隔离，直接执行
"""

from .interface import ISandboxHandle, SandboxType, CommandResult, ExecutionResult, FileInfo
from .config import SandboxConfig, MountPath
from .factory import SandboxProviderFactory

from .providers.local import Sandbox, SandboxFileSystem, VenvManager

__all__ = [
    'ISandboxHandle',
    'SandboxType',
    'CommandResult',
    'ExecutionResult',
    'FileInfo',
    'SandboxConfig',
    'MountPath',
    'SandboxProviderFactory',
    'Sandbox',
    'SandboxFileSystem',
    'VenvManager',
]
