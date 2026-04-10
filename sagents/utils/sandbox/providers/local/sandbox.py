"""
Sandbox - 沙箱核心类

核心功能：
1. Python 虚拟环境：隔离 Python 依赖
2. 执行模式：bwrap/seatbelt（默认优先，缺失时可退回 subprocess）

注意：路径映射由外部通过 volume_mounts 配置，内部不做任何额外添加
"""
import sys
import os
import asyncio
import threading
from typing import Dict, Any, Optional, Callable, List

from sagents.utils.logger import logger
from sagents.utils.sandbox.config import VolumeMount
from sagents.utils.common_utils import get_system_python_path, resolve_python_venv_dir, file_lock


class SandboxError(Exception):
    """沙箱错误"""
    pass


class Sandbox:
    """
    沙箱核心类

    注意：内部不做任何路径映射添加，所有映射必须在 volume_mounts 中明确定义
    """

    DEFAULT_ALLOWED_PATHS = [
        "/usr/share/zoneinfo",
        "/etc/localtime",
        "/etc/mime.types",
        "/etc/apache2/mime.types",
        "/usr/local/etc/mime.types",
        "~/.npm",
        "~/.cache",
        "~/.config",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "~/.sage",
        "/usr/local/lib/node_modules",
    ]

    if sys.platform == 'win32':
        DEFAULT_ALLOWED_PATHS.extend([
            os.environ.get('SystemRoot', 'C:\\Windows'),
            os.environ.get('ProgramFiles', 'C:\\Program Files'),
            os.environ.get('ProgramFiles(x86)', 'C:\\Program Files (x86)'),
            os.environ.get('USERPROFILE', 'C:\\Users\\Default'),
            os.path.join(os.environ.get('USERPROFILE', ''), '.sage'),
        ])

    def __init__(self, cpu_time_limit: int = 60, memory_limit_mb: int = 1024,
                 allowed_paths: Optional[List[str]] = None,
                 sandbox_agent_workspace: Optional[str] = None,
                 volume_mounts: Optional[List[VolumeMount]] = None,
                 linux_isolation_mode: str = 'auto',
                 macos_isolation_mode: str = 'seatbelt'):
        logger.debug(f"初始化沙箱 Sandbox")
        logger.debug(f"  平台: {sys.platform}")
        logger.debug(f"  sandbox_agent_workspace: {sandbox_agent_workspace}")
        logger.debug(f"  volume_mounts: {len(volume_mounts) if volume_mounts else 0}")

        self.linux_isolation_mode = self._resolve_linux_mode(linux_isolation_mode)
        self.macos_isolation_mode = macos_isolation_mode

        if sys.platform == 'darwin':
            self.isolation_mode = self.macos_isolation_mode
        else:
            self.isolation_mode = self.linux_isolation_mode

        logger.debug(f"  隔离模式: {self.isolation_mode}")

        self.limits = {
            'cpu_time': cpu_time_limit,
            'memory': memory_limit_mb * 1024 * 1024,
            'allowed_paths': list(set((allowed_paths or []) + self.DEFAULT_ALLOWED_PATHS))
        }

        # workspace 配置
        self.sandbox_agent_workspace = sandbox_agent_workspace
        self.volume_mounts = volume_mounts or []

        self.file_system = None
        self.sandbox_dir = None
        self.venv_dir = None
        self.isolation = None

        # 初始化文件系统和隔离
        self._init_file_system()
        self._init_venv_and_isolation()

        logger.debug(f"沙箱初始化完成")

    def _init_file_system(self):
        """初始化文件系统，使用 volume_mounts"""
        from .filesystem import SandboxFileSystem
        from sagents.utils.sandbox.config import VolumeMount

        # 构建 volume_mounts
        if self.volume_mounts:
            # 使用提供的 volume_mounts
            volume_mounts = self.volume_mounts
        elif self.sandbox_agent_workspace:
            # 如果没有 volume_mounts，使用 sandbox_agent_workspace 作为直通模式
            volume_mounts = [VolumeMount(
                host_path=self.sandbox_agent_workspace,
                mount_path=self.sandbox_agent_workspace
            )]
        else:
            # 默认使用当前目录
            volume_mounts = [VolumeMount(host_path=".", mount_path=".")]

        # 创建文件系统
        self.file_system = SandboxFileSystem(volume_mounts=volume_mounts)

    def _init_venv_and_isolation(self):
        """初始化虚拟环境和隔离"""
        if not self.sandbox_agent_workspace:
            # 没有 workspace，不创建 venv 和 isolation
            self.sandbox_dir = None
            self.venv_dir = None
            self.isolation = None
            return

        # 在 desktop 共享模式下使用统一 venv，否则仍使用 workspace 本地 venv
        self.venv_dir = resolve_python_venv_dir(self.sandbox_agent_workspace)
        self.sandbox_dir = (
            os.path.join(self.sandbox_agent_workspace, ".sandbox")
            if self.sandbox_agent_workspace else None
        )
        if self.sandbox_dir:
            os.makedirs(self.sandbox_dir, exist_ok=True)

        # 在后台异步创建 venv
        self._ensure_venv_async()

        # 初始化隔离
        self._init_isolation()

    def _resolve_linux_mode(self, mode: str) -> str:
        if sys.platform == 'win32':
             return 'subprocess'
        if mode != 'auto':
            return mode
        result = os.system('which bwrap > /dev/null 2>&1')
        if result == 0:
            return 'bwrap'
        return 'subprocess'

    def _ensure_venv_async(self):
        """在后台异步创建虚拟环境，不阻塞初始化"""
        if not self.venv_dir or os.path.exists(self.venv_dir):
            return  # 已存在，无需创建

        def create_venv_in_background():
            try:
                import venv

                lock_path = os.path.join(os.path.dirname(self.venv_dir), ".venv.lock")
                with file_lock(lock_path):
                    if os.path.exists(self.venv_dir):
                        return

                    logger.info(f"后台创建虚拟环境: {self.venv_dir}")
                    os.makedirs(os.path.dirname(self.venv_dir), exist_ok=True)

                    # 获取正确的 Python 解释器路径（处理 PyInstaller 打包环境）
                    system_python = get_system_python_path()
                    if not system_python:
                        logger.error("无法找到系统 Python 解释器")
                        return

                    logger.info(f"使用 Python 解释器创建 venv: {system_python}")
                    venv.create(self.venv_dir, with_pip=True, executable=system_python)
                    logger.info(f"虚拟环境创建完成: {self.venv_dir}")
            except Exception as e:
                logger.error(f"创建虚拟环境失败: {self.venv_dir}, 错误: {e}")

        # 在后台线程中创建 venv
        thread = threading.Thread(target=create_venv_in_background, daemon=True)
        thread.start()
        logger.info(f"虚拟环境创建任务已启动（后台）: {self.venv_dir}")

    def _init_isolation(self):
        from .isolation import SubprocessIsolation, SeatbeltIsolation, BwrapIsolation

        logger.info(f"初始化隔离策略: {self.isolation_mode}")

        if not self.sandbox_agent_workspace:
            self.isolation = None
            return

        if self.isolation_mode == 'subprocess':
            self.isolation = SubprocessIsolation(
                venv_dir=self.venv_dir,
                host_workspace=self.sandbox_agent_workspace,
                limits=self.limits
            )
        elif self.isolation_mode == 'seatbelt':
            self.isolation = SeatbeltIsolation(
                venv_dir=self.venv_dir,
                host_workspace=self.sandbox_agent_workspace,
                limits=self.limits,
                allowed_paths=self.limits['allowed_paths'],
                sandbox_dir=self.sandbox_dir
            )
        elif self.isolation_mode == 'bwrap':
            self.isolation = BwrapIsolation(
                venv_dir=self.venv_dir,
                host_workspace=self.sandbox_agent_workspace,
                limits=self.limits,
                virtual_workspace=self.sandbox_agent_workspace
            )
        else:
            logger.warning(f"未知的隔离模式: {self.isolation_mode}，使用 subprocess")
            self.isolation = SubprocessIsolation(
                venv_dir=self.venv_dir,
                host_workspace=self.sandbox_agent_workspace,
                limits=self.limits
            )

        logger.info(f"隔离策略初始化完成: {type(self.isolation).__name__}")

    def get_venv_python(self) -> Optional[str]:
        """获取沙箱 venv 的 Python 路径"""
        if self.venv_dir:
            if sys.platform == 'win32':
                venv_python = os.path.join(self.venv_dir, 'Scripts', 'python.exe')
            else:
                venv_python = os.path.join(self.venv_dir, 'bin', 'python')

            if os.path.exists(venv_python):
                return venv_python
        # 没有沙箱时，使用 get_system_python_path 处理 PyInstaller 打包环境
        return get_system_python_path()

    def get_cwd(self) -> str:
        """获取当前工作目录"""
        if self.sandbox_agent_workspace:
            return self.sandbox_agent_workspace
        return os.getcwd()

    def wrap_command_with_cwd_capture(self, command: str, process_id: str) -> str:
        """包装命令以捕获 CWD"""
        return command

    def update_cwd_from_output(self, stdout: str, process_id: str) -> str:
        """从输出中更新 CWD"""
        return stdout

    async def run_tool(self, tool_func: Callable, kwargs: Dict[str, Any], tool_obj: Any = None) -> Any:
        """
        运行工具函数（异步版本）。
        """
        import asyncio
        logger.debug(f"[Sandbox.run_tool] 开始执行")

        # 如果没有 tool_func，返回错误
        if tool_func is None:
            raise SandboxError("未提供 tool_func")

        # 检查是否是 bound method
        if hasattr(tool_func, '__self__'):
            func_to_call = tool_func
        else:
            tool_class = getattr(tool_func, '__objclass__', None)
            if tool_class:
                instance = tool_class()
                func_to_call = tool_func.__get__(instance)
            else:
                raise SandboxError("tool_func 无法调用，需要 bound method 或提供 tool_obj")

        is_async = asyncio.iscoroutinefunction(func_to_call)

        # 使用沙箱 venv 的 Python 环境执行
        if self.venv_dir and os.path.exists(self.venv_dir):
            result = await self._run_with_venv(func_to_call, kwargs, is_async)
        else:
            if is_async:
                result = await func_to_call(**kwargs)
            else:
                result = func_to_call(**kwargs)

        return result

    async def _run_with_venv(self, tool_func: Callable, kwargs: Dict[str, Any], is_async: bool = False) -> Any:
        """在沙箱 venv 环境中执行工具函数（异步版本）"""
        import os as _os
        import sys as _sys

        original_path = _os.environ.get('PATH', '')

        try:
            if _sys.platform == 'win32':
                venv_bin = _os.path.join(self.venv_dir, 'Scripts')
            else:
                venv_bin = _os.path.join(self.venv_dir, 'bin')

            _os.environ['PATH'] = venv_bin + _os.pathsep + original_path

            logger.info(f"[_run_with_venv] 使用 venv: {self.venv_dir}")

            if is_async:
                result = await tool_func(**kwargs)
            else:
                result = tool_func(**kwargs)
            return result

        finally:
            _os.environ['PATH'] = original_path
