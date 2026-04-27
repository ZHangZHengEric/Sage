import os
import re
import asyncio
from typing import Dict, Optional, List

from sagents.utils.sandbox.config import VolumeMount


class SandboxFileSystem:
    """
    Represents the file system within the sandbox environment.
    
    使用 volume_mounts 配置路径映射，支持多路径映射。
    第一个 volume_mount 作为主映射，其余作为额外映射。
    """
    
    def __init__(self, volume_mounts: List[VolumeMount]):
        """
        Args:
            volume_mounts: 卷挂载配置列表，第一个作为主映射
        """
        if not volume_mounts:
            raise ValueError("volume_mounts 不能为空")

        self._volume_mounts = volume_mounts

        # 第一个 mount 作为主映射
        first_mount = volume_mounts[0]
        self.host_path = os.path.abspath(first_mount.host_path)
        self.virtual_path = first_mount.mount_path.rstrip(os.sep) or os.sep

        # 额外的映射
        self._mappings: Dict[str, str] = {}
        for mount in volume_mounts[1:]:
            normalized_virtual = mount.mount_path.rstrip(os.sep) or os.sep
            self._mappings[normalized_virtual] = os.path.abspath(mount.host_path)

        # 如果 host_path == virtual_path，自动禁用路径映射
        self.enable_path_mapping = (self.host_path != self.virtual_path)

    def _iter_virtual_mappings(self):
        """Yield mappings ordered by longest virtual prefix first."""
        items = [(self.virtual_path, self.host_path), *self._mappings.items()]
        return sorted(items, key=lambda item: len(item[0]), reverse=True)

    def _iter_host_mappings(self):
        """Yield mappings ordered by longest host prefix first."""
        items = [(self.virtual_path, self.host_path), *self._mappings.items()]
        host_first = [(host, virtual) for virtual, host in items]
        return sorted(host_first, key=lambda item: len(item[0]), reverse=True)

    def _normalize_input_path(self, path: str) -> str:
        """Normalize common local-path variants before mapping."""
        if not path:
            return path

        # Windows file:/// URLs may be normalized upstream to `/C:/...`.
        if os.name == "nt" and path[:1] in {"/", "\\"}:
            trimmed = path.lstrip("/\\")
            if os.path.isabs(trimmed):
                return trimmed

        return path

    def to_host_path(self, virtual_path: str) -> str:
        """
        Converts a virtual path to a host path.
        Handles both exact matches and subpaths.
        """
        normalized_path = self._normalize_input_path(virtual_path)

        for mapped_virtual, mapped_host in self._iter_virtual_mappings():
            if normalized_path == mapped_virtual:
                return mapped_host
            if normalized_path.startswith(mapped_virtual + os.sep) or normalized_path.startswith(mapped_virtual + "/"):
                rel_path = normalized_path[len(mapped_virtual):].lstrip(os.sep).lstrip("/")
                return os.path.join(mapped_host, rel_path)

        if os.path.isabs(normalized_path):
            return normalized_path

        # Relative paths are rooted inside the primary workspace mount.
        return os.path.join(self.host_path, normalized_path)

    def to_virtual_path(self, host_path: str) -> str:
        """
        Converts a host path to a virtual path. 虚拟路径统一用 POSIX 分隔符 ``/``，
        避免 Windows 在虚拟命名空间里出现混合分隔符。
        """
        normalized_host = os.path.abspath(host_path)
        for mapped_host, mapped_virtual in self._iter_host_mappings():
            if normalized_host == mapped_host:
                return mapped_virtual
            if normalized_host.startswith(mapped_host + os.sep) or normalized_host.startswith(mapped_host + "/"):
                rel_path = normalized_host[len(mapped_host):].lstrip(os.sep).lstrip("/")
                rel_posix = rel_path.replace(os.sep, "/") if os.sep != "/" else rel_path
                base = mapped_virtual.rstrip("/").rstrip(os.sep)
                if not base:
                    return f"/{rel_posix}"
                # 如果虚拟路径本身是 POSIX（以 / 开头），保持 POSIX 拼接
                if base.startswith("/"):
                    return f"{base}/{rel_posix}"
                return os.path.join(base, rel_posix)
        return host_path

    def _write_file_sync(self, path: str, content: str, encoding: str = 'utf-8', append: bool = False) -> str:
        """
        Writes content to a file in the sandbox.
        """
        # Resolve to host path
        if os.path.isabs(path) and path.startswith(self.host_path):
             host_file_path = path
        else:
             host_file_path = self.to_host_path(path)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(host_file_path), exist_ok=True)
        
        mode = 'a' if append else 'w'
        with open(host_file_path, mode, encoding=encoding) as f:
            f.write(content)
            
        return host_file_path

    def _read_file_sync(self, path: str, encoding: str = 'utf-8') -> str:
        """
        Reads content from a file in the sandbox.
        """
        # Resolve to host path
        if os.path.isabs(path) and path.startswith(self.host_path):
             host_file_path = path
        else:
             host_file_path = self.to_host_path(path)
             
        with open(host_file_path, 'r', encoding=encoding) as f:
            return f.read()

    def _exists_sync(self, path: str) -> bool:
        """
        Check if a path exists in the sandbox.
        """
        # Resolve to host path
        if os.path.isabs(path) and path.startswith(self.host_path):
            host_path = path
        else:
            host_path = self.to_host_path(path)
        
        return os.path.exists(host_path)

    def _ensure_directory_sync(self, path: str) -> str:
        """
        Ensures that a directory exists in the sandbox.
        """
        # Resolve to host path
        if os.path.isabs(path) and path.startswith(self.host_path):
             host_dir_path = path
        else:
             host_dir_path = self.to_host_path(path)
        
        os.makedirs(host_dir_path, exist_ok=True)
        return host_dir_path

    def map_text_to_host(self, text: str) -> str:
        """
        Replaces all occurrences of virtual path with host path in a text string.
        """
        if not self.enable_path_mapping:
            return text

        if not text:
            return text
            
        result = text
        for virtual_path, host_path in self._iter_virtual_mappings():
            escaped_path = re.escape(virtual_path)
            pattern = r'(?<![a-zA-Z0-9_\.\-/])' + escaped_path + r'(?=$|/|[^a-zA-Z0-9_\.\-])'
            result = re.sub(pattern, lambda m, replacement=host_path: replacement, result)
        return result

    def map_text_to_virtual(self, text: str) -> str:
        """
        Replaces all occurrences of host path with virtual path in a text string.
        """
        if not text:
            return text

        result = text
        for host_path, virtual_path in self._iter_host_mappings():
            escaped_path = re.escape(host_path)
            pattern = r'(?<![a-zA-Z0-9_\.\-/])' + escaped_path + r'(?=$|/|[^a-zA-Z0-9_\.\-])'
            result = re.sub(pattern, lambda m, replacement=virtual_path: replacement, result)
        return result

    @property
    def root(self) -> str:
        """Alias for host_path"""
        return self.host_path

    def __str__(self) -> str:
        """Return the virtual path representation."""
        return self.virtual_path

    def _get_file_tree_compact_sync(
        self,
        include_hidden: bool = False,
        root_path: Optional[str] = None,
        max_depth: Optional[int] = None,
        max_items_per_dir: int = 5
    ) -> str:
        """
        获取文件树结构（紧凑格式）
        
        Args:
            include_hidden: 是否包含隐藏文件
            root_path: 根路径（宿主机路径），默认为 host_path
            max_depth: 最大深度
            max_items_per_dir: 每个目录最多显示的项目数
            
        Returns:
            文件树字符串
        """
        target_root = root_path if root_path else self.host_path
        
        if not os.path.exists(target_root):
            return ""
        
        ALWAYS_HIDDEN_DIRS = {'.sandbox', '.git', '.idea', '.vscode', '__pycache__', 'node_modules', 'venv', '.DS_Store'}
        target_root = os.path.abspath(target_root)
        base_depth = target_root.rstrip(os.sep).count(os.sep)
        
        result = []
        root_name = os.path.basename(target_root) or "workspace"
        result.append(f"{root_name}/")
        
        for root, dirs, files in os.walk(target_root):
            current_depth = root.rstrip(os.sep).count(os.sep) - base_depth
            
            if max_depth is not None and current_depth >= max_depth:
                dirs[:] = []
            
            dirs[:] = [d for d in dirs if d not in ALWAYS_HIDDEN_DIRS and (include_hidden or not d.startswith('.'))]
            filtered_files = [f for f in files if f not in ALWAYS_HIDDEN_DIRS and (include_hidden or not f.startswith('.'))]
            
            rel_root = os.path.relpath(root, target_root)
            if rel_root == '.':
                rel_root = ''
            
            path_parts = rel_root.split(os.sep) if rel_root else []
            indent = "  " * len(path_parts)
            
            if current_depth > 0:
                items = [('dir', d) for d in sorted(dirs)]
                shown_items = items[:max_items_per_dir]
                hidden_count = len(items) - len(shown_items)
                
                for _, item_name in shown_items:
                    result.append(f"{indent}  {item_name}/")
                
                if hidden_count > 0:
                    result.append(f"{indent}  ... (and {hidden_count} more dirs)")
                
                if current_depth >= 1:
                    dirs[:] = []
            else:
                items = [('dir', d) for d in sorted(dirs)]
                items.extend([('file', f) for f in sorted(filtered_files)])
                
                for item_type, item_name in items:
                    suffix = "/" if item_type == 'dir' else ""
                    result.append(f"{indent}  {item_name}{suffix}")
            
            if rel_root == 'skills':
                dirs[:] = []
        
        return "\n".join(result)

    async def write_file(self, path: str, content: str, encoding: str = 'utf-8', append: bool = False) -> str:
        return await asyncio.to_thread(self._write_file_sync, path, content, encoding, append)

    async def read_file(self, path: str, encoding: str = 'utf-8') -> str:
        return await asyncio.to_thread(self._read_file_sync, path, encoding)

    async def exists(self, path: str) -> bool:
        return await asyncio.to_thread(self._exists_sync, path)

    async def ensure_directory(self, path: str) -> str:
        return await asyncio.to_thread(self._ensure_directory_sync, path)

    async def get_file_tree_compact(
        self,
        include_hidden: bool = False,
        root_path: Optional[str] = None,
        max_depth: Optional[int] = None,
        max_items_per_dir: int = 5
    ) -> str:
        return await asyncio.to_thread(
            self._get_file_tree_compact_sync,
            include_hidden,
            root_path,
            max_depth,
            max_items_per_dir,
        )
