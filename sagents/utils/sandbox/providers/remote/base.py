"""
远程沙箱提供者基类
"""

import os
from abc import abstractmethod
from datetime import timedelta
from typing import Dict, List, Optional

from ...interface import ISandboxHandle, SandboxType, CommandResult, ExecutionResult, FileInfo
from ...config import MountPath


class RemoteSandboxProvider(ISandboxHandle):
    """远程沙箱提供者基类"""

    def __init__(
        self,
        sandbox_id: str,
        workspace_mount: Optional[str] = None,
        mount_paths: Optional[List[MountPath]] = None,
        timeout: timedelta = timedelta(minutes=30),
    ):
        self._sandbox_id = sandbox_id
        self.workspace_mount = workspace_mount
        self.mount_paths = mount_paths or []
        self.timeout = timeout
        self._workspace_path = "/sage-workspace"
        self._is_initialized = False

    @property
    def sandbox_type(self) -> SandboxType:
        return SandboxType.REMOTE

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def workspace_path(self) -> str:
        return self._workspace_path

    @property
    def host_workspace_path(self) -> Optional[str]:
        return self.workspace_mount

    @abstractmethod
    async def initialize(self) -> None:
        """初始化远程沙箱"""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """清理沙箱资源（断开连接，不删除沙箱）"""
        pass

    @abstractmethod
    async def kill(self) -> None:
        """强制删除沙箱"""
        pass

    # 远程沙箱文件操作接口
    async def upload_file(self, host_path: str, sandbox_path: str) -> None:
        """
        上传文件到远程沙箱

        Args:
            host_path: 宿主机文件路径
            sandbox_path: 沙箱内目标路径
        """
        raise NotImplementedError("This provider does not support file upload")

    async def download_file(self, sandbox_path: str, host_path: str) -> None:
        """
        从远程沙箱下载文件

        Args:
            sandbox_path: 沙箱内文件路径
            host_path: 宿主机目标路径
        """
        raise NotImplementedError("This provider does not support file download")

    async def sync_directory_to_sandbox(self, host_dir: str, sandbox_dir: str) -> None:
        """
        同步目录到远程沙箱

        Args:
            host_dir: 宿主机目录路径
            sandbox_dir: 沙箱内目标目录
        """
        for root, dirs, files in os.walk(host_dir):
            for file in files:
                host_file = os.path.join(root, file)
                rel_path = os.path.relpath(host_file, host_dir)
                sandbox_file = os.path.join(sandbox_dir, rel_path)
                await self.upload_file(host_file, sandbox_file)

    async def sync_directory_from_sandbox(self, sandbox_dir: str, host_dir: str) -> None:
        """
        从远程沙箱同步目录

        Args:
            sandbox_dir: 沙箱内目录路径
            host_dir: 宿主机目标目录
        """
        # 子类可以实现更高效的批量下载
        raise NotImplementedError("This provider does not support directory sync")

    def to_host_path(self, virtual_path: str) -> str:
        """虚拟路径转宿主机路径"""
        if virtual_path.startswith(self._workspace_path):
            rel_path = virtual_path[len(self._workspace_path):].lstrip("/")
            return os.path.join(self.workspace_mount, rel_path) if self.workspace_mount else virtual_path
        return virtual_path

    def to_virtual_path(self, host_path: str) -> str:
        """宿主机路径转虚拟路径"""
        if self.workspace_mount and host_path.startswith(self.workspace_mount):
            rel_path = host_path[len(self.workspace_mount):].lstrip("/")
            return os.path.join(self._workspace_path, rel_path)
        return host_path
