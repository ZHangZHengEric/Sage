"""
直通模式沙箱实现 - 直接在本机执行，无隔离

用于开发调试或特殊场景

与 LocalSandboxProvider 的区别：
- PassthroughSandboxProvider: 无隔离，直接在本机执行：
  1. 不使用 venv，直接使用系统 Python
  2. 无进程级隔离（bwrap/seatbelt）
  3. 简单的路径映射（仅用于路径转换）
  4. 无资源限制
  适用场景：开发调试、单用户本地运行、性能敏感场景

- LocalSandboxProvider: 提供完整的隔离环境，包括：
  1. Python venv 虚拟环境隔离
  2. 可选的进程级隔离（bwrap/seatbelt）
  3. 路径映射（虚拟路径 ↔ 宿主机路径）
  4. 资源限制（CPU时间、内存）
  适用场景：生产环境、需要隔离的多租户场景
"""

import os
import re
import shutil
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


class PassthroughSandboxProvider(ISandboxHandle):
    """直通模式 - 直接在本机执行，无隔离"""

    def __init__(
        self,
        sandbox_id: str,
        workspace: str = ".",
        mount_paths: Optional[List[MountPath]] = None,
    ):
        self._sandbox_id = sandbox_id
        self._workspace = os.path.abspath(workspace)
        self._mount_paths = mount_paths or []
        # 路径映射表，支持动态修改
        self._dynamic_mounts: Dict[str, str] = {}

    @property
    def sandbox_type(self) -> SandboxType:
        return SandboxType.PASSTHROUGH

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def workspace_path(self) -> str:
        return self._workspace

    @property
    def host_workspace_path(self) -> str:
        return self._workspace

    def add_mount(self, host_path: str, sandbox_path: str) -> None:
        """动态添加路径映射"""
        self._dynamic_mounts[sandbox_path] = host_path

    def remove_mount(self, sandbox_path: str) -> None:
        """动态移除路径映射"""
        if sandbox_path in self._dynamic_mounts:
            del self._dynamic_mounts[sandbox_path]

    def to_host_path(self, virtual_path: str) -> str:
        """虚拟路径转宿主机路径，支持动态映射"""
        # 先检查动态映射
        for sandbox_path, host_path in self._dynamic_mounts.items():
            if virtual_path.startswith(sandbox_path):
                rel_path = virtual_path[len(sandbox_path):].lstrip("/")
                result = os.path.join(host_path, rel_path)
                logger.debug(f"PassthroughSandboxProvider: Dynamic mount conversion: {virtual_path} -> {result}")
                return result

        # 默认工作区映射
        if virtual_path.startswith("/sage-workspace"):
            rel_path = virtual_path[len("/sage-workspace"):].lstrip("/")
            result = os.path.join(self._workspace, rel_path)
            logger.debug(f"PassthroughSandboxProvider: Workspace conversion: {virtual_path} -> {result}")
            return result

        return virtual_path

    def to_virtual_path(self, host_path: str) -> str:
        """宿主机路径转虚拟路径"""
        if host_path.startswith(self._workspace):
            rel_path = host_path[len(self._workspace):].lstrip("/")
            return os.path.join("/sage-workspace", rel_path)
        return host_path

    async def initialize(self) -> None:
        """初始化直通模式沙箱"""
        # 直通模式不需要特殊初始化
        pass

    async def cleanup(self) -> None:
        """清理直通模式沙箱资源"""
        # 直通模式不需要特殊清理
        pass

    def add_allowed_paths(self, paths: List[str]) -> None:
        """添加允许访问的路径列表 - 直通模式无限制，空实现"""
        # 直通模式没有访问限制，不需要实现
        pass

    def remove_allowed_paths(self, paths: List[str]) -> None:
        """移除允许访问的路径列表 - 直通模式无限制，空实现"""
        # 直通模式没有访问限制，不需要实现
        pass

    def get_allowed_paths(self) -> List[str]:
        """获取当前允许访问的路径列表 - 直通模式返回空列表"""
        # 直通模式没有访问限制，返回空列表
        return []

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
        """直接在本机执行命令"""
        actual_workdir = self.to_host_path(workdir) if workdir else self._workspace

        # 转换命令中的虚拟路径为宿主机路径
        converted_command = self._convert_paths_in_command(command)
        if converted_command != command:
            logger.info(f"PassthroughSandboxProvider: Command path conversion: {command} -> {converted_command}")

        logger.info(f"PassthroughSandboxProvider: Executing command in {actual_workdir}: {converted_command[:100]}{'...' if len(converted_command) > 100 else ''}")

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        # 使用异步 subprocess 执行命令，避免阻塞
        import asyncio
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_shell(
                    converted_command,
                    cwd=actual_workdir,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                ),
                timeout=timeout,
            )
            stdout, _ = await proc.communicate()
            stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
            return CommandResult(
                success=proc.returncode == 0,
                stdout=stdout_text,
                stderr="",  # 已合并到 stdout
                return_code=proc.returncode,
                execution_time=0,
            )
        except asyncio.TimeoutError:
            if proc:
                proc.kill()
                await proc.wait()
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Command timed out after {timeout} seconds",
                return_code=-1,
                execution_time=timeout,
            )

    async def execute_python(
        self,
        code: str,
        requirements: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60,
    ) -> ExecutionResult:
        """执行 Python 代码"""
        # 创建临时文件执行代码
        import tempfile

        actual_workdir = self.to_host_path(workdir) if workdir else self._workspace

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            temp_file = f.name

        try:
            # 使用异步 subprocess 执行，避免阻塞
            import asyncio
            try:
                proc = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        "python",
                        temp_file,
                        cwd=actual_workdir,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    ),
                    timeout=timeout,
                )
                stdout, stderr = await proc.communicate()
                stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
                stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""

                return ExecutionResult(
                    success=proc.returncode == 0,
                    output=stdout_text,
                    error=stderr_text if proc.returncode != 0 else None,
                    execution_time=0,
                    installed_packages=requirements or [],
                )
            except asyncio.TimeoutError:
                if proc:
                    proc.kill()
                    await proc.wait()
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"Python execution timed out after {timeout} seconds",
                    execution_time=timeout,
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
        import tempfile

        actual_workdir = self.to_host_path(workdir) if workdir else self._workspace

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".js", delete=False
        ) as f:
            f.write(code)
            temp_file = f.name

        try:
            # 使用异步 subprocess 执行，避免阻塞
            import asyncio
            try:
                proc = await asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        "node",
                        temp_file,
                        cwd=actual_workdir,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    ),
                    timeout=timeout,
                )
                stdout, stderr = await proc.communicate()
                stdout_text = stdout.decode('utf-8', errors='replace') if stdout else ""
                stderr_text = stderr.decode('utf-8', errors='replace') if stderr else ""

                return ExecutionResult(
                    success=proc.returncode == 0,
                    output=stdout_text,
                    error=stderr_text if proc.returncode != 0 else None,
                    execution_time=0,
                    installed_packages=packages or [],
                )
            except asyncio.TimeoutError:
                if proc:
                    proc.kill()
                    await proc.wait()
                return ExecutionResult(
                    success=False,
                    output="",
                    error=f"JavaScript execution timed out after {timeout} seconds",
                    execution_time=timeout,
                    installed_packages=packages or [],
                )
        finally:
            os.unlink(temp_file)

    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """直接读取文件"""
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
        """直接写入文件"""
        actual_path = self.to_host_path(path)
        os.makedirs(os.path.dirname(actual_path), exist_ok=True)
        write_mode = "a" if mode == "append" else "w"
        with open(actual_path, write_mode, encoding=encoding) as f:
            f.write(content)

    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        actual_path = self.to_host_path(path)
        return os.path.exists(actual_path)

    async def list_directory(
        self,
        path: str,
        include_hidden: bool = False,
    ) -> List[FileInfo]:
        """列出目录内容"""
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
        actual_path = self.to_host_path(path)
        os.makedirs(actual_path, exist_ok=True)

    async def delete_file(self, path: str) -> None:
        """删除文件"""
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

        直通模式实现：直接遍历工作目录
        """
        target_root = self.to_host_path(root_path) if root_path else self._workspace

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

        直通模式实现：直接复制到工作目录
        """
        if not os.path.exists(host_source_path):
            logger.warning(f"源路径不存在: {host_source_path}")
            return False

        # 转换沙箱虚拟路径为实际路径
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
