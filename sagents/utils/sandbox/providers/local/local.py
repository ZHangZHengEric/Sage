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
import sys
import asyncio
import fnmatch
from typing import Any, Dict, List, Optional

from ..._stdout_echo import echo_chunk
from ..._bg_runner import HostBackgroundRunner
from ...interface import (
    ISandboxHandle,
    SandboxType,
    CommandResult,
    ExecutionResult,
    FileInfo,
)
from ...config import VolumeMount
from sagents.utils.logger import logger
from sagents.utils.common_utils import (
    get_system_python_path,
    resolve_python_venv_dir,
    resolve_sandbox_runtime_dir,
    file_lock,
)


class LocalSandboxProvider(ISandboxHandle):
    """本地沙箱实现 - 提供进程级隔离

    sandbox_agent_workspace 是沙箱内的虚拟工作区路径
    volume_mounts 用于将宿主机路径映射到沙箱内的其他路径
    """

    def __init__(
        self,
        sandbox_id: str,
        sandbox_agent_workspace: str,
        volume_mounts: Optional[List[VolumeMount]] = None,
        cpu_time_limit: int = 300,
        memory_limit_mb: int = 4096,
        allowed_paths: Optional[List[str]] = None,
        linux_isolation_mode: str = "bwrap",
        macos_isolation_mode: str = "seatbelt",
    ):
        self._sandbox_id = sandbox_id
        self._sandbox_agent_workspace = sandbox_agent_workspace
        self._volume_mounts = volume_mounts or []
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
        # 跨平台后台进程运行器（local 沙箱的后台命令直接走主机进程，
        # 不进 bwrap/seatbelt，方便长跑任务管理）
        self._bg_runner = HostBackgroundRunner()

    async def _ensure_initialized(self):
        """确保沙箱已初始化"""
        if self._file_system is None:
            from .filesystem import SandboxFileSystem

            logger.info(f"LocalSandboxProvider: Initializing with workspace={self._sandbox_agent_workspace}")

            # 显式传入 volume_mounts 时以其为准；否则用 sandbox_agent_workspace 作 1:1 宿主机映射
            if self._volume_mounts:
                volume_mounts = list(self._volume_mounts)
            else:
                volume_mounts = [
                    VolumeMount(
                        host_path=self._sandbox_agent_workspace,
                        mount_path=self._sandbox_agent_workspace,
                    )
                ]
            
            # 使用 volume_mounts 创建文件系统
            self._file_system = SandboxFileSystem(volume_mounts)

            # venv / 运行时目录必须落在宿主机路径上（虚拟路径如 /sage-workspace 不可直接 mkdir）
            host_workspace = self._file_system.to_host_path(self._sandbox_agent_workspace)

            # 设置 venv 目录（desktop 可切换为共享 venv）
            self._venv_dir = resolve_python_venv_dir(host_workspace)
            sandbox_runtime_dir = resolve_sandbox_runtime_dir(host_workspace)
            if sandbox_runtime_dir:
                os.makedirs(sandbox_runtime_dir, exist_ok=True)

            # 初始化隔离层（如果需要）
            if self._linux_isolation_mode != "subprocess" or self._macos_isolation_mode != "subprocess":
                self._init_isolation()

    async def _ensure_initialized_async(self):
        """异步确保沙箱已初始化，避免阻塞事件循环。"""
        await self._ensure_initialized()

    def _init_isolation(self):
        """初始化隔离层"""
        from .isolation import SeatbeltIsolation, BwrapIsolation

        if sys.platform == "darwin":
            if self._macos_isolation_mode == "seatbelt":
                self._isolation = SeatbeltIsolation(
                    venv_dir=self._venv_dir,
                    sandbox_agent_workspace=self._sandbox_agent_workspace,
                    sandbox_runtime_dir=resolve_sandbox_runtime_dir(self._sandbox_agent_workspace),
                    volume_mounts=self._volume_mounts,
                    limits={"cpu_time": self._cpu_time_limit, "memory": self._memory_limit_mb * 1024 * 1024},
                )
        else:
            if self._linux_isolation_mode == "bwrap":
                self._isolation = BwrapIsolation(
                    venv_dir=self._venv_dir,
                    sandbox_agent_workspace=self._sandbox_agent_workspace,
                    sandbox_runtime_dir=resolve_sandbox_runtime_dir(self._sandbox_agent_workspace),
                    volume_mounts=self._volume_mounts,
                    limits={"cpu_time": self._cpu_time_limit, "memory": self._memory_limit_mb * 1024 * 1024},
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

    def _ensure_python_executable(self):
        """确保 venv 中的 Python 解释器有执行权限"""
        if sys.platform == "win32":
            # Windows 下不需要设置执行权限
            return

        venv_bin = os.path.join(self._venv_dir, "bin")
        python_executables = ["python", "python3"]

        for exe_name in python_executables:
            python_path = os.path.join(venv_bin, exe_name)
            if os.path.exists(python_path):
                try:
                    # 获取当前权限
                    current_mode = os.stat(python_path).st_mode
                    # 添加执行权限 (owner, group, others)
                    new_mode = current_mode | 0o111
                    if current_mode != new_mode:
                        os.chmod(python_path, new_mode)
                        logger.info(f"[LocalSandboxProvider] 添加执行权限: {python_path}")
                except Exception as e:
                    logger.warning(f"[LocalSandboxProvider] 添加执行权限失败 {python_path}: {e}")

    def _ensure_python3_link(self):
        """确保 venv 中同时存在 python 和 python3 命令"""
        if sys.platform == "win32":
            # Windows 下不需要创建符号链接，venv 会自动处理
            return

        venv_bin = os.path.join(self._venv_dir, "bin")
        python_path = os.path.join(venv_bin, "python")
        python3_path = os.path.join(venv_bin, "python3")

        # 如果 python3 不存在，但 python 存在，则创建 python3 -> python 的符号链接
        if os.path.exists(python_path) and not os.path.exists(python3_path):
            try:
                os.symlink("python", python3_path)
                logger.info(f"[LocalSandboxProvider] 创建 python3 符号链接: {python3_path}")
            except Exception as e:
                logger.warning(f"[LocalSandboxProvider] 创建 python3 符号链接失败: {e}")

        # 如果 python 不存在，但 python3 存在，则创建 python -> python3 的符号链接
        if os.path.exists(python3_path) and not os.path.exists(python_path):
            try:
                os.symlink("python3", python_path)
                logger.info(f"[LocalSandboxProvider] 创建 python 符号链接: {python_path}")
            except Exception as e:
                logger.warning(f"[LocalSandboxProvider] 创建 python 符号链接失败: {e}")

    async def _ensure_venv(self):
        """确保 venv 存在"""
        if not self._venv_dir:
            raise RuntimeError("venv 目录未初始化")
        if os.path.exists(self._venv_dir):
            return

        lock_path = os.path.join(os.path.dirname(self._venv_dir), ".venv.lock")
        with file_lock(lock_path):
            if os.path.exists(self._venv_dir):
                return

            import subprocess

            os.makedirs(os.path.dirname(self._venv_dir), exist_ok=True)

            # 获取正确的 Python 解释器路径（处理 PyInstaller 打包环境）
            system_python = get_system_python_path()
            if not system_python:
                raise RuntimeError("无法找到系统 Python 解释器")

            # 使用 subprocess 调用 python -m venv 创建虚拟环境
            logger.info(f"[LocalSandboxProvider] 创建虚拟环境: {self._venv_dir} 使用 Python: {system_python}")
            result = await asyncio.to_thread(
                subprocess.run,
                [system_python, "-m", "venv", self._venv_dir],
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"创建虚拟环境失败: {result.stderr}")

            # 确保 venv 中同时存在 python 和 python3 命令
            self._ensure_python3_link()

            # 确保 Python 解释器有执行权限
            self._ensure_python_executable()

            # 尝试在 venv 内预装 uv（失败不阻塞）
            await self._ensure_uv_in_venv()

    async def _ensure_uv_in_venv(self):
        """在 venv 中安装 uv，便于后续按需使用。"""
        import subprocess

        venv_python = self._get_venv_python()
        if not venv_python:
            logger.warning("[LocalSandboxProvider] 未找到 venv python，跳过 uv 预装")
            return

        install_cmd = [
            venv_python, "-m", "pip", "install", "-U", "uv",
            "--index-url", "https://mirrors.aliyun.com/pypi/simple/",
            "--trusted-host", "mirrors.aliyun.com",
        ]
        result = await asyncio.to_thread(
            subprocess.run, install_cmd, capture_output=True, text=True, timeout=180
        )
        if result.returncode == 0:
            logger.info("[LocalSandboxProvider] uv 已安装到 venv")
            return

        # 镜像失败时回退到默认源
        fallback_cmd = [venv_python, "-m", "pip", "install", "-U", "uv"]
        fallback_result = await asyncio.to_thread(
            subprocess.run, fallback_cmd, capture_output=True, text=True, timeout=180
        )
        if fallback_result.returncode == 0:
            logger.info("[LocalSandboxProvider] uv 已安装到 venv（默认源）")
        else:
            logger.warning(f"[LocalSandboxProvider] 预装 uv 失败，不影响后续执行: {fallback_result.stderr}")

    @property
    def sandbox_type(self) -> SandboxType:
        return SandboxType.LOCAL

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
        if self._file_system:
            self._file_system.add_mapping(sandbox_path, host_path)

    def remove_mount(self, sandbox_path: str) -> None:
        """动态移除路径映射"""
        # 本地沙箱暂不支持动态移除
        pass

    async def initialize(self) -> None:
        """初始化本地沙箱"""
        await self._ensure_initialized_async()

    async def cleanup(self) -> None:
        """清理本地沙箱资源"""
        # 本地沙箱不需要特殊清理
        pass

    # ===== 跨平台后台命令原语（POSIX + Windows） =====

    def supports_background(self) -> bool:
        return True

    async def start_background(
        self,
        command: str,
        workdir: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        await self._ensure_initialized_async()
        converted = self._convert_paths_in_command(command)
        host_workdir = (
            self.to_host_path(workdir) if workdir else self.to_host_path(self._sandbox_agent_workspace)
        )
        return self._bg_runner.start(converted, workdir=host_workdir, env_vars=env_vars)

    async def read_background_output(self, task_id: str, max_bytes: int = 8192) -> str:
        return self._bg_runner.read_tail(task_id, max_bytes=max_bytes)

    async def is_background_alive(self, task_id: str) -> bool:
        return self._bg_runner.is_alive(task_id)

    async def get_background_exit_code(self, task_id: str) -> Optional[int]:
        return self._bg_runner.get_exit_code(task_id)

    async def kill_background(self, task_id: str, force: bool = False) -> bool:
        return self._bg_runner.kill(task_id, force=force)

    async def cleanup_background(self, task_id: str) -> None:
        self._bg_runner.cleanup(task_id)

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
        if self._file_system:
            host_path = self._file_system.to_host_path(virtual_path)
            if host_path != virtual_path:
                logger.debug(f"LocalSandboxProvider: Path conversion: {virtual_path} -> {host_path}")
            return host_path
        return virtual_path

    def to_virtual_path(self, host_path: str) -> str:
        """宿主机路径转虚拟路径"""
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

    def _read_file_sync(self, actual_path: str, encoding: str) -> str:
        with open(actual_path, "r", encoding=encoding) as f:
            return f.read()

    def _write_file_sync(self, actual_path: str, content: str, encoding: str, mode: str) -> None:
        os.makedirs(os.path.dirname(actual_path), exist_ok=True)
        write_mode = "a" if mode == "append" else "w"
        with open(actual_path, write_mode, encoding=encoding) as f:
            f.write(content)

    def _list_directory_sync(self, actual_path: str, include_hidden: bool) -> List[FileInfo]:
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

    def _delete_path_sync(self, actual_path: str) -> None:
        if os.path.exists(actual_path):
            if os.path.isdir(actual_path):
                shutil.rmtree(actual_path)
            else:
                os.remove(actual_path)

    def _copy_from_host_path_sync(
        self,
        host_source_path: str,
        host_dest_path: str,
        ignore_patterns: Optional[List[str]],
    ) -> bool:
        if not os.path.exists(host_source_path):
            return False

        if os.path.isdir(host_source_path):
            if os.path.exists(host_dest_path):
                shutil.rmtree(host_dest_path)

            if ignore_patterns:
                def ignore_filter(_dir, files):
                    ignored = []
                    for pattern in ignore_patterns:
                        ignored.extend([f for f in files if fnmatch.fnmatch(f, pattern)])
                    return ignored

                shutil.copytree(host_source_path, host_dest_path, ignore=ignore_filter)
            else:
                shutil.copytree(host_source_path, host_dest_path)
            return True

        os.makedirs(os.path.dirname(host_dest_path), exist_ok=True)
        shutil.copy2(host_source_path, host_dest_path)
        return True

    async def execute_command(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """执行 shell 命令（使用 venv 环境）"""
        await self._ensure_initialized_async()
        await self._ensure_venv()

        # 转换工作目录
        actual_workdir = (
            self.to_host_path(workdir) if workdir else self.to_host_path(self._sandbox_agent_workspace)
        )

        # 转换命令中的虚拟路径为宿主机路径
        converted_command = self._convert_paths_in_command(command)
        if converted_command != command:
            logger.info(f"LocalSandboxProvider: Command path conversion: {command} -> {converted_command}")


        # 准备环境变量
        env = os.environ.copy()

        # 设置 venv 环境
        venv_python = self._get_venv_python()
        if venv_python:
            venv_bin = os.path.dirname(venv_python)
            env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")

        # 配置 npm 使用国内镜像源
        env["NPM_CONFIG_REGISTRY"] = "https://registry.npmmirror.com"

        # 配置 pip 使用阿里镜像源
        env["PIP_INDEX_URL"] = "https://mirrors.aliyun.com/pypi/simple/"
        env["PIP_TRUSTED_HOST"] = "mirrors.aliyun.com"

        # 配置 Sage 打包的 Node.js 运行时（优先使用）
        bundled_node_bin = os.environ.get("SAGE_BUNDLED_NODE_BIN")
        if bundled_node_bin and os.path.exists(bundled_node_bin):
            # 将打包的 Node.js bin 目录添加到 PATH 最前面
            env["PATH"] = bundled_node_bin + os.pathsep + env.get("PATH", "")
            logger.debug(f"LocalSandboxProvider: Added bundled Node.js bin to PATH: {bundled_node_bin}")
            # 设置 SAGE_USING_BUNDLED_NODE 标记
            env["SAGE_USING_BUNDLED_NODE"] = "1"

        # 配置 Sage 独立的 node 环境（如果已设置）
        sage_node_modules_dir = os.environ.get("SAGE_NODE_MODULES_DIR")
        if sage_node_modules_dir and os.path.exists(sage_node_modules_dir):
            # 将 Sage 的 node_modules/.bin 添加到 PATH
            sage_bin = os.path.join(sage_node_modules_dir, ".bin")
            if os.path.exists(sage_bin):
                # 避免重复添加
                if sage_bin not in env.get("PATH", ""):
                    env["PATH"] = sage_bin + os.pathsep + env.get("PATH", "")
                    logger.debug(f"LocalSandboxProvider: Added Sage node bin to PATH: {sage_bin}")
            # 设置 NODE_PATH 以便 require 能找到模块
            env["NODE_PATH"] = sage_node_modules_dir
            logger.debug(f"LocalSandboxProvider: Set NODE_PATH: {sage_node_modules_dir}")

        # 添加 Sage node_modules/.bin 到 PATH（优先使用真正安装的包）
        # 使用环境变量 NODE_PATH 的值（通常是 ~/.sage/.sage_node_env）
        node_path_env = env.get("NODE_PATH") or os.environ.get("NODE_PATH")
        if node_path_env:
            sage_node_env_bin = os.path.join(node_path_env, "node_modules", ".bin")
            if os.path.exists(sage_node_env_bin) and sage_node_env_bin not in env.get("PATH", ""):
                env["PATH"] = sage_node_env_bin + os.pathsep + env.get("PATH", "")
                logger.debug(f"LocalSandboxProvider: Added Sage node_modules/.bin to PATH: {sage_node_env_bin}")

        # 为 npm/npx 配置项目级缓存，避免写入用户主目录 ~/.npm 导致权限问题
        npm_cache_dir = os.path.join(os.path.expanduser("~"), ".sage", ".npm-cache")
        try:
            os.makedirs(npm_cache_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"LocalSandboxProvider: Failed to create npm cache dir {npm_cache_dir}: {e}")
        env.setdefault("npm_config_cache", npm_cache_dir)
        env.setdefault("NPM_CONFIG_CACHE", npm_cache_dir)

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
                result = await self._isolation.execute(payload, cwd=actual_workdir)
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
                # 隔离层执行失败，永久禁用隔离层并回退到直接执行
                # 避免每次执行都重复尝试和报错
                if "Operation not permitted" in str(e) or "Seatbelt execution failed" in str(e):
                    logger.warning(f"Isolation layer failed permanently (sandbox-exec not permitted), disabling isolation: {e}")
                    self._isolation = None  # 永久禁用隔离层
                else:
                    logger.error(f"Isolation execution failed: {e}, falling back to direct execution")

        # 使用异步 subprocess 执行命令，避免阻塞
        proc = None
        collected_output = []
        try:
            # 使用 exec 模式避免 shell 配置文件覆盖 PATH
            # 通过显式传递 PATH 环境变量确保 venv 的 Python 优先
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh",
                "-c",
                converted_command,
                cwd=actual_workdir,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            # 使用增量读取方式，确保超时前能获取已产生的输出
            # 同时把 chunk 实时回显到当前进程 stdout（受 SAGE_ECHO_SHELL_OUTPUT 控制）
            async def read_output():
                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            proc.stdout.read(4096),
                            timeout=0.5
                        )
                        if not chunk:
                            break
                        chunk_text = chunk.decode('utf-8', errors='replace')
                        collected_output.append(chunk_text)
                        echo_chunk(chunk_text)
                    except asyncio.TimeoutError:
                        # 继续读取，检查进程是否还在运行
                        if proc.returncode is not None:
                            break
                        continue
                return ''.join(collected_output)

            try:
                stdout_text = await asyncio.wait_for(
                    read_output(),
                    timeout=timeout,
                )
                return CommandResult(
                    success=proc.returncode == 0,
                    stdout=stdout_text,
                    stderr="",  # 已合并到 stdout
                    return_code=proc.returncode,
                    execution_time=0,
                )
            except asyncio.TimeoutError:
                # 超时发生时，返回已收集的输出
                stdout_text = ''.join(collected_output)
                if proc:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                return CommandResult(
                    success=False,
                    stdout=stdout_text,
                    stderr=f"Command timed out after {timeout} seconds",
                    return_code=-1,
                    execution_time=timeout,
                )
        except Exception as e:
            # 其他异常，返回已收集的输出
            stdout_text = ''.join(collected_output)
            if proc:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            return CommandResult(
                success=False,
                stdout=stdout_text,
                stderr=str(e),
                return_code=-1,
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
        await self._ensure_initialized_async()
        await self._ensure_venv()

        # 安装依赖
        if requirements:
            pip_cmd = f"pip install {' '.join(requirements)}"
            await self.execute_command(pip_cmd, workdir, timeout=300)

        # 创建临时文件执行代码
        import tempfile

        actual_workdir = (
            self.to_host_path(workdir) if workdir else self.to_host_path(self._sandbox_agent_workspace)
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_file = f.name

        try:
            venv_python = self._get_venv_python()
            python_cmd = venv_python if venv_python else "python"

            # 使用异步 subprocess 执行，避免阻塞
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    python_cmd,
                    temp_file,
                    cwd=actual_workdir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # 使用 wait_for 包装 communicate 来限制整个执行时间
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
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
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
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
        await self._ensure_initialized_async()

        # 安装依赖
        if packages:
            npm_cmd = f"npm install {' '.join(packages)}"
            await self.execute_command(npm_cmd, workdir, timeout=300)

        # 创建临时文件执行代码
        import tempfile

        actual_workdir = (
            self.to_host_path(workdir) if workdir else self.to_host_path(self._sandbox_agent_workspace)
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".js", delete=False) as f:
            f.write(code)
            temp_file = f.name

        try:
            # 使用异步 subprocess 执行，避免阻塞
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(
                    "node",
                    temp_file,
                    cwd=actual_workdir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                # 使用 wait_for 包装 communicate 来限制整个执行时间
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout,
                )
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
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
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
        """读取文件"""
        await self._ensure_initialized_async()
        actual_path = self.to_host_path(path)
        return await asyncio.to_thread(self._read_file_sync, actual_path, encoding)

    async def write_file(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        mode: str = "overwrite",
    ) -> None:
        """写入文件"""
        await self._ensure_initialized_async()
        actual_path = self.to_host_path(path)
        await asyncio.to_thread(self._write_file_sync, actual_path, content, encoding, mode)

    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        await self._ensure_initialized_async()
        actual_path = self.to_host_path(path)
        return await asyncio.to_thread(os.path.exists, actual_path)

    async def get_mtime(self, path: str) -> float:
        """直接 ``os.path.getmtime``，避免每次 stat 都启 sandbox-exec 子进程。

        本地沙箱本质就是宿主机上的同一个 inode，读取 mtime 不存在隔离语义
        （隔离层只是限制写入与命令执行权限），所以这里走 host 直读，
        和"在 Seatbelt 里跑 ``stat``"等价但 0.3~1s/次 的子进程开销没了。
        """
        await self._ensure_initialized_async()
        actual_path = self.to_host_path(path)
        try:
            if not await asyncio.to_thread(os.path.exists, actual_path):
                return 0
            return float(await asyncio.to_thread(os.path.getmtime, actual_path))
        except Exception as e:
            logger.debug(f"LocalSandboxProvider.get_mtime 失败 {path}: {e}")
            return 0

    async def list_directory(
        self,
        path: str,
        include_hidden: bool = False,
    ) -> List[FileInfo]:
        """列出目录内容"""
        await self._ensure_initialized_async()
        actual_path = self.to_host_path(path)
        return await asyncio.to_thread(self._list_directory_sync, actual_path, include_hidden)

    async def ensure_directory(self, path: str) -> None:
        """确保目录存在"""
        await self._ensure_initialized_async()
        actual_path = self.to_host_path(path)
        await asyncio.to_thread(os.makedirs, actual_path, exist_ok=True)

    async def delete_file(self, path: str) -> None:
        """删除文件"""
        await self._ensure_initialized_async()
        actual_path = self.to_host_path(path)
        await asyncio.to_thread(self._delete_path_sync, actual_path)

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
        await self._ensure_initialized_async()
        
        if self._file_system:
            # 转换虚拟路径为宿主机路径
            host_root_path = self.to_host_path(root_path) if root_path else None
            return await self._file_system.get_file_tree_compact(
                include_hidden=include_hidden,
                root_path=host_root_path,
                max_depth=max_depth,
                max_items_per_dir=max_items_per_dir,
            )
        
        # Fallback: 使用基本实现
        return await asyncio.to_thread(
            self._basic_get_file_tree,
            root_path,
            include_hidden,
            max_depth,
            max_items_per_dir,
        )
    
    def _basic_get_file_tree(
        self,
        root_path: Optional[str] = None,
        include_hidden: bool = False,
        max_depth: Optional[int] = None,
        max_items_per_dir: int = 5
    ) -> str:
        """基本的文件树实现（当 filesystem 不可用时）"""
        target_root = (
            self.to_host_path(root_path) if root_path else self.to_host_path(self._sandbox_agent_workspace)
        )
        
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
        await self._ensure_initialized_async()
        
        # 转换沙箱虚拟路径为宿主机路径
        host_dest_path = self.to_host_path(sandbox_dest_path)
        
        try:
            copied = await asyncio.to_thread(
                self._copy_from_host_path_sync,
                host_source_path,
                host_dest_path,
                ignore_patterns,
            )
            if not copied:
                logger.warning(f"源路径不存在: {host_source_path}")
                return False
            
            logger.debug(f"复制成功: {host_source_path} -> {sandbox_dest_path} (实际: {host_dest_path})")
            return True
        except Exception as e:
            logger.error(f"复制失败: {host_source_path} -> {sandbox_dest_path}: {e}")
            return False
