"""
本地沙箱提供者模块

包含:
- LocalSandboxProvider: 新的统一接口实现
- Sandbox: 旧的沙箱类（保持兼容性）
- SandboxFileSystem: 文件系统映射
- VenvManager: Python 虚拟环境管理
- isolation: 隔离策略（subprocess, bwrap, seatbelt）
"""

from .local import LocalSandboxProvider
from .sandbox import Sandbox
from .filesystem import SandboxFileSystem
from .venv import VenvManager
from . import isolation

__all__ = [
    'LocalSandboxProvider',
    'Sandbox',
    'SandboxFileSystem',
    'VenvManager',
    'isolation',
]
