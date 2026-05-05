"""
沙箱接口定义 - 统一沙箱抽象层

所有沙箱实现必须实现 ISandboxHandle 接口
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


class SandboxType(Enum):
    """沙箱类型"""
    LOCAL = "local"           # 本地沙箱（venv + subprocess/bwrap/seatbelt）
    REMOTE = "remote"         # 远程沙箱（OpenSandbox、K8s、Firecracker 等）
    PASSTHROUGH = "passthrough"  # 直通模式（本机执行，无隔离）


@dataclass
class CommandResult:
    """命令执行结果"""
    success: bool
    stdout: str
    stderr: str
    return_code: int
    execution_time: float


@dataclass
class ExecutionResult:
    """代码执行结果"""
    success: bool
    output: str
    execution_time: float
    error: Optional[str] = None
    installed_packages: Optional[List[str]] = None


@dataclass
class FileInfo:
    """文件信息"""
    path: str
    is_file: bool
    is_dir: bool
    size: int
    modified_time: float


class ISandboxHandle(ABC):
    """
    统一沙箱接口 - 所有沙箱实现必须实现此接口
    
    这是工具层看到的唯一接口，无论底层是本地还是远程沙箱
    """
    
    @property
    @abstractmethod
    def sandbox_type(self) -> SandboxType:
        """返回沙箱类型"""
        pass
    
    @property
    @abstractmethod
    def sandbox_id(self) -> str:
        """返回沙箱ID"""
        pass
    
    @property
    @abstractmethod
    def workspace_path(self) -> str:
        """返回工作区路径（虚拟路径）"""
        pass
    
    @property
    @abstractmethod
    def host_workspace_path(self) -> Optional[str]:
        """返回宿主机工作区路径（本地沙箱有效，远程返回None）
        
        注意：这是 sandbox_agent_workspace 的宿主机路径
        """
        pass
    
    @property
    @abstractmethod
    def volume_mounts(self) -> List[Any]:
        """返回卷挂载配置列表"""
        pass
    
    # ========== 命令执行 ==========
    
    @abstractmethod
    async def execute_command(
        self,
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> CommandResult:
        """
        执行 shell 命令

        Args:
            command: 命令字符串
            workdir: 工作目录（虚拟路径）
            timeout: 超时时间（秒）
            env_vars: 额外环境变量
        """
        pass
    
    # ========== 后台命令（跨平台） ==========

    async def start_background(
        self,
        command: str,
        workdir: Optional[str] = None,
        env_vars: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """以后台方式启动命令；返回 ``{task_id, pid, log_path}``。

        默认实现抛出 ``NotImplementedError``，由具体 Provider 覆写。
        本机执行的 Provider（Passthrough/Local）应直接走 ``HostBackgroundRunner``，
        远端 Provider 可以通过 sandbox API 实现。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 不支持 start_background；"
            "请使用 Passthrough/Local 沙箱或在 Provider 中实现该原语。"
        )

    async def read_background_output(self, task_id: str, max_bytes: int = 8192) -> str:
        """读取后台任务输出尾部。默认实现返回空串。"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 不支持 read_background_output"
        )

    async def get_background_output_size(self, task_id: str) -> Optional[int]:
        """返回后台任务日志文件的总字节数；不支持/不存在时返回 ``None``。

        上层用它来判断 ``read_background_output`` 的返回是否被截断，
        以及向用户/agent 显式给出 "已显示 last N of M bytes" 的提示。
        """
        return None

    async def read_background_output_range(
        self, task_id: str, offset: int = 0, max_bytes: int = 1 << 20
    ) -> Tuple[str, int]:
        """从 ``offset`` 字节起向后读到末尾（最多 ``max_bytes`` 字节），返回 ``(text, new_offset)``。

        语义：
        - 用于工具实时过程通道（``tool_progress``）做"零重复、零丢失"的纯增量推送。
        - 调用方维护 ``offset``：第一次传 0，之后用上次返回的 ``new_offset``。
        - 没有新输出（``offset >= size``）返回 ``("", offset)``。

        默认实现 ``raise NotImplementedError``：
        上层调用方（如 ``execute_command_tool._wait_for_finish``）应捕获异常，
        回退到 ``read_background_output`` 的 tail diff 模式。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} 不支持 read_background_output_range；"
            "上层将回退到 tail diff 模式"
        )

    async def is_background_alive(self, task_id: str) -> bool:
        """后台任务是否仍在运行。默认实现 False。"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 不支持 is_background_alive"
        )

    async def get_background_exit_code(self, task_id: str) -> Optional[int]:
        """已退出则返回 exit code，否则 ``None``。"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 不支持 get_background_exit_code"
        )

    async def kill_background(self, task_id: str, force: bool = False) -> bool:
        """终止后台任务；force=True 表示直接 SIGKILL/TerminateProcess。"""
        raise NotImplementedError(
            f"{self.__class__.__name__} 不支持 kill_background"
        )

    async def cleanup_background(self, task_id: str) -> None:
        """从注册表中移除任务（关闭日志句柄等）；默认 no-op。"""
        return None

    def supports_background(self) -> bool:
        """便于上层在不抛异常的情况下判断当前 sandbox 是否支持原生后台。"""
        return False

    # ========== 代码执行 ==========
    
    @abstractmethod
    async def execute_python(
        self,
        code: str,
        requirements: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60
    ) -> ExecutionResult:
        """执行 Python 代码"""
        pass
    
    @abstractmethod
    async def execute_javascript(
        self,
        code: str,
        packages: Optional[List[str]] = None,
        workdir: Optional[str] = None,
        timeout: int = 60
    ) -> ExecutionResult:
        """执行 JavaScript 代码"""
        pass
    
    # ========== 文件操作 ==========
    
    @abstractmethod
    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """
        读取文件内容
        
        Args:
            path: 文件路径（虚拟路径）
            encoding: 文件编码
        """
        pass
    
    @abstractmethod
    async def write_file(
        self, 
        path: str, 
        content: str, 
        encoding: str = "utf-8",
        mode: str = "overwrite"
    ) -> None:
        """
        写入文件
        
        Args:
            path: 文件路径（虚拟路径）
            content: 文件内容
            encoding: 文件编码
            mode: 写入模式 (overwrite | append)
        """
        pass
    
    @abstractmethod
    async def file_exists(self, path: str) -> bool:
        """检查文件是否存在"""
        pass
    
    @abstractmethod
    async def list_directory(
        self, 
        path: str,
        include_hidden: bool = False
    ) -> List[FileInfo]:
        """列出目录内容"""
        pass

    async def get_mtime(self, path: str) -> float:
        """
        获取文件/目录的修改时间（Unix 时间戳）。

        默认实现通过 ``list_directory(parent)`` 找到对应条目。
        各 provider 可按需 override 以避免无谓开销
        （如本地沙箱可直接 ``os.path.getmtime``，远端沙箱可走原生 stat API）。

        约定：路径不存在或读取失败时返回 ``0``。
        """
        import os as _os

        parent = _os.path.dirname(path.rstrip("/")) or path
        target = path.rstrip("/")
        try:
            entries = await self.list_directory(parent, include_hidden=True)
        except Exception:
            return 0
        for entry in entries:
            if entry.path.rstrip("/") == target:
                return float(entry.modified_time or 0)
        return 0
    
    @abstractmethod
    async def ensure_directory(self, path: str) -> None:
        """确保目录存在"""
        pass
    
    @abstractmethod
    async def delete_file(self, path: str) -> None:
        """删除文件"""
        pass
    
    @abstractmethod
    async def get_file_tree(
        self,
        root_path: Optional[str] = None,
        include_hidden: bool = False,
        max_depth: Optional[int] = None,
        max_items_per_dir: int = 5
    ) -> str:
        """
        获取文件树结构（紧凑格式）
        
        Args:
            root_path: 根路径（虚拟路径），None 表示使用工作区根目录
            include_hidden: 是否包含隐藏文件
            max_depth: 最大遍历深度，None 表示无限制
            max_items_per_dir: 每个目录最多显示的项目数
            
        Returns:
            文件树字符串，使用缩进表示层级
            
        Example:
            workspace/
              file1.txt
              file2.txt
              dir1/
                subfile1.txt
        """
        pass
    
    # ========== 路径转换 ==========
    
    @abstractmethod
    def to_host_path(self, virtual_path: str) -> str:
        """虚拟路径转宿主机路径"""
        pass
    
    @abstractmethod
    def to_virtual_path(self, host_path: str) -> str:
        """宿主机路径转虚拟路径"""
        pass
    
    # ========== 生命周期 ==========
    
    @abstractmethod
    async def initialize(self) -> None:
        """初始化沙箱"""
        pass
    
    @abstractmethod
    async def cleanup(self) -> None:
        """清理沙箱资源（断开连接，不删除沙箱）"""
        pass
    
    # ========== 访问控制 ==========
    
    @abstractmethod
    def add_allowed_paths(self, paths: List[str]) -> None:
        """
        添加允许访问的路径列表
        
        Args:
            paths: 宿主机路径列表
        """
        pass
    
    @abstractmethod
    def remove_allowed_paths(self, paths: List[str]) -> None:
        """
        移除允许访问的路径列表
        
        Args:
            paths: 宿主机路径列表
        """
        pass
    
    @abstractmethod
    def get_allowed_paths(self) -> List[str]:
        """获取当前允许访问的路径列表"""
        pass
    
    # ========== 批量文件操作 ==========
    
    @abstractmethod
    async def copy_from_host(
        self,
        host_source_path: str,
        sandbox_dest_path: str,
        ignore_patterns: Optional[List[str]] = None
    ) -> bool:
        """
        从宿主机复制文件/目录到沙箱
        
        Args:
            host_source_path: 宿主机源路径
            sandbox_dest_path: 沙箱目标路径（虚拟路径）
            ignore_patterns: 忽略的文件模式列表（如 ['*.pyc', '__pycache__']）
            
        Returns:
            bool: 是否成功
            
        Note:
            - 本地沙箱：直接复制文件
            - 远程沙箱：通过 API 上传文件
        """
        pass
