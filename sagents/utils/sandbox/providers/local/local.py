"""
本地沙箱实现 - 适配现有的 Sandbox 类

提供进程级隔离（venv + 可选的 bwrap/seatbelt）

与 PassthroughSandboxProvider 的区别：
- LocalSandboxProvider: 提供完整的隔离环境，包括：
  1. Python venv 虚拟环境隔离
  2. 可选的进程级隔离（bwrap/seatbelt）
  3. 路径映射（虚拟路径 ↔ 宿主机路径）
  4. 资源限制（CPU时间、内存）
  适用场景：生产环境、需要隔离的多租户场景

- PassthroughSandboxProvider: 无隔离，直接在本机执行：
  1. 不使用 venv，直接使用系统 Python
  2. 无进程级隔离
  3. 简单的路径映射（仅用于路径转换）
  适用场景：开发调试、单用户本地运行、性能敏感场景
"""

import os
import re
import shutil
import subprocess
import sys
from datetime import timedelta
from typing import Dict, List, Optional

from ...interface import (
    ISandboxHandle,
    SandboxType,
    CommandResult,
    ExecutionResult,
    FileInfo,
)
from ...config import MountPath
from sagents.utils.logger import logger


class LocalSandboxProvider(ISandboxHandle):
    """本地沙箱实现 - 提供进程级隔离"""

    def __init__(
        self,
        sandbox_id: str,
        host_workspace: str,
        virtual_workspace: str = "/sage-workspace",
        mount_paths: Optional[List[MountPath]] = None,
        cpu_time_limit: int = 300,
        memory_limit_mb: int = 4096,
        allowed_paths: Optional[List[str]] = None,
        linux_isolation_mode: str = "subprocess",
        macos_isolation_mode: str = "subprocess",
    ):
        self._sandbox_id = sandbox_id
        self._host_workspace = host_workspace
        self._virtual_workspace = virtual_workspace
        self._mount_paths = mount_paths or []
        self._cpu_time_limit = cpu_time_limit
        self._memory_limit_mb = memory_limit_mb
        self._allowed_paths = allowed_paths
        self._linux_isolation_mode = linux_isolation_mode
        self._macos_isolation_mode = macos_isolation_mode

        # 初始化文件系统
        self._file_system = None
        # 初始化隔离层
        self._isolation = None
        # venv 目录
        self._venv_dir = None

    def _ensure_initialized(self):
        """确保沙箱已初始化"""
        if self._file_system is None:
            from .filesystem import SandboxFileSystem

            logger.info(f"LocalSandboxProvider: Initializing with host_workspace={self._host_workspace}, virtual_workspace={self._virtual_workspace}")

            self._file_system = SandboxFileSystem(
                host_path=self._host_workspace,
                virtual_path=self._virtual_workspace,
                enable_path_mapping=True,
            )

            # 添加额外的路径映射
            for mp in self._mount_paths:
                self._file_system.add_mapping(mp.sandbox_path, mp.host_path)

            # 设置 venv 目录
            self._venv_dir = os.path.join(self._host_workspace, ".sandbox", "venv")

            # 初始化隔离层（如果需要）
            if self._linux_isolation_mode != "subprocess" or self._macos_isolation_mode != "subprocess":
                self._init_isolation()

    def _init_isolation(self):
        """初始化隔离层"""
        from .isolation import SubprocessIsolation, SeatbeltIsolation, BwrapIsolation

        if sys.platform == "darwin":
            if self._macos_isolation_mode == "seatbelt":
                self._isolation = SeatbeltIsolation(
                    venv_dir=self._venv_dir,
                    host_workspace=self._host_workspace,
                    limits={"cpu_time": self._cpu_time_limit, "memory": self._memory_limit_mb * 1024 * 1024},
                    allowed_paths=self._allowed_paths or [],
                    sandbox_dir=os.path.join(self._host_workspace, ".sandbox"),
                )
        else:
            if self._linux_isolation_mode == "bwrap":
                self._isolation = BwrapIsolation(
                    venv_dir=self._venv_dir,
                    host_workspace=self._host_workspace,
                    limits={"cpu_time": self._cpu_time_limit, "memory": self._memory_limit_mb * 1024 * 1024},
                    virtual_workspace=self._virtual_workspace,
                )

    def _get_venv_python(self) -> Optional[str]:
        """获取 venv 的 Python 路径"""
        if self._venv_dir and os.path.exists(self._venv_dir):
            if sys.platform == "win32":
                python_path = os.path.join(self._venv_dir, "Scripts", "python.exe")
            else:
                python_path = os.path.join(self._venv_dir, "bin", "python")
            if os.path.exists(python_path):
                return python_path
        return None

    def _ensure_venv(self):
        """确保 venv 存在"""
        if not os.path.exists(self._venv_dir):
            import venv

            os.makedirs(os.path.dirname(self._venv_dir), exist_ok=True)
            venv.create(self._venv_dir, with_pip=True)

    @property
    def sandbox_type(self) -> SandboxType:
        return SandboxType.LOCAL

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def workspace_path(self) -> str:
        return self._virtual_workspace

    @property
    def host_workspace_path(self) -> str:
        return self._host_workspace

    def add_mount(self, host_path: str, sandbox_path: str) -> None:
        """动态添加路径映射"""
        self._ensure_initialized()
        if self._file_system:
            self._file_system.add_mapping(sandbox_path, host_path)

    def remove_mount(self, sandbox_path: str) -> None:
        """动态移除路径映射"""
        # 本地沙箱暂不支持动态移除
        pass

    async def initialize(self) -> None:
        """初始化本地沙箱"""
        self._ensure_initialized()
        self._ensure_venv()

    async def cleanup(self) -> None:
        """清理本地沙箱资源"""
        # 本地沙箱不需要特殊清理
        pass

    def add_allowed_paths(self, paths: List[str]) -> None:
        """添加允许访问的路径列表"""
        if self._allowed_paths is None:
            self._allowed_paths = []
        for path in paths:
            if path not in self._allowed_paths:
                self._allowed_paths.append(path)
        # 如果隔离层已初始化，也需要更新
        if self._isolation and hasattr(self._isolation, 'allowed_paths'):
            for path in paths:
                if path not in self._isolation.allowed_paths:
                    self._isolation.allowed_paths.append(path)

    def remove_allowed_paths(self, paths: List[str]) -> None:
        """移除允许访问的路径列表"""
        if self._allowed_paths:
            self._allowed_paths = [p for p in self._allowed_paths if p not in paths]
        # 如果隔离层已初始化，也需要更新
        if self._isolation and hasattr(self._isolation, 'allowed_paths'):
            self._isolation.allowed_paths = [p for p in self._isolation.allowed_paths if p not in paths]

    def get_allowed_paths(self) -> List[str]:
        """获取当前允许访问的路径列表"""
        return list(self._allowed_paths) if self._allowed_paths else []

    def to_host_path(self, virtual_path: str) -> str:
        """虚拟路径转宿主机路径"""
        self._ensure_initialized()
        if self._file_system:
            host_path = self._file_system.to_host_path(virtual_path)
            if host_path != virtual_path:
                logger.debug(f"LocalSandboxProvider: Path conversion: {virtual_path} -> {host_path}")
            return host_path
        return virtual_path

    def to_virtual_path(self, host_path: str) -> str:
        """宿主机路径转虚拟路径"""
        self._ensure_initialized()
        if self._file_system:
            return self._file_system.to_virtual_path(host_path)
        return host_path

    def _convert_paths_in_command(self, command: str) -> str:
        """Convert virtual paths to host paths in command string
        
        This method finds path-like patterns in the command and converts
        virtual paths to host paths.
        """
        if not command:
            return command
            
        # Pattern to match common path patterns:
        # - Absolute paths starting with / (e.g., /sage-workspace, /tmp)
        # - Paths in quotes (single or double)
        # This is a simple heuristic and may need refinement
        
        converted_command = command
        
        # Find all potential paths (simplified approach)
        # Look for patterns like: /path/to/file, "/path/to/file", '/path/to/file'
        path_pattern = r'["\']?(/[a-zA-Z0-9_\-./]+)["\']?'
        
        def replace_path(match):
            full_match = match.group(0)
            path = match.group(1)
            
            # Check if this looks like a virtual path we should convert
            # Convert the path
            host_path = self.to_host_path(path)
            
            # If conversion changed the path, replace it
            if host_path != path:
                # Preserve quotes if they existed
                if full_match.startswith('"') and full_match.endswith('"'):
                    return f'"{host_path}"'
                elif full_match.startswith("'") and full_match.endswith("'"):
                    return f"'{host_path}'"
                else:
                    return host_path
            return full_match
        
        converted_command = re.sub(path_pattern, replace_path, converted_command)
        return converted_command

    async def execute_command(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """执行 shell 命令（使用 venv 环境）"""
        self._ensure_initialized()

        # 转换工作目录
        actual_workdir = self.to_host_path(workdir) if workdir else self._host_workspace

        # 转换命令中的虚拟路径为宿主机路径
        converted_command = self._convert_paths_in_command(command)
        if converted_command != command:
            logger.info(f"LocalSandboxProvider: Command path conversion: {command} -> {converted_command}")

        logger.info(f"LocalSandboxProvider: Executing command in {actual_workdir}: {converted_command[:100]}{'...' if len(converted_command) > 100 else ''}")

        # 准备环境变量
        env = os.environ.copy()

        # 设置 venv 环境
        venv_python = self._get_venv_python()
        if venv_python:
            venv_bin = os.path.dirname(venv_python)
            env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

        # 添加额外环境变量
        if env_vars:
            env.update(env_vars)

        # 如果有隔离层，使用隔离层执行
        if self._isolation:
            try:
                payload = {
                    'mode': 'shell',
                    'command': converted_command,
                    'cwd': actual_workdir,
                }
                result = self._isolation.execute(payload, cwd=actual_workdir)
                if isinstance(result, dict):
                    return CommandResult(
                        success=result.get('success', True),
                        stdout=result.get('output', ''),
                        stderr='',
                        return_code=0 if result.get('success', True) else 1,
                        execution_time=0,
                    )
                else:
                    return CommandResult(
                        success=True,
                        stdout=str(result),
                        stderr='',
                        return_code=0,
                        execution_time=0,
                    )
            except Exception as e:
                logger.error(f"Isolation execution failed: {e}, falling back to direct execution")
                # 隔离层执行失败，回退到直接执行

        # 直接执行命令 - 合并 stdout 和 stderr 以保持原始输出顺序
        result = subprocess.run(
            converted_command,
            shell=True,
            cwd=actual_workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        return CommandResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr="",  # 已合并到 stdout
            return_code=result.returncode,
            execution_time=0,
        )

    async def execute_python(
        self,
        code: str,
        requirements: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> ExecutionResult:
        """执行 Python 代码（使用 venv）"""
        self._ensure_initialized()

        # 安装依赖
        if requirements:
            pip_cmd = f"pip install {' '.join(requirements)}"
            await self.execute_command(pip_cmd, workdir, timeout=300)

        # 创建临时文件执行代码
        import tempfile

        actual_workdir = self.to_host_path(workdir) if workdir else self._host_workspace

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_file = f.name

        try:
            venv_python = self._get_venv_python()
            python_cmd = venv_python if venv_python else "python"

            result = subprocess.run(
                [python_cmd, temp_file],
                cwd=actual_workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return ExecutionResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                execution_time=0,
                installed_packages=requirements or [],
            )
        finally:
            os.unlink(temp_file)

    async def execute_javascript(
        self,
        code: str,
        packages: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> ExecutionResult:
        """执行 JavaScript 代码"""
        self._ensure_initialized()

        # 安装依赖
        if packages:
            npm_cmd = f"npm install {' '.join(packages)}"
            await self.execute_command(npm_cmd, workdir, timeout=300)

        # 创建临时文件执行代码
        import tempfile

        actual_workdir = self.to_host_path(workdir) if workdir else self._host_workspace

        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            temp_file = f.name

        try:
            result = subprocess.run(
                ["node", temp_file],
                cwd=actual_workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return ExecutionResult(
                success=result.returncode == 0,
                output=result.stdout,
                error=result.stderr if result.returncode != 0 else None,
                execution_time=0,
                installed_packages=packages or [],
            )
        finally:
            os.unlink(temp_file)

    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """读取文件"""
        self._ensure_initialized()
        actual_path = self.to_host_path(path)
        with open(actual_path, "r", encoding=encoding) as f:
            return f.read()

    async def write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        mode: str = "overwrite",
    ) -> None:
        """写入文件"""
        self._ensure_initialized()
        actual_path = self.to_host_path(path)
        os.makedirs(os.path.dirname(actual_path), exist_ok=True)
        write_mode = "a" if mode == "append" else "w"
        with open(actual_path, write_mode, encoding=encoding) as f:
            f.write(content)

    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        self._ensure_initialized()
        actual_path = self.to_host_path(path)
        return os.path.exists(actual_path)

    async def list_directory(
        self,
        path: str,
        include_hidden: bool = False,
    ) -> List[FileInfo]:
        """列出目录内容"""
        self._ensure_initialized()
        actual_path = self.to_host_path(path)

        if not os.path.isdir(actual_path):
            return []

        result = []
        for entry in os.scandir(actual_path):
            if not include_hidden and entry.name.startswith("."):
                continue

            stat = entry.stat()
            result.append(
                FileInfo(
                    path=self.to_virtual_path(entry.path),
                    is_file=entry.is_file(),
                    is_dir=entry.is_dir(),
                    size=stat.st_size,
                    modified_time=stat.st_mtime,
                )
            )

        return result

    async def ensure_directory(self, path: str) -> None:
        """确保目录存在"""
        self._ensure_initialized()
        actual_path = self.to_host_path(path)
        os.makedirs(actual_path, exist_ok=True)

    async def delete_file(self, path: str) -> None:
        """删除文件"""
        self._ensure_initialized()
        actual_path = self.to_host_path(path)

        if os.path.exists(actual_path):
            if os.path.isdir(actual_path):
                import shutil
                shutil.rmtree(actual_path)
            else:
                os.remove(actual_path)

    async def get_file_tree(
        self,
        root_path: Optional[str] = None,
        include_hidden: bool = False,
        max_depth: Optional[int] = None,
        max_items_per_dir: int = 5
    ) -> str:
        """
        获取文件树结构（紧凑格式）
        
        使用 filesystem 的 get_file_tree_compact 方法
        """
        self._ensure_initialized()
        
        if self._file_system:
            # 转换虚拟路径为宿主机路径
            host_root_path = self.to_host_path(root_path) if root_path else None
            return self._file_system.get_file_tree_compact(
                include_hidden=include_hidden,
                root_path=host_root_path,
                max_depth=max_depth,
                max_items_per_dir=max_items_per_dir
            )
        
        # Fallback: 使用基本实现
        return self._basic_get_file_tree(root_path, include_hidden, max_depth, max_items_per_dir)
    
    def _basic_get_file_tree(
        self,
        root_path: Optional[str] = None,
        include_hidden: bool = False,
        max_depth: Optional[int] = None,
        max_items_per_dir: int = 5
    ) -> str:
        """基本的文件树实现（当 filesystem 不可用时）"""
        target_root = self.to_host_path(root_path) if root_path else self._host_workspace
        
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

    async def copy_from_host(
        self,
        host_source_path: str,
        sandbox_dest_path: str,
        ignore_patterns: Optional[List[str]] = None
    ) -> bool:
        """
        从宿主机复制文件/目录到沙箱
        
        本地沙箱实现：直接复制到宿主机路径
        """
        self._ensure_initialized()
        
        if not os.path.exists(host_source_path):
            logger.warning(f"源路径不存在: {host_source_path}")
            return False
        
        # 转换沙箱虚拟路径为宿主机路径
        host_dest_path = self.to_host_path(sandbox_dest_path)
        
        try:
            if os.path.isdir(host_source_path):
                # 复制目录
                if os.path.exists(host_dest_path):
                    shutil.rmtree(host_dest_path)
                
                # 使用 ignore 参数过滤文件
                if ignore_patterns:
                    import fnmatch
                    def ignore_filter(dir, files):
                        ignored = []
                        for pattern in ignore_patterns:
                            ignored.extend([f for f in files if fnmatch.fnmatch(f, pattern)])
                        return ignored
                    shutil.copytree(host_source_path, host_dest_path, ignore=ignore_filter)
                else:
                    shutil.copytree(host_source_path, host_dest_path)
            else:
                # 复制单个文件
                os.makedirs(os.path.dirname(host_dest_path), exist_ok=True)
                shutil.copy2(host_source_path, host_dest_path)
            
            logger.debug(f"复制成功: {host_source_path} -> {sandbox_dest_path} (实际: {host_dest_path})")
            return True
        except Exception as e:
            logger.error(f"复制失败: {host_source_path} -> {sandbox_dest_path}: {e}")
            return False
