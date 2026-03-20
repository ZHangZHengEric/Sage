# 沙箱统一化改造方案

## 概述

将现有分散的沙箱使用方式统一为单一接口，支持本地沙箱、远程沙箱（OpenSandbox）和直通模式三种实现，对工具层完全透明。

## 现状分析

### 当前问题

1. **沙箱使用分散**：
   - `SessionContext` 直接操作 `Sandbox` 对象
   - 工具通过 `session_id` 获取 `SessionContext`，再访问 `agent_workspace_sandbox`
   - 路径映射逻辑散落在各处

2. **工具依赖 `session_id`**：
   ```python
   async def execute_shell_command(self, ..., session_id: Optional[str] = None):
       # 通过 session_id 获取沙箱
       sandbox = self._get_sandbox(session_id)
   ```

3. **实现耦合**：
   - 工具直接依赖具体的 `Sandbox` 类
   - 切换远程沙箱需要修改大量工具代码

## 改造方案

### 1. 核心架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Tool Layer                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │   execute   │  │    file     │  │    code     │  │      ...        │ │
│  │   command   │  │  operation  │  │  execution  │  │                 │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └─────────────────┘ │
│         │                │                │                              │
│         └────────────────┴────────────────┘                              │
│                          │                                               │
│                          ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    Unified Sandbox Interface                     │    │
│  │                     (ISandboxHandle)                             │    │
│  │                                                                  │    │
│  │  • execute_command(cmd, timeout, env_vars) -> CommandResult     │    │
│  │  • execute_python(code, requirements) -> ExecutionResult        │    │
│  │  • execute_javascript(code, packages) -> ExecutionResult        │    │
│  │  • read_file(path) -> str                                       │    │
│  │  • write_file(path, content)                                    │    │
│  │  • list_directory(path) -> List[FileInfo]                       │    │
│  │  • get_workspace_path() -> str                                  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                          │                                               │
│                          ▼                                               │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │                    Sandbox Provider Layer                        │    │
│  │                                                                  │    │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │    │
│  │  │  LocalSandbox   │  │  RemoteSandbox  │  │  Passthrough    │  │    │
│  │  │   Provider      │  │    Provider     │  │   Provider      │  │    │
│  │  │  (本地venv隔离)  │  │  (OpenSandbox)  │  │  (本机直通)      │  │    │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘  │    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         SessionContext                                  │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  self.sandbox: ISandboxHandle  ← 统一的沙箱句柄                  │   │
│  │                                                                  │   │
│  │  工具通过 session_context.sandbox 访问，完全无需关心底层实现      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2. 核心接口设计

```python
# sagents/utils/sandbox/interface.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum

class SandboxType(Enum):
    LOCAL = "local"
    REMOTE = "remote"
    PASSTHROUGH = "passthrough"

@dataclass
class CommandResult:
    success: bool
    stdout: str
    stderr: str
    return_code: int
    execution_time: float
    is_background: bool = False
    process_id: Optional[str] = None

@dataclass
class ExecutionResult:
    success: bool
    output: str
    error: Optional[str] = None
    execution_time: float
    installed_packages: List[str] = None

@dataclass
class FileInfo:
    path: str
    is_file: bool
    is_dir: bool
    size: int
    modified_time: float


class ISandboxHandle(ABC):
    """
    统一沙箱接口 - 所有沙箱实现必须实现此接口
    这是工具层看到的唯一接口
    """
    
    @property
    @abstractmethod
    def sandbox_type(self) -> SandboxType:
        """返回沙箱类型"""
        pass
    
    @property
    @abstractmethod
    def workspace_path(self) -> str:
        """返回工作区路径（虚拟路径）"""
        pass
    
    @property
    @abstractmethod
    def host_workspace_path(self) -> Optional[str]:
        """返回宿主机工作区路径（本地沙箱有效，远程返回None）"""
        pass
    
    # ========== 命令执行 ==========
    
    @abstractmethod
    async def execute_command(
        self, 
        command: str,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
        background: bool = False
    ) -> CommandResult:
        """执行 shell 命令"""
        pass
    
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
        """读取文件内容（path为虚拟路径）"""
        pass
    
    @abstractmethod
    async def write_file(
        self, 
        path: str, 
        content: str, 
        encoding: str = "utf-8",
        mode: str = "overwrite"
    ) -> None:
        """写入文件"""
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
    
    @abstractmethod
    async def ensure_directory(self, path: str) -> None:
        """确保目录存在"""
        pass
    
    @abstractmethod
    async def delete_file(self, path: str) -> None:
        """删除文件"""
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
        """清理沙箱资源"""
        pass
```

### 3. 工具层改造

**改造前（当前代码）**：
```python
class ExecuteCommandTool:
    @tool(...)
    async def execute_shell_command(
        self,
        command: str,
        background: bool = False,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
        session_id: Optional[str] = None,  # ← 需要session_id获取沙箱
    ) -> Dict[str, Any]:
        # 通过session_id获取沙箱
        sandbox = self._get_sandbox(session_id)
        
        # 转换工作目录
        actual_workdir = self._get_actual_workdir(workdir, session_id)
        
        # 执行命令（直接调用subprocess）
        result = await self._execute_shell_command_sync(
            command, background, actual_workdir, timeout, env_vars, session_id
        )
        return result
```

**改造后（统一接口）**：
```python
class ExecuteCommandTool:
    @tool(...)
    async def execute_shell_command(
        self,
        command: str,
        background: bool = False,
        workdir: Optional[str] = None,
        timeout: int = 30,
        env_vars: Optional[Dict[str, str]] = None,
        session_id: Optional[str] = None,  # ← 保持session_id参数
    ) -> Dict[str, Any]:
        """
        执行 shell 命令
        
        Args:
            session_id: 会话ID，用于获取session_context和沙箱
        """
        # 通过session_id获取session_context
        from sagents.session_runtime import get_global_session_manager
        session_manager = get_global_session_manager()
        session = session_manager.get(session_id)
        session_context = session.session_context if session else None
        
        if not session_context:
            return {"success": False, "error": f"Session {session_id} not found"}
        
        # 使用 session_context.sandbox（统一接口）
        sandbox = session_context.sandbox
        
        # 所有沙箱实现统一的execute_command接口
        result = await sandbox.execute_command(
            command=command,
            workdir=workdir,  # 虚拟路径，由沙箱内部处理映射
            timeout=timeout,
            env_vars=env_vars,
            background=background
        )
        
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.return_code,
            "execution_time": result.execution_time,
        }
```

### 4. SessionContext 改造

```python
class SessionContext:
    def __init__(self, session_id: str, user_id: Optional[str] = None, agent_id: Optional[str] = None, ...):
        self.session_id = session_id
        self.user_id = user_id
        self.agent_id = agent_id
        # ... 其他初始化代码 ...
        
    def _init_sandbox_and_file_system(self, use_sandbox: bool = True):
        """
        初始化沙箱环境 - 统一入口
        """
        from sagents.utils.sandbox.factory import SandboxProviderFactory, SandboxConfig
        
        # 方式1: 从环境变量加载默认配置，然后修改
        config = SandboxConfig.from_env()
        config.workspace = self.agent_workspace
        config.virtual_workspace = self.virtual_workspace
        
        # 设置沙箱ID - 优先级: agent_id > user_id > session_id
        # 这样同一个agent或user可以复用同一个沙箱
        config.sandbox_id = config.sandbox_id or self.agent_id or self.user_id or self.session_id
        
        # 方式2: 完全通过代码配置（不从环境变量加载）
        # config = SandboxConfig(
        #     mode=SandboxType.REMOTE,
        #     sandbox_id=self.agent_id,
        #     workspace=self.agent_workspace,
        #     virtual_workspace="/workspace",
        #     remote_server_url="http://opensandbox.internal:8080",
        #     remote_api_key="xxx",
        # )
        
        # 方式3: 从YAML配置文件加载
        # config = SandboxConfig.from_yaml("/path/to/config.yaml")
        
        # 动态添加额外的路径映射（运行时配置）
        # 例如：根据用户请求动态挂载特定目录
        if hasattr(self, 'extra_mount_paths'):
            for mp in self.extra_mount_paths:
                config.mount_paths.append(mp)
        
        # 工厂模式创建对应沙箱实现
        self.sandbox: ISandboxHandle = SandboxProviderFactory.create(config)
        
        # 异步初始化
        import asyncio
        asyncio.create_task(self.sandbox.initialize())
        
        logger.info(f"SessionContext: 沙箱初始化完成，类型: {self.sandbox.sandbox_type}, ID: {config.sandbox_id}")
```

### 5. 工厂类 - 统一创建入口

```python
# sagents/utils/sandbox/factory.py

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from .interface import ISandboxHandle, SandboxType
from .providers.local import LocalSandboxProvider
from .providers.remote import RemoteSandboxProvider
from .providers.passthrough import PassthroughSandboxProvider

@dataclass
class MountPath:
    """路径映射配置"""
    host_path: str
    sandbox_path: str
    read_only: bool = False

@dataclass
class SandboxConfig:
    """沙箱配置
    
    配置优先级（从高到低）：
    1. 代码中显式传入的配置
    2. 环境变量
    3. YAML配置文件
    4. 默认值
    """
    
    # ===== 核心配置 =====
    mode: SandboxType = SandboxType.LOCAL
    sandbox_id: Optional[str] = None  # 沙箱ID，用于持久化和识别（user_id/agent_id/session_id）
    
    # ===== 工作区配置 =====
    workspace: str = "."  # 宿主机工作区根目录
    virtual_workspace: str = "/sage-workspace"  # 沙箱内虚拟工作区路径
    
    # ===== 路径映射配置 =====
    mount_paths: List[MountPath] = field(default_factory=list)  # 额外的路径映射
    
    # ===== 本地沙箱配置 =====
    cpu_time_limit: int = 300
    memory_limit_mb: int = 4096
    allowed_paths: Optional[List[str]] = None
    linux_isolation_mode: str = "subprocess"
    macos_isolation_mode: str = "subprocess"
    
    # ===== 远程沙箱配置 =====
    remote_provider: str = "opensandbox"  # 远程沙箱提供者: opensandbox | kubernetes | firecracker | custom
    remote_server_url: Optional[str] = None
    remote_api_key: Optional[str] = None
    remote_image: str = "opensandbox/code-interpreter:v1.0.2"
    remote_timeout: int = 1800
    remote_persistent: bool = True  # 是否持久化沙箱
    remote_sandbox_ttl: int = 3600  # 沙箱存活时间（秒）
    remote_provider_config: Dict[str, Any] = field(default_factory=dict)  # 特定提供者的额外配置
    
    @classmethod
    def from_env(cls) -> "SandboxConfig":
        """从环境变量加载配置"""
        import os
        
        mode_str = os.environ.get("SAGE_SANDBOX_MODE", "local").lower()
        mode = SandboxType(mode_str)
        
        # 解析路径映射环境变量
        # 格式: "/host/path1:/sandbox/path1,/host/path2:/sandbox/path2"
        mount_paths = []
        mount_paths_env = os.environ.get("SAGE_SANDBOX_MOUNT_PATHS", "")
        if mount_paths_env:
            for mapping in mount_paths_env.split(","):
                if ":" in mapping:
                    host_path, sandbox_path = mapping.split(":", 1)
                    mount_paths.append(MountPath(
                        host_path=host_path.strip(),
                        sandbox_path=sandbox_path.strip(),
                        read_only=False
                    ))
        
        return cls(
            mode=mode,
            sandbox_id=os.environ.get("SAGE_SANDBOX_ID"),
            workspace=os.environ.get("SAGE_SANDBOX_WORKSPACE", "."),
            virtual_workspace=os.environ.get("SAGE_SANDBOX_VIRTUAL_WORKSPACE", "/sage-workspace"),
            mount_paths=mount_paths,
            # 本地配置
            cpu_time_limit=int(os.environ.get("SAGE_LOCAL_CPU_TIME_LIMIT", "300")),
            memory_limit_mb=int(os.environ.get("SAGE_LOCAL_MEMORY_LIMIT_MB", "4096")),
            linux_isolation_mode=os.environ.get("SAGE_LOCAL_LINUX_ISOLATION", "subprocess"),
            macos_isolation_mode=os.environ.get("SAGE_LOCAL_MACOS_ISOLATION", "subprocess"),
            # 远程配置
            remote_provider=os.environ.get("SAGE_REMOTE_PROVIDER", "opensandbox"),
            remote_server_url=os.environ.get("OPENSANDBOX_URL"),
            remote_api_key=os.environ.get("OPENSANDBOX_API_KEY"),
            remote_image=os.environ.get("OPENSANDBOX_IMAGE", "opensandbox/code-interpreter:v1.0.2"),
            remote_timeout=int(os.environ.get("OPENSANDBOX_TIMEOUT", "1800")),
        )
    
    @classmethod
    def from_yaml(cls, config_path: str) -> "SandboxConfig":
        """从YAML配置文件加载"""
        import yaml
        
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        sandbox_config = config.get('sandbox', {})
        
        # 解析路径映射
        mount_paths = []
        for mp in sandbox_config.get('mount_paths', []):
            mount_paths.append(MountPath(
                host_path=mp['host_path'],
                sandbox_path=mp['sandbox_path'],
                read_only=mp.get('read_only', False)
            ))
        
        return cls(
            mode=SandboxType(sandbox_config.get('mode', 'local')),
            sandbox_id=sandbox_config.get('sandbox_id'),
            workspace=sandbox_config.get('workspace', '.'),
            virtual_workspace=sandbox_config.get('virtual_workspace', '/sage-workspace'),
            mount_paths=mount_paths,
            # 本地配置
            cpu_time_limit=sandbox_config.get('local', {}).get('cpu_time_limit', 300),
            memory_limit_mb=sandbox_config.get('local', {}).get('memory_limit_mb', 4096),
            linux_isolation_mode=sandbox_config.get('local', {}).get('linux_isolation_mode', 'subprocess'),
            macos_isolation_mode=sandbox_config.get('local', {}).get('macos_isolation_mode', 'subprocess'),
            # 远程配置
            remote_provider=sandbox_config.get('remote', {}).get('provider', 'opensandbox'),
            remote_server_url=sandbox_config.get('remote', {}).get('server_url'),
            remote_api_key=sandbox_config.get('remote', {}).get('api_key'),
            remote_image=sandbox_config.get('remote', {}).get('image', 'opensandbox/code-interpreter:v1.0.2'),
            remote_timeout=sandbox_config.get('remote', {}).get('timeout', 1800),
            remote_persistent=sandbox_config.get('remote', {}).get('persistent', True),
            remote_sandbox_ttl=sandbox_config.get('remote', {}).get('sandbox_ttl', 3600),
            remote_provider_config=sandbox_config.get('remote', {}).get('provider_config', {}),
        )
```

### 5.5 工厂类 - 统一创建入口

```python
# sagents/utils/sandbox/factory.py

from typing import Dict, Any, Optional
import uuid
from .interface import ISandboxHandle, SandboxType
from .config import SandboxConfig, MountPath
from .providers.local import LocalSandboxProvider
from .providers.remote import RemoteSandboxProvider
from .providers.passthrough import PassthroughSandboxProvider

class SandboxProviderFactory:
    """
    沙箱工厂 - 统一创建沙箱实例
    
    支持多种远程沙箱提供者，通过配置选择:
    - opensandbox: OpenSandbox (默认)
    - kubernetes: Kubernetes Pod
    - firecracker: Firecracker MicroVM
    - custom: 自定义提供者
    """
    
    # 本地和直通模式提供者
    _providers: Dict[SandboxType, type] = {
        SandboxType.LOCAL: LocalSandboxProvider,
        SandboxType.PASSTHROUGH: PassthroughSandboxProvider,
    }
    
    # 远程沙箱提供者映射
    _remote_providers: Dict[str, type] = {
        "opensandbox": None,  # 延迟导入避免循环依赖
        "kubernetes": None,
        "firecracker": None,
    }
    
    @classmethod
    def _get_remote_provider(cls, provider_name: str) -> type:
        """获取远程沙箱提供者类（延迟导入）"""
        if provider_name not in cls._remote_providers:
            raise ValueError(f"Unknown remote provider: {provider_name}")
        
        if cls._remote_providers[provider_name] is None:
            # 延迟导入
            if provider_name == "opensandbox":
                from .providers.remote.opensandbox import OpenSandboxProvider
                cls._remote_providers[provider_name] = OpenSandboxProvider
            elif provider_name == "kubernetes":
                from .providers.remote.kubernetes import KubernetesSandboxProvider
                cls._remote_providers[provider_name] = KubernetesSandboxProvider
            elif provider_name == "firecracker":
                from .providers.remote.firecracker import FirecrackerSandboxProvider
                cls._remote_providers[provider_name] = FirecrackerSandboxProvider
        
        return cls._remote_providers[provider_name]
    
    @classmethod
    def create(cls, config: Optional[SandboxConfig] = None) -> ISandboxHandle:
        """
        创建沙箱实例
        
        Usage:
            # 从环境变量创建
            sandbox = SandboxProviderFactory.create()
            
            # 指定配置创建
            config = SandboxConfig(mode=SandboxType.REMOTE)
            sandbox = SandboxProviderFactory.create(config)
            
            # 使用特定远程提供者
            config = SandboxConfig(
                mode=SandboxType.REMOTE,
                remote_provider="kubernetes",
                remote_provider_config={"namespace": "sage-sandbox"}
            )
            sandbox = SandboxProviderFactory.create(config)
        """
        if config is None:
            config = SandboxConfig.from_env()
        
        # 确保有沙箱ID
        sandbox_id = config.sandbox_id or str(uuid.uuid4())
        
        # 根据模式创建对应实例
        if config.mode == SandboxType.LOCAL:
            return LocalSandboxProvider(
                sandbox_id=sandbox_id,
                host_workspace=config.workspace,
                virtual_workspace=config.virtual_workspace,
                mount_paths=config.mount_paths,
                cpu_time_limit=config.cpu_time_limit,
                memory_limit_mb=config.memory_limit_mb,
                allowed_paths=config.allowed_paths,
                linux_isolation_mode=config.linux_isolation_mode,
                macos_isolation_mode=config.macos_isolation_mode
            )
        
        elif config.mode == SandboxType.REMOTE:
            # 根据 remote_provider 选择具体的远程沙箱实现
            provider_class = cls._get_remote_provider(config.remote_provider)
            
            # 构建通用参数
            common_kwargs = {
                "sandbox_id": sandbox_id,
                "workspace_mount": config.workspace,
                "mount_paths": config.mount_paths,
                "timeout": timedelta(seconds=config.remote_timeout),
            }
            
            # 根据提供者类型添加特定参数
            if config.remote_provider == "opensandbox":
                if not config.remote_server_url:
                    raise ValueError("OpenSandbox requires server_url")
                return provider_class(
                    **common_kwargs,
                    server_url=config.remote_server_url,
                    api_key=config.remote_api_key,
                    image=config.remote_image,
                    persistent=config.remote_persistent,
                    sandbox_ttl=config.remote_sandbox_ttl,
                    **config.remote_provider_config
                )
            
            elif config.remote_provider == "kubernetes":
                return provider_class(
                    **common_kwargs,
                    namespace=config.remote_provider_config.get("namespace", "default"),
                    image=config.remote_image,
                    resources=config.remote_provider_config.get("resources", {}),
                    **{k: v for k, v in config.remote_provider_config.items() 
                       if k not in ["namespace", "resources"]}
                )
            
            elif config.remote_provider == "firecracker":
                return provider_class(
                    **common_kwargs,
                    microvm_config=config.remote_provider_config.get("microvm_config", {}),
                    **{k: v for k, v in config.remote_provider_config.items() 
                       if k != "microvm_config"}
                )
            
            else:
                # 自定义提供者，传递所有配置
                return provider_class(
                    **common_kwargs,
                    **config.remote_provider_config
                )
        
        else:  # PASSTHROUGH
            return PassthroughSandboxProvider(
                sandbox_id=sandbox_id,
                workspace=config.workspace,
                mount_paths=config.mount_paths,
            )
    
    @classmethod
    def register_local_provider(cls, mode: SandboxType, provider_class: type):
        """注册本地/直通模式提供者"""
        cls._providers[mode] = provider_class
    
    @classmethod
    def register_remote_provider(cls, name: str, provider_class: type):
        """注册远程沙箱提供者
        
        Args:
            name: 提供者名称，如 "opensandbox", "kubernetes"
            provider_class: 提供者类，必须继承 RemoteSandboxProvider
        """
        cls._remote_providers[name] = provider_class
```

### 6. 三种沙箱实现

#### 6.1 本地沙箱（LocalSandboxProvider）

```python
class LocalSandboxProvider(ISandboxHandle):
    """本地沙箱实现 - 适配现有的 Sandbox 类"""
    
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
        macos_isolation_mode: str = "subprocess"
    ):
        self.sandbox_id = sandbox_id
        self._host_workspace = host_workspace
        self._virtual_workspace = virtual_workspace
        self._mount_paths = mount_paths or []
        
        # 复用现有的 Sandbox 实现
        self._sandbox = Sandbox(
            host_workspace=host_workspace,
            virtual_workspace=virtual_workspace,
            cpu_time_limit=cpu_time_limit,
            memory_limit_mb=memory_limit_mb,
            allowed_paths=allowed_paths,
            linux_isolation_mode=linux_isolation_mode,
            macos_isolation_mode=macos_isolation_mode
        )
        
        # 添加额外的路径映射
        for mp in self._mount_paths:
            self._sandbox.file_system.add_mapping(mp.sandbox_path, mp.host_path)
    
    async def execute_command(self, command: str, workdir: Optional[str] = None, ...) -> CommandResult:
        """使用现有的 ExecuteCommandTool 逻辑"""
        from sagents.tool.impl.execute_command_tool import ExecuteCommandTool
        
        tool = ExecuteCommandTool()
        actual_workdir = self._map_workdir(workdir)
        
        result = await tool.execute_shell_command(
            command=command,
            background=background,
            workdir=actual_workdir,
            timeout=timeout,
            env_vars=env_vars,
            session_id=None  # 不需要session_id，直接使用沙箱
        )
        
        return CommandResult(...)
    
    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """使用现有的 SandboxFileSystem"""
        host_path = self.to_host_path(path)
        return self._sandbox.file_system.read_file(host_path, encoding)
```

#### 6.2 远程沙箱提供者基类

```python
# sagents/utils/sandbox/providers/remote/base.py

from abc import abstractmethod
from ..interface import ISandboxHandle, SandboxType

class RemoteSandboxProvider(ISandboxHandle):
    """远程沙箱提供者基类"""
    
    def __init__(
        self,
        sandbox_id: str,
        workspace_mount: Optional[str] = None,
        mount_paths: Optional[List[MountPath]] = None,
        timeout: timedelta = timedelta(minutes=30),
    ):
        self.sandbox_id = sandbox_id
        self.workspace_mount = workspace_mount
        self.mount_paths = mount_paths or []
        self.timeout = timeout
        self._workspace_path = "/sage-workspace"
        self._is_initialized = False
    
    @property
    def sandbox_type(self) -> SandboxType:
        return SandboxType.REMOTE
    
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
        import os
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
```

#### 6.2.1 OpenSandbox 实现

```python
# sagents/utils/sandbox/providers/remote/opensandbox.py

from .base import RemoteSandboxProvider

class OpenSandboxProvider(RemoteSandboxProvider):
    """OpenSandbox 远程沙箱实现"""
    
    def __init__(
        self,
        sandbox_id: str,
        server_url: str,
        api_key: Optional[str] = None,
        image: str = "opensandbox/code-interpreter:v1.0.2",
        timeout: timedelta = timedelta(minutes=30),
        workspace_mount: Optional[str] = None,
        mount_paths: Optional[List[MountPath]] = None,
        persistent: bool = True,
        sandbox_ttl: int = 3600,
    ):
        super().__init__(sandbox_id, workspace_mount, mount_paths, timeout)
        self.server_url = server_url
        self.api_key = api_key
        self.image = image
        self.persistent = persistent
        self.sandbox_ttl = sandbox_ttl
        self._sdk = None
    
    async def initialize(self) -> None:
        """初始化 OpenSandbox 远程沙箱"""
        from opensandbox import Sandbox as OSSandbox
        from opensandbox.models import Mount
        
        # 构建挂载配置
        mounts = []
        
        # 工作区挂载
        if self.workspace_mount:
            mounts.append(Mount(
                source=self.workspace_mount,
                target=self._workspace_path,
                type="bind"
            ))
        
        # 额外的路径映射
        for mp in self.mount_paths:
            mounts.append(Mount(
                source=mp.host_path,
                target=mp.sandbox_path,
                type="bind",
                read_only=mp.read_only
            ))
        
        # 如果持久化且已有沙箱ID，尝试连接已有沙箱
        if self.persistent and self.sandbox_id:
            try:
                self._sdk = await OSSandbox.get(
                    self.sandbox_id,
                    server_url=self.server_url,
                    api_key=self.api_key,
                )
                logger.info(f"OpenSandboxProvider: 复用已有沙箱 {self.sandbox_id}")
                self._is_initialized = True
                return
            except Exception as e:
                logger.warning(f"OpenSandboxProvider: 无法复用沙箱 {self.sandbox_id}, 创建新沙箱: {e}")
        
        # 创建新沙箱
        self._sdk = await OSSandbox.create(
            image=self.image,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
            timeout=self.timeout,
            mounts=mounts if mounts else None,
            labels={
                "sandbox_id": self.sandbox_id,
                "persistent": str(self.persistent),
            } if self.sandbox_id else None,
        )
        
        self._is_initialized = True
        logger.info(f"OpenSandboxProvider: 沙箱初始化完成 {self.sandbox_id}")
    
    async def execute_command(self, command: str, ...) -> CommandResult:
        """在远程沙箱执行命令"""
        if not self._is_initialized:
            await self.initialize()
        
        async with self._sdk:
            execution = await self._sdk.commands.run(command, timeout=timeout)
            
            return CommandResult(
                success=execution.exit_code == 0,
                stdout="\n".join([log.text for log in execution.logs.stdout]),
                stderr="\n".join([log.text for log in execution.logs.stderr]),
                return_code=execution.exit_code,
                execution_time=execution.duration
            )
    
    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """从远程沙箱读取文件"""
        if not self._is_initialized:
            await self.initialize()
        
        async with self._sdk:
            return await self._sdk.files.read_file(path)
    
    async def upload_file(self, host_path: str, sandbox_path: str) -> None:
        """上传文件到远程沙箱"""
        if not self._is_initialized:
            await self.initialize()
        
        from opensandbox.models import WriteEntry
        
        with open(host_path, 'rb') as f:
            content = f.read()
        
        async with self._sdk:
            await self._sdk.files.write_files([
                WriteEntry(path=sandbox_path, data=content, mode=644)
            ])
        
        logger.debug(f"OpenSandboxProvider: 上传文件 {host_path} -> {sandbox_path}")
    
    async def download_file(self, sandbox_path: str, host_path: str) -> None:
        """从远程沙箱下载文件"""
        if not self._is_initialized:
            await self.initialize()
        
        async with self._sdk:
            content = await self._sdk.files.read_file(sandbox_path)
        
        # 确保目录存在
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        
        with open(host_path, 'wb') as f:
            f.write(content)
        
        logger.debug(f"OpenSandboxProvider: 下载文件 {sandbox_path} -> {host_path}")
    
    async def cleanup(self) -> None:
        """清理沙箱资源 - 断开连接，不删除沙箱
        
        远程沙箱保持运行状态，通过 sandbox_id 可以重新连接
        """
        if self._sdk:
            if self.persistent:
                # 持久化沙箱：仅断开连接，保持运行
                logger.info(f"OpenSandboxProvider: 断开连接，保持沙箱 {self.sandbox_id} 运行")
                # 可以在这里调用API更新沙箱TTL
            else:
                # 非持久化沙箱：删除
                logger.info(f"OpenSandboxProvider: 删除沙箱 {self.sandbox_id}")
                await self._sdk.kill()
            self._sdk = None
            self._is_initialized = False
    
    async def kill(self) -> None:
        """强制删除沙箱"""
        if self._sdk:
            logger.info(f"OpenSandboxProvider: 强制删除沙箱 {self.sandbox_id}")
            await self._sdk.kill()
            self._sdk = None
            self._is_initialized = False
```

#### 6.2.2 其他远程沙箱实现示例

```python
# sagents/utils/sandbox/providers/remote/kubernetes.py

from .base import RemoteSandboxProvider

class KubernetesSandboxProvider(RemoteSandboxProvider):
    """Kubernetes 远程沙箱实现"""
    
    def __init__(
        self,
        sandbox_id: str,
        namespace: str = "default",
        image: str = "python:3.11-slim",
        timeout: timedelta = timedelta(minutes=30),
        workspace_mount: Optional[str] = None,
        mount_paths: Optional[List[MountPath]] = None,
        resources: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(sandbox_id, workspace_mount, mount_paths, timeout)
        self.namespace = namespace
        self.image = image
        self.resources = resources or {}
        self._pod_name = None
    
    async def initialize(self) -> None:
        """在 K8s 中创建 Pod"""
        # 使用 kubernetes client 创建 Pod
        # ...
        pass
    
    async def execute_command(self, command: str, ...) -> CommandResult:
        """在 K8s Pod 中执行命令"""
        # 使用 kubectl exec 或 kubernetes client
        # ...
        pass


# sagents/utils/sandbox/providers/remote/firecracker.py

from .base import RemoteSandboxProvider

class FirecrackerSandboxProvider(RemoteSandboxProvider):
    """Firecracker 微虚拟机沙箱实现"""
    
    def __init__(
        self,
        sandbox_id: str,
        microvm_config: Dict[str, Any],
        timeout: timedelta = timedelta(minutes=30),
        workspace_mount: Optional[str] = None,
        mount_paths: Optional[List[MountPath]] = None,
    ):
        super().__init__(sandbox_id, workspace_mount, mount_paths, timeout)
        self.microvm_config = microvm_config
        self._vm_id = None
    
    async def initialize(self) -> None:
        """创建 Firecracker 微虚拟机"""
        # 使用 Firecracker API 创建 VM
        # ...
        pass
```

#### 6.3 直通模式（PassthroughSandboxProvider）

```python
class PassthroughSandboxProvider(ISandboxHandle):
    """直通模式 - 直接在本机执行，无隔离"""
    
    def __init__(
        self,
        sandbox_id: str,
        workspace: str = ".",
        mount_paths: Optional[List[MountPath]] = None,
    ):
        self.sandbox_id = sandbox_id
        self._workspace = os.path.abspath(workspace)
        self._mount_paths = mount_paths or []
        # 路径映射表，支持动态修改
        self._dynamic_mounts: Dict[str, str] = {}
    
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
                return os.path.join(host_path, rel_path)
        
        # 默认工作区映射
        if virtual_path.startswith("/sage-workspace"):
            rel_path = virtual_path[len("/sage-workspace"):].lstrip("/")
            return os.path.join(self._workspace, rel_path)
        
        return virtual_path
    
    async def execute_command(self, command: str, ...) -> CommandResult:
        """直接在本机执行命令"""
        import subprocess
        
        actual_workdir = self.to_host_path(workdir) if workdir else self._workspace
        
        if background:
            process = subprocess.Popen(...)
            return CommandResult(success=True, ...)
        else:
            result = subprocess.run(command, shell=True, cwd=actual_workdir, ...)
            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                ...
            )
    
    async def read_file(self, path: str, encoding: str = "utf-8") -> str:
        """直接读取文件"""
        actual_path = self.to_host_path(path)
        with open(actual_path, 'r', encoding=encoding) as f:
            return f.read()
```

### 7. 配置方式

#### 7.1 环境变量

```bash
# ===== 沙箱模式配置 =====
export SAGE_SANDBOX_MODE=remote          # local | remote | passthrough
export SAGE_SANDBOX_ID=                  # 沙箱ID，用于沙箱持久化和识别
                                         # 可以是 user_id, agent_id 或 session_id

# ===== 工作区路径配置 =====
export SAGE_SANDBOX_WORKSPACE=./sage_sessions      # 宿主机工作区根目录
export SAGE_SANDBOX_VIRTUAL_WORKSPACE=/sage-workspace  # 沙箱内虚拟工作区路径

# ===== 本地沙箱配置 =====
export SAGE_LOCAL_CPU_TIME_LIMIT=300     # CPU时间限制（秒）
export SAGE_LOCAL_MEMORY_LIMIT_MB=4096   # 内存限制（MB）
export SAGE_LOCAL_LINUX_ISOLATION=bwrap  # Linux隔离模式: subprocess | bwrap
export SAGE_LOCAL_MACOS_ISOLATION=subprocess  # macOS隔离模式: subprocess

# ===== 远程沙箱提供者选择 =====
export SAGE_REMOTE_PROVIDER=opensandbox    # 远程沙箱提供者: opensandbox | kubernetes | firecracker

# ===== 远程沙箱配置 (OpenSandbox) =====
export OPENSANDBOX_URL=http://opensandbox.internal:8080  # OpenSandbox服务地址
export OPENSANDBOX_API_KEY=xxx                           # API密钥
export OPENSANDBOX_IMAGE=opensandbox/code-interpreter:v1.0.2  # 默认镜像
export OPENSANDBOX_TIMEOUT=1800                          # 超时时间（秒）

# ===== 远程沙箱配置 (Kubernetes) =====
export K8S_NAMESPACE=sage-sandbox          # K8s命名空间
export K8S_IMAGE=python:3.11-slim          # 默认镜像
export K8S_CPU_LIMIT=2                     # CPU限制
export K8S_MEMORY_LIMIT=4Gi                # 内存限制

# ===== 路径映射配置（宿主机路径:沙箱路径） =====
export SAGE_SANDBOX_MOUNT_PATHS="/data:/data,/tmp:/tmp"  # 额外的路径映射，逗号分隔
```

#### 7.2 YAML配置文件

```yaml
# sage_config.yaml
sandbox:
  # 模式: local | remote | passthrough
  mode: "local"
  
  # 沙箱ID - 用于沙箱持久化和识别
  # 可以是 user_id, agent_id 或 session_id
  sandbox_id: "${SAGE_SANDBOX_ID}"
  
  # 工作区配置
  workspace: "./sage_sessions"
  virtual_workspace: "/sage-workspace"
  
  # 路径映射配置
  mount_paths:
    - host_path: "/data"
      sandbox_path: "/data"
      read_only: false
    - host_path: "/tmp"
      sandbox_path: "/tmp"
      read_only: false
  
  # 本地沙箱配置
  local:
    cpu_time_limit: 300
    memory_limit_mb: 4096
    linux_isolation_mode: "bwrap"  # subprocess | bwrap
    macos_isolation_mode: "subprocess"
  
  # 远程沙箱配置
  remote:
    # 远程沙箱提供者: opensandbox | kubernetes | firecracker
    provider: "opensandbox"
    
    # OpenSandbox 配置
    server_url: "http://opensandbox.internal:8080"
    api_key: "${OPENSANDBOX_API_KEY}"
    image: "opensandbox/code-interpreter:v1.0.2"
    timeout: 1800
    persistent: true           # 是否持久化沙箱
    sandbox_ttl: 3600         # 沙箱存活时间（秒）
    
    # 提供者特定配置
    provider_config:
      # OpenSandbox 特定配置
      network_mode: "bridge"
      
      # Kubernetes 特定配置 (当 provider: kubernetes 时)
      # namespace: "sage-sandbox"
      # resources:
      #   cpu_limit: "2"
      #   memory_limit: "4Gi"
      
      # Firecracker 特定配置 (当 provider: firecracker 时)
      # microvm_config:
      #   vcpu_count: 2
      #   mem_size_mib: 4096
```

#### 7.3 配置优先级

配置优先级（从高到低）：
1. 代码中显式传入的配置
2. 环境变量
3. YAML配置文件
4. 默认值

#### 7.4 远程沙箱状态保持

**远程沙箱通过 `sandbox_id` 保持状态，无需关闭**：

```python
# 通过相同的 sandbox_id 复用沙箱，保持状态
config = SandboxConfig(
    mode=SandboxType.REMOTE,
    sandbox_id="user_123",  # 相同的 ID 会复用已有沙箱
    remote_provider="opensandbox",
    remote_server_url="http://opensandbox.internal:8080",
    persistent=True,  # 保持沙箱存活
)

sandbox = SandboxProviderFactory.create(config)
await sandbox.initialize()

# 第一次：安装依赖
await sandbox.execute_command("pip install numpy pandas")

# ... 一段时间后，通过相同的 sandbox_id 连接 ...

# 第二次：依赖仍然存在
result = await sandbox.execute_command("python -c 'import numpy; print(numpy.__version__)'")
# 输出: 1.24.0 (之前安装的版本)
```

**远程沙箱生命周期管理**：

| 操作 | 说明 |
|-----|------|
| `initialize()` | 连接已有沙箱或创建新沙箱 |
| `cleanup()` | 断开连接（不删除沙箱） |
| `kill()` | 强制删除沙箱 |

**注意**：远程沙箱保持运行状态，不会自动关闭，直到调用 `kill()` 或超过 TTL。

#### 7.5 动态路径映射

**本地沙箱和直通模式**支持运行时动态添加/移除路径映射：

```python
# 获取沙箱实例
sandbox = session_context.sandbox

# 动态添加路径映射（仅本地和直通模式支持）
if hasattr(sandbox, 'add_mount'):
    sandbox.add_mount(
        host_path="/tmp/user_data_123",
        sandbox_path="/data"
    )

# 现在可以在沙箱中访问 /data 目录
result = await sandbox.execute_command("ls -la /data")

# 使用完成后可以移除映射
if hasattr(sandbox, 'remove_mount'):
    sandbox.remove_mount("/data")
```

**远程沙箱的文件访问**：

远程沙箱不支持动态路径映射，但可以通过文件 API 访问：

```python
# 上传文件到远程沙箱
await sandbox.upload_file(
    host_path="/local/data.csv",
    sandbox_path="/workspace/data.csv"
)

# 在远程沙箱中处理
result = await sandbox.execute_command("python process.py /workspace/data.csv")

# 下载结果
await sandbox.download_file(
    sandbox_path="/workspace/result.json",
    host_path="/local/result.json"
)
```

**使用场景**：
- 本地/直通模式：开发调试，需要频繁挂载不同目录
- 远程沙箱：生产环境，预配置好路径或使用文件 API

## 迁移步骤

### 阶段 1：创建统一接口（1-2天）
1. 创建 `ISandboxHandle` 接口
2. 创建 `LocalSandboxProvider` 适配现有代码
3. 创建 `SandboxProviderFactory` 工厂类
4. 修改 `SessionContext` 使用工厂创建沙箱

### 阶段 2：改造工具层（2-3天）
1. 修改 `ToolManager` 注入 `session_context` 而非 `session_id`
2. 逐个改造工具，使用 `session_context.sandbox` 接口
3. 保持向后兼容（支持旧版 `session_id` 参数）

### 阶段 3：添加远程支持（1-2天）
1. 实现 `RemoteSandboxProvider`
2. 添加配置支持
3. 测试远程沙箱模式

### 阶段 4：清理和优化（1天）
1. 移除旧的 `sandbox_utils.py` 中的冗余函数
2. 统一错误处理
3. 完善日志记录

## 优势

| 优势 | 说明 |
|-----|------|
| **统一接口** | 工具层只看到 `ISandboxHandle`，无需关心底层实现 |
| **灵活切换** | 通过配置即可切换本地/远程/直通模式 |
| **渐进迁移** | 可以逐个工具迁移，不影响其他功能 |
| **易于测试** | 直通模式便于本地开发和调试 |
| **扩展性强** | 可以轻松添加新的沙箱提供者 |
| **类型安全** | 使用接口和类型提示，IDE 支持好 |

## 风险与缓解

| 风险 | 缓解措施 |
|-----|---------|
| 改造范围大 | 分阶段进行，保持向后兼容 |
| 性能影响 | 本地沙箱保持现有实现，无额外开销 |
| 远程沙箱延迟 | 仅对耗时操作使用远程沙箱，简单操作使用本地 |
| 调试困难 | 直通模式支持本地调试 |
