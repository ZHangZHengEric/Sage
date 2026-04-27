"""
远程沙箱提供者基类
"""

import asyncio
import fnmatch
import os
from abc import abstractmethod
from datetime import timedelta
from typing import Dict, List, Optional

from ...interface import ISandboxHandle, SandboxType, CommandResult, ExecutionResult, FileInfo
from ...config import MountPath


def _host_path_state_sync(path: str) -> str:
    if not os.path.exists(path):
        return "missing"
    if os.path.isdir(path):
        return "dir"
    return "file"


def _walk_upload_files_sync(
    host_dir: str,
    sandbox_dir: str,
    ignore_patterns: Optional[List[str]] = None,
) -> List[tuple[str, str]]:
    ignore_patterns = ignore_patterns or []
    upload_files: List[tuple[str, str]] = []

    for root, dirs, files in os.walk(host_dir):
        if ignore_patterns:
            dirs[:] = [
                d for d in dirs
                if not any(fnmatch.fnmatch(d, pattern) for pattern in ignore_patterns)
            ]
        for file_name in files:
            if any(fnmatch.fnmatch(file_name, pattern) for pattern in ignore_patterns):
                continue
            host_file = os.path.join(root, file_name)
            rel_path = os.path.relpath(host_file, host_dir)
            sandbox_file = os.path.join(sandbox_dir, rel_path)
            upload_files.append((host_file, sandbox_file))

    return upload_files


class RemoteSandboxProvider(ISandboxHandle):
    """远程沙箱提供者基类"""

    def __init__(
        self,
        sandbox_id: str,
        workspace_mount: Optional[str] = None,
        mount_paths: Optional[List[MountPath]] = None,
        virtual_workspace: str = "/sage-workspace",
        timeout: timedelta = timedelta(minutes=30),
    ):
        self._sandbox_id = sandbox_id
        self.workspace_mount = os.path.abspath(workspace_mount) if workspace_mount else None
        self.mount_paths = list(mount_paths or [])
        self._volume_mounts = list(self.mount_paths)
        self.timeout = timeout
        self._workspace_path = virtual_workspace or "/sage-workspace"
        self._is_initialized = False
        self._allowed_paths: List[str] = []
        if self.workspace_mount:
            self._allowed_paths.append(self.workspace_mount)
        self._allowed_paths.extend(mp.host_path for mp in self.mount_paths)

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

    @property
    def volume_mounts(self) -> List[MountPath]:
        """返回额外的卷挂载配置列表。"""
        return self._volume_mounts

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

    def add_allowed_paths(self, paths: List[str]) -> None:
        """记录允许访问的宿主机路径。"""
        for path in paths:
            if path not in self._allowed_paths:
                self._allowed_paths.append(path)

    def remove_allowed_paths(self, paths: List[str]) -> None:
        """移除允许访问的宿主机路径。"""
        self._allowed_paths = [path for path in self._allowed_paths if path not in paths]

    def get_allowed_paths(self) -> List[str]:
        """获取当前允许访问的宿主机路径列表。"""
        return list(self._allowed_paths)

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
        upload_files = await asyncio.to_thread(
            _walk_upload_files_sync,
            host_dir,
            sandbox_dir,
        )
        for host_file, sandbox_file in upload_files:
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

    async def copy_from_host(
        self,
        host_source_path: str,
        sandbox_dest_path: str,
        ignore_patterns: Optional[List[str]] = None
    ) -> bool:
        """
        从宿主机复制文件/目录到远程沙箱。
        """
        path_state = await asyncio.to_thread(_host_path_state_sync, host_source_path)
        if path_state == "missing":
            return False

        ignore_patterns = ignore_patterns or []

        if path_state == "dir":
            upload_files = await asyncio.to_thread(
                _walk_upload_files_sync,
                host_source_path,
                sandbox_dest_path,
                ignore_patterns,
            )
            for source_file, target_file in upload_files:
                await self.upload_file(source_file, target_file)
            return True

        await self.upload_file(host_source_path, sandbox_dest_path)
        return True

    async def get_file_tree(
        self,
        root_path: Optional[str] = None,
        include_hidden: bool = False,
        max_depth: Optional[int] = None,
        max_items_per_dir: int = 5
    ) -> str:
        """
        基于 list_directory 生成紧凑文件树。
        """
        root = root_path or self.workspace_path
        root_name = os.path.basename(root.rstrip("/")) or "workspace"
        lines = [f"{root_name}/"]

        async def walk(path: str, depth: int, indent: str) -> None:
            if max_depth is not None and depth >= max_depth:
                return

            entries = await self.list_directory(path, include_hidden=include_hidden)
            entries.sort(key=lambda entry: (not entry.is_dir, os.path.basename(entry.path)))

            if depth > 0 and len(entries) > max_items_per_dir:
                shown_entries = entries[:max_items_per_dir]
                hidden_count = len(entries) - max_items_per_dir
            else:
                shown_entries = entries
                hidden_count = 0

            for entry in shown_entries:
                name = os.path.basename(entry.path.rstrip("/"))
                suffix = "/" if entry.is_dir else ""
                lines.append(f"{indent}  {name}{suffix}")
                if entry.is_dir:
                    await walk(entry.path, depth + 1, indent + "  ")

            if hidden_count > 0:
                lines.append(f"{indent}  ... (and {hidden_count} more items)")

        await walk(root, 0, "")
        return "\n".join(lines)

    def _iter_virtual_mappings(self) -> List[tuple[str, str]]:
        mappings: List[tuple[str, str]] = []
        if self.workspace_mount:
            mappings.append((self._workspace_path.rstrip("/") or "/", self.workspace_mount))
        for mount in self.mount_paths:
            mappings.append((mount.mount_path.rstrip("/") or "/", mount.host_path))
        return sorted(mappings, key=lambda item: len(item[0]), reverse=True)

    def _iter_host_mappings(self) -> List[tuple[str, str]]:
        host_first = [(host, virtual) for virtual, host in self._iter_virtual_mappings()]
        return sorted(host_first, key=lambda item: len(item[0]), reverse=True)

    def to_host_path(self, virtual_path: str) -> str:
        """虚拟路径转宿主机路径"""
        for virtual_root, host_root in self._iter_virtual_mappings():
            if virtual_path == virtual_root:
                return host_root
            if virtual_path.startswith(virtual_root + "/"):
                rel_path = virtual_path[len(virtual_root):].lstrip("/")
                return os.path.join(host_root, rel_path)
        return virtual_path

    def to_virtual_path(self, host_path: str) -> str:
        """宿主机路径转虚拟路径"""
        normalized_host = os.path.abspath(host_path)
        for host_root, virtual_root in self._iter_host_mappings():
            if normalized_host == host_root:
                return virtual_root
            if normalized_host.startswith(host_root + os.sep):
                rel_path = normalized_host[len(host_root):].lstrip("/")
                return os.path.join(virtual_root, rel_path)
        return host_path
