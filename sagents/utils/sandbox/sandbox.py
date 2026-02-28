"""
Sandbox - 沙箱核心类

核心功能：
1. 路径映射：虚拟路径 ↔ 宿主机路径
2. Python 虚拟环境：隔离 Python 依赖
3. 执行模式：subprocess（默认，无 FS 隔离）
"""
import sys
import os
from typing import Dict, Any, Optional, Callable, List

from sagents.utils.logger import logger


class SandboxError(Exception):
    """沙箱错误"""
    pass


class Sandbox:
    """
    沙箱核心类
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
        "/usr/local/lib/node_modules",
    ]
    
    def __init__(self, cpu_time_limit: int = 60, memory_limit_mb: int = 1024, 
                 allowed_paths: Optional[List[str]] = None, 
                 host_workspace: Optional[str] = None, 
                 virtual_workspace: str = "/sage-workspace", 
                 linux_isolation_mode: str = 'auto', 
                 macos_isolation_mode: str = 'subprocess'):
        logger.info(f"初始化沙箱 Sandbox")
        logger.info(f"  平台: {sys.platform}")
        logger.info(f"  host_workspace: {host_workspace}")
        logger.info(f"  virtual_workspace: {virtual_workspace}")
        
        self.linux_isolation_mode = self._resolve_linux_mode(linux_isolation_mode)
        self.macos_isolation_mode = macos_isolation_mode
        
        if sys.platform == 'darwin':
            self.isolation_mode = self.macos_isolation_mode
        else:
            self.isolation_mode = self.linux_isolation_mode
            
        logger.info(f"  隔离模式: {self.isolation_mode}")
        
        self.limits = {
            'cpu_time': cpu_time_limit,
            'memory': memory_limit_mb * 1024 * 1024,
            'allowed_paths': list(set((allowed_paths or []) + self.DEFAULT_ALLOWED_PATHS))
        }
        
        self.host_workspace = host_workspace
        self.virtual_workspace = virtual_workspace
        self.file_system = None
        self.sandbox_dir = None
        self.venv_dir = None
        self.isolation = None
        
        # 始终创建 SandboxFileSystem
        # 当 host_path == virtual_workspace 时，创建"无沙箱功能的沙箱"
        from sagents.utils.sandbox.filesystem import SandboxFileSystem
        
        # host_workspace 是必填参数
        # 检查是否与 virtual_workspace 相同
        if host_workspace == virtual_workspace:
            # 相同时，创建"无沙箱功能的沙箱"（禁用路径映射，不创建 venv，不初始化 isolation）
            self.file_system = SandboxFileSystem(
                host_path=host_workspace, 
                virtual_path=virtual_workspace,
                enable_path_mapping=False
            )
            self.sandbox_dir = None
            self.venv_dir = None
            self.isolation = None
        else:
            # 不同时，创建正常沙箱（启用路径映射，创建 venv，初始化 isolation）
            self.file_system = SandboxFileSystem(
                host_path=host_workspace, 
                virtual_path=virtual_workspace,
                enable_path_mapping=True
            )
            if host_workspace not in self.limits['allowed_paths']:
                self.limits['allowed_paths'].append(host_workspace)
            
            self.sandbox_dir = os.path.join(host_workspace, ".sandbox")
            self.venv_dir = os.path.join(self.sandbox_dir, "venv")
            os.makedirs(self.sandbox_dir, exist_ok=True)
            self._ensure_venv()
            self._init_isolation()
        
        logger.info(f"沙箱初始化完成")
        
    def _resolve_linux_mode(self, mode: str) -> str:
        if mode != 'auto':
            return mode
        result = os.system('which bwrap > /dev/null 2>&1')
        if result == 0:
            return 'bwrap'
        return 'subprocess'
    
    def _ensure_venv(self):
        if not os.path.exists(self.venv_dir):
            import venv
            logger.info(f"创建虚拟环境: {self.venv_dir}")
            os.makedirs(os.path.dirname(self.venv_dir), exist_ok=True)
            venv.create(self.venv_dir, with_pip=True)
    
    def _init_isolation(self):
        from sagents.utils.sandbox.isolation import SubprocessIsolation, SeatbeltIsolation, BwrapIsolation
        
        logger.info(f"初始化隔离策略: {self.isolation_mode}")
        
        if not self.host_workspace:
            self.isolation = None
            return
            
        if self.isolation_mode == 'subprocess':
            self.isolation = SubprocessIsolation(
                venv_dir=self.venv_dir,
                host_workspace=self.host_workspace,
                limits=self.limits
            )
        elif self.isolation_mode == 'seatbelt':
            self.isolation = SeatbeltIsolation(
                venv_dir=self.venv_dir,
                host_workspace=self.host_workspace,
                limits=self.limits,
                allowed_paths=self.limits['allowed_paths'],
                sandbox_dir=self.sandbox_dir
            )
        elif self.isolation_mode == 'bwrap':
            self.isolation = BwrapIsolation(
                venv_dir=self.venv_dir,
                host_workspace=self.host_workspace,
                limits=self.limits,
                virtual_workspace=self.virtual_workspace
            )
        else:
            logger.warning(f"未知的隔离模式: {self.isolation_mode}，使用 subprocess")
            self.isolation = SubprocessIsolation(
                venv_dir=self.venv_dir,
                host_workspace=self.host_workspace,
                limits=self.limits
            )
            
        logger.info(f"隔离策略初始化完成: {type(self.isolation).__name__}")
    
    def get_venv_python(self) -> Optional[str]:
        """获取沙箱 venv 的 Python 路径"""
        import sys
        if self.venv_dir:
            venv_python = os.path.join(self.venv_dir, 'bin', 'python')
            if os.path.exists(venv_python):
                return venv_python
        # 没有沙箱时，返回系统 Python
        return sys.executable
    
    def get_cwd(self) -> str:
        """获取当前工作目录（宿主机路径）"""
        if self.host_workspace:
            return self.host_workspace
        return os.getcwd()
    
    def wrap_command_with_cwd_capture(self, command: str, process_id: str) -> str:
        """包装命令以捕获 CWD"""
        # 不需要捕获 CWD，直接返回原命令
        return command
    
    def update_cwd_from_output(self, stdout: str, process_id: str) -> str:
        """从输出中更新 CWD"""
        return stdout
    
    def _map_to_host(self, obj: Any) -> Any:
        """将虚拟路径映射到宿主机路径"""
        if self.file_system:
            if isinstance(obj, str):
                return self.file_system.map_text_to_host(obj)
            elif isinstance(obj, dict):
                result = {}
                for k, v in obj.items():
                    if isinstance(v, str):
                        result[k] = self.file_system.map_text_to_host(v)
                    else:
                        result[k] = v
                return result
            return obj
        return obj
    
    def _map_to_virtual(self, obj: Any) -> Any:
        """将宿主机路径映射到虚拟路径"""
        if self.file_system:
            if isinstance(obj, str):
                return self.file_system.map_text_to_virtual(obj)
            elif isinstance(obj, dict):
                result = {}
                for k, v in obj.items():
                    if isinstance(v, str):
                        result[k] = self.file_system.map_text_to_virtual(v)
                    else:
                        result[k] = v
                return result
            return obj
        return obj
    
    async def run_tool(self, tool_func: Callable, kwargs: Dict[str, Any], tool_obj: Any = None) -> Any:
        """
        运行工具函数（异步版本）。
        """
        import asyncio
        logger.info(f"[Sandbox.run_tool] 开始执行")
        
        # 映射路径
        host_kwargs = self._map_to_host(kwargs)
        
        # 如果没有 tool_func，返回错误
        if tool_func is None:
            raise SandboxError("未提供 tool_func")
        
        # 检查是否是 bound method
        if hasattr(tool_func, '__self__'):
            # bound method
            func_to_call = tool_func
        else:
            # 需要获取或创建实例
            tool_class = getattr(tool_func, '__objclass__', None)
            if tool_class:
                # 创建实例
                instance = tool_class()
                func_to_call = tool_func.__get__(instance)
            else:
                raise SandboxError("tool_func 无法调用，需要 bound method 或提供 tool_obj")
        
        # 检查是否是 coroutine function
        is_async = asyncio.iscoroutinefunction(func_to_call)
        
        # 使用沙箱 venv 的 Python 环境执行
        if self.venv_dir and os.path.exists(self.venv_dir):
            result = await self._run_with_venv(func_to_call, host_kwargs, is_async)
        else:
            # 没有 venv，直接调用
            if is_async:
                result = await func_to_call(**host_kwargs)
            else:
                result = func_to_call(**host_kwargs)
        
        # 将返回结果中的路径映射回虚拟路径
        return self._map_to_virtual(result)
    
    async def _run_with_venv(self, tool_func: Callable, kwargs: Dict[str, Any], is_async: bool = False) -> Any:
        """在沙箱 venv 环境中执行工具函数（异步版本）"""
        import asyncio
        import os as _os
        
        # 保存原始环境变量
        original_path = _os.environ.get('PATH', '')
        original_virtenv = _os.environ.get('VIRTUAL_ENV', '')
        
        try:
            # 设置环境变量使用沙箱 venv
            venv_bin = _os.path.join(self.venv_dir, 'bin')
            _os.environ['PATH'] = venv_bin + ':' + original_path
            _os.environ['VIRTUAL_ENV'] = self.venv_dir
            _os.environ['SANDBOX_PYTHON_PATH'] = _os.path.join(venv_bin, 'python')
            
            logger.info(f"[_run_with_venv] 使用 venv: {self.venv_dir}")
            
            # 执行工具函数
            if is_async:
                result = await tool_func(**kwargs)
            else:
                result = tool_func(**kwargs)
            return result
            
        finally:
            # 恢复原始环境变量
            _os.environ['PATH'] = original_path
            if original_virtenv:
                _os.environ['VIRTUAL_ENV'] = original_virtenv
            else:
                _os.environ.pop('VIRTUAL_ENV', None)
            _os.environ.pop('SANDBOX_PYTHON_PATH', None)
