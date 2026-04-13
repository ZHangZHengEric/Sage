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
import asyncio
from typing import Dict, List, Optional

from ...interface import (
    ISandboxHandle,
    SandboxType,
    CommandResult,
    ExecutionResult,
    FileInfo,
)
from ...config import VolumeMount
from sagents.utils.logger import logger


class PassthroughSandboxProvider(ISandboxHandle):
    """直通模式 - 直接在本机执行，无隔离

    使用 volume_mounts 配置工作区映射
    sandbox_agent_workspace 是沙箱内的虚拟路径
    """

    def __init__(
        self,
        sandbox_id: str,
        sandbox_agent_workspace: str,
        volume_mounts: Optional[List[VolumeMount]] = None,
    ):
        self._sandbox_id = sandbox_id
        self._sandbox_agent_workspace = sandbox_agent_workspace
        self._volume_mounts = volume_mounts or []

        # 路径映射表，支持动态修改
        self._dynamic_mounts: Dict[str, str] = {}
        
        # 添加 volume_mounts 到动态映射
        for mount in self._volume_mounts:
            self.add_mount(mount.host_path, mount.mount_path)

    @property
    def sandbox_type(self) -> SandboxType:
        return SandboxType.PASSTHROUGH

    @property
    def sandbox_id(self) -> str:
        return self._sandbox_id

    @property
    def workspace_path(self) -> str:
        return self._sandbox_agent_workspace

    @property
    def host_workspace_path(self) -> str:
        """返回宿主机工作区路径（sandbox_agent_workspace）"""
        return self._sandbox_agent_workspace

    @property
    def volume_mounts(self) -> List[VolumeMount]:
        """返回卷挂载配置列表"""
        return self._volume_mounts

    def add_mount(self, host_path: str, sandbox_path: str) -> None:
        """动态添加路径映射"""
        normalized_virtual = sandbox_path.rstrip("/") or "/"
        self._dynamic_mounts[normalized_virtual] = os.path.abspath(host_path)

    def _iter_virtual_mappings(self) -> List[tuple[str, str]]:
        """生成虚拟路径到宿主机路径的映射列表"""
        # 主映射：sandbox_agent_workspace 映射到自身（直通）
        mappings = [(self._sandbox_agent_workspace, self._sandbox_agent_workspace)]
        # 添加动态映射
        mappings.extend(self._dynamic_mounts.items())
        return sorted(mappings, key=lambda item: len(item[0]), reverse=True)

    def _iter_host_mappings(self) -> List[tuple[str, str]]:
        """生成宿主机路径到虚拟路径的映射列表"""
        mappings = self._iter_virtual_mappings()
        host_first = [(host, virtual) for virtual, host in mappings]
        return sorted(host_first, key=lambda item: len(item[0]), reverse=True)

    def remove_mount(self, sandbox_path: str) -> None:
        """动态移除路径映射"""
        if sandbox_path in self._dynamic_mounts:
            del self._dynamic_mounts[sandbox_path]

    def to_host_path(self, virtual_path: str) -> str:
        """虚拟路径转宿主机路径，支持动态映射"""
        for sandbox_path, host_path in self._iter_virtual_mappings():
            if virtual_path == sandbox_path:
                logger.debug(f"PassthroughSandboxProvider: Path conversion: {virtual_path} -> {host_path}")
                return host_path
            if virtual_path.startswith(sandbox_path + "/"):
                rel_path = virtual_path[len(sandbox_path):].lstrip("/")
                result = os.path.join(host_path, rel_path)
                logger.debug(f"PassthroughSandboxProvider: Path conversion: {virtual_path} -> {result}")
                return result

        return virtual_path

    def to_virtual_path(self, host_path: str) -> str:
        """宿主机路径转虚拟路径"""
        normalized_host = os.path.abspath(host_path)
        for mapped_host, mapped_virtual in self._iter_host_mappings():
            if normalized_host == mapped_host:
                return mapped_virtual
            if normalized_host.startswith(mapped_host + os.sep):
                rel_path = normalized_host[len(mapped_host):].lstrip("/")
                return os.path.join(mapped_virtual, rel_path)
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

    def _read_file_sync(self, host_path: str, encoding: str) -> str:
        with open(host_path, 'r', encoding=encoding) as f:
            return f.read()

    def _write_file_sync(self, host_path: str, content: str, encoding: str) -> None:
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        with open(host_path, 'w', encoding=encoding) as f:
            f.write(content)

    def _list_directory_sync(self, host_path: str) -> List[FileInfo]:
        result = []
        for entry in os.listdir(host_path):
            entry_path = os.path.join(host_path, entry)
            stat = os.stat(entry_path)
            result.append(FileInfo(
                name=entry,
                path=os.path.join(host_path, entry),
                is_dir=os.path.isdir(entry_path),
                size=stat.st_size,
                modified_time=stat.st_mtime,
            ))
        return result

    def _delete_path_sync(self, host_path: str) -> None:
        if os.path.exists(host_path):
            if os.path.isdir(host_path):
                shutil.rmtree(host_path)
            else:
                os.remove(host_path)

    def _copy_from_host_sync(self, host_path: str, target_path: str) -> None:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        if os.path.isdir(host_path):
            shutil.copytree(host_path, target_path, dirs_exist_ok=True)
        else:
            shutil.copy2(host_path, target_path)

    # ... 其余方法保持不变
    async def execute_command(
        self,
        command: str,
        timeout: Optional[int] = None,
        working_dir: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """执行命令"""
        import asyncio
        import subprocess

        # 转换命令中的虚拟路径到宿主机路径
        converted_command = self._convert_paths_in_command(command)

        # 设置工作目录
        if working_dir:
            cwd = self.to_host_path(working_dir)
        else:
            cwd = self._sandbox_agent_workspace

        # 为 npm/npx 配置项目级缓存，避免写入用户主目录 ~/.npm 导致权限问题
        npm_cache_dir = os.path.join(os.path.expanduser("~"), ".sage", ".npm-cache")
        try:
            os.makedirs(npm_cache_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"PassthroughSandboxProvider: Failed to create npm cache dir {npm_cache_dir}: {e}")

        merged_env = {**os.environ, **(env or {})}
        merged_env.setdefault("npm_config_cache", npm_cache_dir)
        merged_env.setdefault("NPM_CONFIG_CACHE", npm_cache_dir)

        # 执行命令
        process = None
        collected_stdout = []
        collected_stderr = []
        try:
            process = await asyncio.create_subprocess_shell(
                converted_command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=merged_env,
            )

            # 使用增量读取方式，确保超时前能获取已产生的输出
            async def read_output():
                while True:
                    try:
                        stdout_chunk = await asyncio.wait_for(
                            process.stdout.read(4096),
                            timeout=0.5
                        )
                        if stdout_chunk:
                            collected_stdout.append(stdout_chunk.decode('utf-8', errors='replace'))

                        stderr_chunk = await asyncio.wait_for(
                            process.stderr.read(4096),
                            timeout=0.5
                        )
                        if stderr_chunk:
                            collected_stderr.append(stderr_chunk.decode('utf-8', errors='replace'))

                        if not stdout_chunk and not stderr_chunk:
                            if process.returncode is not None:
                                break
                    except asyncio.TimeoutError:
                        # 继续读取，检查进程是否还在运行
                        if process.returncode is not None:
                            break
                        continue
                return (
                    ''.join(collected_stdout),
                    ''.join(collected_stderr)
                )

            try:
                stdout_text, stderr_text = await asyncio.wait_for(
                    read_output(),
                    timeout=timeout,
                )
                return CommandResult(
                    success=process.returncode == 0,
                    stdout=stdout_text,
                    stderr=stderr_text,
                    return_code=process.returncode,
                    execution_time=0,
                )
            except asyncio.TimeoutError:
                # 超时发生时，返回已收集的输出
                stdout_text = ''.join(collected_stdout)
                stderr_text = ''.join(collected_stderr)
                if process:
                    try:
                        process.kill()
                        await process.wait()
                    except Exception:
                        pass
                return CommandResult(
                    success=False,
                    stdout=stdout_text,
                    stderr=stderr_text + f"\nCommand timed out after {timeout} seconds",
                    return_code=-1,
                    execution_time=timeout,
                )
        except Exception as e:
            # 其他异常，返回已收集的输出
            stdout_text = ''.join(collected_stdout)
            stderr_text = ''.join(collected_stderr)
            if process:
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
            return CommandResult(
                success=False,
                stdout=stdout_text,
                stderr=stderr_text + f"\n{str(e)}",
                return_code=-1,
                execution_time=0,
            )

    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """读取文件"""
        host_path = self.to_host_path(path)
        return await asyncio.to_thread(self._read_file_sync, host_path, encoding)

    async def write_file(self, path: str, content: str, encoding: str = "utf-8") -> None:
        """写入文件"""
        host_path = self.to_host_path(path)
        await asyncio.to_thread(self._write_file_sync, host_path, content, encoding)

    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        host_path = self.to_host_path(path)
        return await asyncio.to_thread(os.path.exists, host_path)

    async def list_directory(self, path: str) -> List[FileInfo]:
        """列出目录内容"""
        host_path = self.to_host_path(path)
        return await asyncio.to_thread(self._list_directory_sync, host_path)

    async def ensure_directory(self, path: str) -> None:
        """确保目录存在"""
        host_path = self.to_host_path(path)
        await asyncio.to_thread(os.makedirs, host_path, exist_ok=True)

    async def get_file_info(self, path: str) -> Optional[FileInfo]:
        """获取文件信息"""
        host_path = self.to_host_path(path)
        if not await asyncio.to_thread(os.path.exists, host_path):
            return None
        stat = await asyncio.to_thread(os.stat, host_path)
        return FileInfo(
            name=os.path.basename(path),
            path=path,
            is_dir=await asyncio.to_thread(os.path.isdir, host_path),
            size=stat.st_size,
            modified_time=stat.st_mtime,
        )

    async def delete_file(self, path: str) -> None:
        """删除文件"""
        host_path = self.to_host_path(path)
        await asyncio.to_thread(self._delete_path_sync, host_path)

    async def copy_from_host(self, host_path: str, sandbox_path: str) -> None:
        """从宿主机复制文件到沙箱"""
        target_path = self.to_host_path(sandbox_path)
        await asyncio.to_thread(self._copy_from_host_sync, host_path, target_path)

    async def execute_python(self, code: str, timeout: Optional[int] = None) -> ExecutionResult:
        """执行 Python 代码"""
        import asyncio
        import subprocess
        import tempfile

        # 创建临时文件存储代码
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_file = f.name

        try:
            # 执行 Python 代码
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                temp_file,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._sandbox_agent_workspace,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

            return ExecutionResult(
                exit_code=process.returncode,
                stdout=stdout.decode('utf-8', errors='replace'),
                stderr=stderr.decode('utf-8', errors='replace'),
            )
        except asyncio.TimeoutError:
            process.kill()
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"Python execution timed out after {timeout} seconds",
            )
        except Exception as e:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
            )
        finally:
            # 清理临时文件
            try:
                os.remove(temp_file)
            except:
                pass

    async def execute_javascript(self, code: str, timeout: Optional[int] = None) -> ExecutionResult:
        """执行 JavaScript 代码"""
        import asyncio
        import subprocess

        # 检查是否有 node 环境
        try:
            process = await asyncio.create_subprocess_exec(
                'node',
                '-e',
                code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._sandbox_agent_workspace,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )

            return ExecutionResult(
                exit_code=process.returncode,
                stdout=stdout.decode('utf-8', errors='replace'),
                stderr=stderr.decode('utf-8', errors='replace'),
            )
        except FileNotFoundError:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr="Node.js not found. Please install Node.js to execute JavaScript code.",
            )
        except asyncio.TimeoutError:
            process.kill()
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=f"JavaScript execution timed out after {timeout} seconds",
            )
        except Exception as e:
            return ExecutionResult(
                exit_code=-1,
                stdout="",
                stderr=str(e),
            )

    async def get_file_tree(self, include_hidden: bool = False, root_path: Optional[str] = None, max_depth: Optional[int] = None, max_items_per_dir: int = 5) -> str:
        """获取文件树"""
        from .filesystem import SandboxFileSystem

        if root_path:
            target_path = self.to_host_path(root_path)
        else:
            target_path = self._sandbox_agent_workspace

        if not os.path.exists(target_path):
            return ""

        # 使用 SandboxFileSystem 的 get_file_tree 方法
        fs = SandboxFileSystem(volume_mounts=[
            VolumeMount(self._sandbox_agent_workspace, self._sandbox_agent_workspace)
        ])
        return await fs.get_file_tree_compact(
            include_hidden=include_hidden,
            root_path=target_path,
            max_depth=max_depth,
            max_items_per_dir=max_items_per_dir,
        )
