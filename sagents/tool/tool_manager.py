from typing import Dict, Any, List, Optional, Union
from .tool_base import _DISCOVERED_TOOLS
from .mcp_tool_base import _DISCOVERED_MCP_TOOLS
from .tool_schema import (
    convert_spec_to_openai_format,
    ToolSpec,
    McpToolSpec,
    SageMcpToolSpec,
    SseServerParameters,
    StreamableHttpServerParameters,
)
from sagents.utils.logger import logger
from sagents.context.session_context import SessionContext
from sagents.context.messages.message_manager import MessageManager
from sagents.utils.serialization import make_serializable
from pathlib import Path
import json
import asyncio
from mcp import StdioServerParameters
from mcp import Tool
import traceback
import time
import os
import sys
import shutil
import subprocess


def _check_command_exists(command: str) -> bool:
    """检查命令是否存在"""
    return shutil.which(command) is not None


async def _install_uvx() -> bool:
    """自动安装 uvx (uv package manager)
    
    Returns:
        bool: 安装是否成功
    """
    try:
        logger.info("[Auto Install] uvx not found, attempting to install uv...")
        
        # 检查是否已经安装了 uv
        if _check_command_exists("uv"):
            logger.info("[Auto Install] uv is already installed")
            return True
        
        # 尝试使用 pip 安装 uv
        logger.info("[Auto Install] Installing uv via pip...")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "uv",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode == 0:
            logger.info("[Auto Install] Successfully installed uv via pip")
            # 刷新 PATH
            os.environ["PATH"] = os.environ.get("PATH", "")
            return True
        else:
            logger.error(f"[Auto Install] Failed to install uv via pip: {stderr.decode()}")
            
            # 尝试使用官方安装脚本
            logger.info("[Auto Install] Trying to install uv via official installer...")
            import platform
            system = platform.system().lower()
            
            if system == "darwin" or system == "linux":
                # macOS 或 Linux
                install_cmd = "curl -LsSf https://astral.sh/uv/install.sh | sh"
                process = await asyncio.create_subprocess_shell(
                    install_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    logger.info("[Auto Install] Successfully installed uv via official installer")
                    # 添加 uv 到 PATH (通常安装在 ~/.local/bin)
                    home = os.path.expanduser("~")
                    uv_bin_path = os.path.join(home, ".local", "bin")
                    if uv_bin_path not in os.environ.get("PATH", ""):
                        os.environ["PATH"] = f"{uv_bin_path}{os.pathsep}{os.environ.get('PATH', '')}"
                    return True
                else:
                    logger.error(f"[Auto Install] Failed to install uv via official installer: {stderr.decode()}")
            
            return False
            
    except Exception as e:
        logger.error(f"[Auto Install] Error during uvx installation: {e}")
        return False


def _ensure_command_available(command: str) -> bool:
    """确保命令可用，如果不存在则尝试安装
    
    Args:
        command: 命令名称 (如 'uvx', 'npx' 等)
        
    Returns:
        bool: 命令是否可用
    """
    if _check_command_exists(command):
        return True
    
    # 特殊处理 uvx/uv
    if command in ["uvx", "uv"]:
        # 异步安装 uv
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，创建新任务
                future = asyncio.ensure_future(_install_uvx())
                # 这里不能直接等待，需要返回 False 让调用者重试
                logger.info(f"[Auto Install] Installation of {command} started in background")
                return False
            else:
                # 如果事件循环未运行，可以直接运行
                return loop.run_until_complete(_install_uvx())
        except Exception as e:
            logger.error(f"[Auto Install] Error ensuring {command} available: {e}")
            return False
    
    return False
try:
    BaseExceptionGroup
except NameError:
    class BaseExceptionGroup(BaseException):
        """Backport for Python < 3.11"""
        pass
from .mcp_proxy import McpProxy

class RegisteredToolList(list):
    """List of registered tools that evaluates to True for backward compatibility."""
    def __bool__(self):
        return True

_GLOBAL_TOOL_MANAGER: Optional["ToolManager"] = None


def get_tool_manager() -> Optional["ToolManager"]:
    return _GLOBAL_TOOL_MANAGER


def set_tool_manager(tm: Optional["ToolManager"]) -> None:
    global _GLOBAL_TOOL_MANAGER
    _GLOBAL_TOOL_MANAGER = tm


def _innermost_exception(exc: BaseException) -> BaseException:
    seen = set()
    cur: BaseException = exc
    while True:
        cur_id = id(cur)
        if cur_id in seen:
            return cur
        seen.add(cur_id)

        if isinstance(cur, BaseExceptionGroup):
            exceptions = getattr(cur, "exceptions", None)
            if exceptions:
                cur = exceptions[0]
                continue

        cause = getattr(cur, "__cause__", None)
        if cause is not None:
            cur = cause
            continue

        context = getattr(cur, "__context__", None)
        if context is not None:
            cur = context
            continue

        return cur


def _innermost_exception_message(exc: BaseException) -> str:
    inner = _innermost_exception(exc)
    msg = str(inner).strip()
    return msg if msg else repr(inner)


def _raise_innermost_exception(exc: BaseException) -> None:
    inner = _innermost_exception(exc)
    if isinstance(inner, Exception):
        raise inner from None
    raise Exception(_innermost_exception_message(inner)) from None


class ToolManager:
    _instance = None

    def __new__(cls, is_auto_discover=True, isolated=False):
        if isolated:
            return super(ToolManager, cls).__new__(cls)
        if cls._instance is None:
            cls._instance = super(ToolManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, is_auto_discover=True, isolated=False):
        """初始化工具管理器"""
        if not isolated and getattr(self, '_initialized', False):
            return

        logger.debug(f"Initializing ToolManager (isolated={isolated})")

        self.tools: Dict[str, Union[ToolSpec, McpToolSpec, SageMcpToolSpec]] = {}
        self._tool_instances: Dict[type, Any] = {}  # 缓存工具实例
        self._mcp_setting_path = None

        if is_auto_discover:
            self.discover_tools_from_path()
            self.discover_builtin_mcp_tools_from_path()
            # self._mcp_setting_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'mcp_servers', 'mcp_setting.json')
            # # 在测试环境中，我们不希望自动发现MCP工具
            # if not os.environ.get('TESTING'):
            #     logger.debug("Not in testing environment, discovering MCP tools")
        
        if not isolated:
            self._initialized = True
            #     asyncio.run(self._discover_mcp_tools(mcp_setting_path=self._mcp_setting_path))
            # else:
            #     logger.debug("In testing environment, skipping MCP tool discovery")

    @classmethod
    def get_instance(cls, is_auto_discover: bool = True) -> "ToolManager":
        tm = get_tool_manager()
        if tm is None:
            tm = ToolManager(is_auto_discover=is_auto_discover)
            set_tool_manager(tm)
        return tm

    async def initialize(self):
        """异步初始化，用于测试环境"""
        logger.info("Asynchronously initializing ToolManager")
        await self._discover_mcp_tools(mcp_setting_path=self._mcp_setting_path)

    def _discover_import_path(self, path=None, root_package="sagents"):
        package_path = Path(path) if path else Path(__file__).parent
        package_path = package_path.resolve()

        # Find root_package in path to determine sys.path and full package name
        current = package_path
        parts = []
        root_found = False
        sys_path_dir = None

        while True:
            parts.insert(0, current.name)
            if current.name == root_package:
                root_found = True
                sys_path_dir = current.parent
                break
            if current.parent == current:  # Reached root
                break
            current = current.parent

        if not root_found:
            # Fallback: treat package_path as the root package
            logger.warning(f"Root package '{root_package}' not found in path {package_path}. Using {package_path.name} as root.")
            sys_path_dir = package_path.parent
            full_package_name = package_path.name
        else:
            full_package_name = ".".join(parts)

        # Add to sys.path
        if sys_path_dir:
            sys_path_str = str(sys_path_dir)
            if sys_path_str not in sys.path:
                sys.path.append(sys_path_str)

        logger.info(f"Discovering tools from package_path: {package_path}, module prefix: {full_package_name}")
        import importlib
        # 遍历 .py 文件
        for py_file in package_path.rglob("*.py"):
            if py_file.name.startswith(("test_", "__")):
                continue
            # 相对路径 + 模块名
            rel_parts = py_file.relative_to(package_path).with_suffix("").parts
            module_name = ".".join([full_package_name, *rel_parts])
            try:
                importlib.import_module(module_name)
            except Exception as e:
                logger.warning(f"Failed to import {module_name}: {e}")

    def discover_builtin_mcp_tools_from_path(self, path: Optional[str] = None):
        """Discover and register built-in MCP tools from mcp_servers directory"""
        if path:
            self._discover_import_path(path=path, root_package="mcp_servers")
        else:
            root_path = Path(__file__).parent.parent.parent
            mcp_servers_path = root_path / "mcp_servers"
            if not mcp_servers_path.exists():
                logger.warning(f"mcp_servers path not found: {mcp_servers_path}")
            else:
                self._discover_import_path(path=mcp_servers_path, root_package="mcp_servers")

        # Register discovered tools
        count = 0
        for module_name, funcs in _DISCOVERED_MCP_TOOLS.items():
            for func in funcs:
                if hasattr(func, '_mcp_tool_spec'):
                    self.register_tool(func._mcp_tool_spec)
                    count += 1

        logger.info(f"Registered {count} built-in MCP tools")

    def discover_tools_from_path(self, path: Optional[str] = None):
        """Auto-discover and register all tools in the tools package
        Args:
            path: Optional custom path to scan for tools. If None, uses package directory.
        """
        if path:
            self._discover_import_path(path=path, root_package="sagents")
        else:
            # 默认情况：直接导入 sagents.tool.impl，由其 __init__.py 控制导出哪些工具
            try:
                import sagents.tool.impl
            except Exception as e:
                logger.warning(f"Failed to import tools in impl package: {e}")

        count = 0
        for funcs in _DISCOVERED_TOOLS.values():
            for func in funcs:
                tool_spec = getattr(func, "_tool_spec", None)
                if not tool_spec:
                    continue
                if tool_spec.name in self.tools:
                    continue
                owner_module = getattr(func, "_tool_owner_module", None)
                owner_qualname = getattr(func, "_tool_owner_qualname", None)
                if owner_module and owner_qualname:
                    module = sys.modules.get(owner_module)
                    if module is None:
                        try:
                            module = importlib.import_module(owner_module)
                        except Exception:
                            module = None
                    if module is not None:
                        target = module
                        for part in owner_qualname.split("."):
                            target = getattr(target, part, None)
                            if target is None:
                                break
                        if isinstance(target, type):
                            func.__objclass__ = target
                if self.register_tool(tool_spec):
                    count += 1
        logger.debug(f"Registered {count} tools from package_path")

    def register_tools_from_object(self, obj: Any) -> List[str]:
        """
        Register tools from an object instance or class.
        Automatically discovers methods decorated with @tool and registers them.
        If an instance is provided, methods are bound to the instance.
        
        Args:
            obj: An object instance or class to scan for tools.
            
        Returns:
            List[str]: List of names of successfully registered tools.
        """
        import inspect
        import copy
        
        registered_tools = []
        logger.debug(f"Discovering tools from object: {obj}")
        
        # Iterate over all members of the object
        for name, member in inspect.getmembers(obj):
            # Check if member has _tool_spec (added by @tool decorator)
            tool_spec = getattr(member, "_tool_spec", None)
            
            # If not found directly, check underlying function for bound methods
            if not tool_spec and hasattr(member, "__func__"):
                tool_spec = getattr(member.__func__, "_tool_spec", None)
                
            if not tool_spec:
                continue
                
            # Skip if tool name already exists (subject to priority logic in register_tool)
            # But here we let register_tool handle the decision
            
            # Handle instance binding
            # If obj is an instance (not a class), we need to ensure the func in spec is bound
            if not inspect.isclass(obj):
                try:
                    # Create a copy of the spec to avoid modifying the original class-level spec
                    new_spec = copy.copy(tool_spec)
                    
                    # member is already a bound method when accessed from instance via inspect.getmembers
                    # Verify it is bound
                    if inspect.ismethod(member) and member.__self__ is obj:
                         new_spec.func = member
                    else:
                        # Fallback or strict check?
                        # If member is not bound but obj is instance, it might be a staticmethod or we need to bind it manually?
                        # inspect.getmembers on instance returns bound methods for regular methods.
                        new_spec.func = member
                        
                    self.register_tool(new_spec)
                    registered_tools.append(new_spec.name)
                except Exception as e:
                    logger.error(f"Failed to register tool '{name}' from object: {e}")
            else:
                # obj is a class
                # We register the unbound method? Or fail?
                # Usually we want to register tools from instances to support state.
                # If it's a class, the method must be static or class method, or handled appropriately.
                # For now, we just try to register as is.
                self.register_tool(tool_spec)
                registered_tools.append(tool_spec.name)
                    
        return registered_tools

    def register_tool(self, tool_spec: Union[ToolSpec, McpToolSpec, SageMcpToolSpec]):
        """Register a tool specification with priority-based replacement

        Priority order (high to low):
        1. McpToolSpec (MCP tools)
        2. SageMcpToolSpec (Built-in MCP tools)
        3. ToolSpec (Local tools)
        """

        if tool_spec.name in self.tools:
            existing_tool = self.tools[tool_spec.name]

            # 定义优先级：MCP > SageMcp > Local
            priority_order = {McpToolSpec: 3, SageMcpToolSpec: 1.5, ToolSpec: 1}

            existing_priority = priority_order.get(type(existing_tool), 0)
            new_priority = priority_order.get(type(tool_spec), 0)

            if new_priority > existing_priority:
                # 新工具优先级更高，替换现有工具
                existing_type = type(existing_tool).__name__
                new_type = type(tool_spec).__name__
                logger.warning(
                    f"Tool '{tool_spec.name}' already exists as {existing_type}, replacing with higher priority {new_type}"
                )

                self.tools[tool_spec.name] = tool_spec
                logger.info(
                    f"Successfully replaced tool: {tool_spec.name} ({existing_type} -> {new_type})"
                )
                return True
            elif new_priority == existing_priority:
                # 相同优先级，保持现有工具
                logger.debug(
                    f"Tool '{tool_spec.name}' already registered with same priority, keeping existing tool"
                )
                return False
            else:
                # 新工具优先级更低，拒绝注册
                existing_type = type(existing_tool).__name__
                new_type = type(tool_spec).__name__
                logger.warning(
                    f"Tool '{tool_spec.name}' registration rejected: existing {existing_type} has higher priority than {new_type}"
                )
                return False

        # 工具不存在，直接注册
        self.tools[tool_spec.name] = tool_spec
        tool_type = type(tool_spec).__name__
        logger.debug(f"Successfully registered new tool: {tool_spec.name} ({tool_type})")
        return True

    async def remove_tool_by_mcp(self, server_name: str) -> bool:
        """
        Remove all tools registered from a specific MCP server.

        Args:
            server_name: Name of the server to remove

        Returns:
            bool: True if any tools were removed, False otherwise
        """
        server_name = server_name.strip()
        removed = False
        try:
            to_delete = []
            for tool_name, spec in self.tools.items():
                # Only McpToolSpec has server_name
                if (
                    isinstance(spec, McpToolSpec)
                    and getattr(spec, "server_name", None) == server_name
                ):
                    to_delete.append(tool_name)
            for tool_name in to_delete:
                del self.tools[tool_name]
                removed = True
                logger.debug(
                    f"Removed MCP tool '{tool_name}' from server '{server_name}'"
                )
            if not removed:
                logger.warning(
                    f"No MCP tools found for server '{server_name}' to remove"
                )
                removed = True
            return removed
        except Exception as e:
            logger.error(f"Failed to remove MCP server '{server_name}': {e}")
            return False

    async def clear_mcp_tools(self) -> int:
        """
        清除所有 MCP 工具（包括 McpToolSpec 和 SageMcpToolSpec）

        Returns:
            int: 被清除的工具数量
        """
        removed_count = 0
        try:
            to_delete = []
            for tool_name, spec in list(self.tools.items()):
                # 清除所有 MCP 相关工具
                if isinstance(spec, (McpToolSpec, SageMcpToolSpec)):
                    to_delete.append(tool_name)

            for tool_name in to_delete:
                del self.tools[tool_name]
                removed_count += 1
                logger.debug(f"Removed MCP tool '{tool_name}'")

            logger.info(f"Cleared {removed_count} MCP tools")
            return removed_count
        except Exception as e:
            logger.error(f"Failed to clear MCP tools: {e}")
            return 0

    async def _discover_mcp_tools(self, mcp_setting_path: Optional[str] = None):
        bool_registered = False
        """Discover and register tools from MCP servers"""
        logger.info(f"Discovering MCP tools from settings file: {mcp_setting_path}")
        if mcp_setting_path is None or not os.path.exists(mcp_setting_path):
            logger.warning(f"MCP setting file not found: {mcp_setting_path}")
            return bool_registered
        try:
            with open(mcp_setting_path) as f:
                mcp_config = json.load(f)
                logger.debug(
                    f"Loaded MCP config with {len(mcp_config.get('mcpServers', {}))} servers"
                )
                logger.debug(f"mcp_config: {mcp_config}")
            for server_name, config in mcp_config.get("mcpServers", {}).items():
                await self.register_mcp_server(server_name, config)
        except Exception as e:
            logger.error(f"Error loading MCP config: {str(e)}")
            return bool_registered
        return bool_registered

    async def register_mcp_server(self, server_name: str, config: dict):
        """Register an MCP server directly with configuration

        Args:
            server_name: Name of the server
            config: Dictionary containing server configuration:
                - For stdio server:
                    - command: Command to start server
                    - args: List of arguments (optional)
                    - env: Environment variables (optional)
                - For SSE server:
                    - sse_url: SSE server URL
        """
        bool_registered = False
        registered_tools = RegisteredToolList()
        logger.info(f"Registering MCP server: {server_name}")
        logger.debug(f"MCP server config: {config}")
        if config.get("disabled", True):
            logger.debug(f"Server {server_name} is disabled, skipping")
            return bool_registered
        server_name = server_name.strip()
        server_params: Optional[Union[StdioServerParameters, SseServerParameters, StreamableHttpServerParameters]] = None
        try:
            protocol_type = "stdio"
            if "sse_url" in config:
                protocol_type = "sse"
            elif "url" in config or "streamable_http_url" in config:
                protocol_type = "streamable_http"
            logger.info(f"Detected protocol type for {server_name}: {protocol_type}")
            
            if "sse_url" in config:
                server_params = SseServerParameters(
                    url=config["sse_url"], api_key=config.get("api_key", None)
                )
            elif "url" in config or "streamable_http_url" in config:
                url_val = config.get("url") or config.get("streamable_http_url")
                if not isinstance(url_val, str):
                    logger.warning(f"Invalid URL for server {server_name}: {url_val}")
                    return False
                server_params = StreamableHttpServerParameters(
                    url=url_val
                )
            else:
                # stdio protocol
                command = config.get("command")
                args = config.get("args", [])
                env = config.get("env", None)
                logger.info(f"Creating StdioServerParameters for {server_name}")
                logger.debug(f"  command: {command}")
                logger.debug(f"  args: {args}")
                logger.debug(f"  env: {env}")
                
                if not command:
                    logger.error(f"Missing 'command' field in config for {server_name}")
                    logger.error(f"Available config keys: {list(config.keys())}")
                    return False
                
                # 检查命令是否存在，如果不存在尝试自动安装
                if not _check_command_exists(command):
                    logger.warning(f"Command '{command}' not found, attempting to install...")
                    if command in ["uvx", "uv"]:
                        # 对于 uvx/uv，尝试异步安装
                        install_success = await _install_uvx()
                        if not install_success:
                            logger.error(f"Failed to install {command}. Please install it manually:")
                            logger.error(f"  curl -LsSf https://astral.sh/uv/install.sh | sh")
                            logger.error(f"  or: pip install uv")
                            return False
                        # 安装成功后，再次检查命令是否存在
                        if not _check_command_exists(command):
                            logger.error(f"Installation completed but '{command}' still not found in PATH")
                            logger.error(f"Please restart the application or check your PATH configuration")
                            return False
                    else:
                        logger.error(f"Command '{command}' not found and auto-installation is not supported")
                        logger.error(f"Please install it manually")
                        return False
                
                server_params = StdioServerParameters(
                    command=command,
                    args=args,
                    env=env,
                )
            mcp_proxy = McpProxy()
            mcp_tools = await mcp_proxy.get_mcp_tools(server_name, server_params)
            for mcp_tool in mcp_tools:
                await self._register_mcp_tool(server_name, mcp_tool, server_params)
                registered_tools.append(mcp_tool)
        except KeyError as e:
            missing_key = str(e).strip("'")
            logger.error(f"Missing required key '{missing_key}' in config for MCP server {server_name}")
            logger.error(f"Full config: {config}")
            return bool_registered
        except Exception as e:
            error_detail = _innermost_exception_message(e)
            logger.error(f"Error registering MCP server {server_name}: {error_detail}")
            logger.error(f"Exception type: {type(e).__name__}")
            logger.error(f"Full config: {config}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return bool_registered
        bool_registered = True
        logger.info(f"Successfully registered MCP server: {server_name}")
        return registered_tools

    async def _register_mcp_tool(
        self,
        server_name: str,
        tool_info: Union[Tool, dict],
        server_params: Union[
            StdioServerParameters, SseServerParameters, StreamableHttpServerParameters
        ],
    ):
        if isinstance(tool_info, Tool):
            tool_info = tool_info.model_dump()
        if not isinstance(tool_info, dict):
            logger.warning(f"Invalid tool info type: {type(tool_info)}")
        logger.debug(
            f"Registering MCP tool: {tool_info['name']} from server: {server_name}"
        )
        """Register a tool from MCP server"""
        if "input_schema" in tool_info:
            input_schema = tool_info.get("input_schema", {})
        else:
            input_schema = tool_info.get("inputSchema", {})

        # 兼容 MCP 的 i18n 元数据来源：优先从 _meta/meta 中读取；其次从顶层键读取；然后从 annotations 中读取；最后从 inputSchema.properties 聚合
        meta = tool_info.get("_meta") or tool_info.get("meta") or {} or tool_info.get("annotations", {}) or {}
        description_i18n = meta.get("description_i18n") or tool_info.get("description_i18n", {})

        # 参数多语言描述聚合
        param_description_i18n = meta.get("param_description_i18n") or tool_info.get("param_description_i18n", {})
        try:
            if not param_description_i18n and isinstance(input_schema.get("properties", {}), dict):
                aggregated: Dict[str, Any] = {}
                for param_name, schema in input_schema.get("properties", {}).items():
                    if isinstance(schema, dict) and isinstance(schema.get("description_i18n"), dict):
                        aggregated[param_name] = schema.get("description_i18n")
                if aggregated:
                    param_description_i18n = aggregated
        except Exception:
            # 保底，避免注册失败
            pass

        tool_spec = McpToolSpec(
            name=tool_info["name"],
            description=tool_info.get("description", ""),
            description_i18n=description_i18n or {},
            param_description_i18n=param_description_i18n or {},
            func=None,
            parameters=input_schema.get("properties", {}),
            required=input_schema.get("required", []),
            server_name=server_name,
            server_params=server_params,
        )
        registered = self.register_tool(tool_spec)
        logger.debug(f"MCP tool {tool_info['name']} registration result: {registered}")

    def get_tool(self, name: str) -> Optional[Union[ToolSpec, McpToolSpec]]:
        """Get a tool by name"""
        logger.debug(f"Getting tool by name: {name}")
        return self.tools.get(name, None)

    def list_tools(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """List all available tools with metadata, supports language filtering via convert_spec_to_openai_format"""
        logger.debug(f"Listing all {len(self.tools)} tools with metadata")

        tools_list: List[Dict[str, Any]] = []
        for tool in self.tools.values():
            spec = convert_spec_to_openai_format(tool, lang=lang, fallback_chain=fallback_chain)
            fn = spec.get("function", {})
            params = fn.get("parameters", {})
            tools_list.append({
                "name": fn.get("name", getattr(tool, "name", "")),
                "description": fn.get("description", getattr(tool, "description", "")),
                "parameters": params.get("properties", {}),
                "required": params.get("required", getattr(tool, "required", [])),
            })
        return tools_list

    def list_tools_simplified(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """List all available tools with simplified metadata, using convert_spec_to_openai_format for i18n"""
        logger.debug(f"Listing all {len(self.tools)} tools with simplified metadata")

        simplified = []
        for tool in self.tools.values():
            spec = convert_spec_to_openai_format(tool, lang=lang, fallback_chain=fallback_chain)
            fn = spec.get("function", {})
            simplified.append({
                "name": fn.get("name", getattr(tool, "name", "")),
                "description": fn.get("description", getattr(tool, "description", "")),
            })
        return simplified

    def list_all_tools_name(self, lang: Optional[str] = None) -> List[str]:
        """List all available tools with name (language param accepted for API consistency)"""
        logger.debug(f"Listing all {len(self.tools)} tools with name")
        return [tool.name for tool in self.tools.values()]

    def list_tools_with_type(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """List tools with type/source info, descriptions and parameters localized via convert_spec_to_openai_format"""
        logger.debug(f"Listing all {len(self.tools)} tools with type information")

        tools_with_type: List[Dict[str, Any]] = []
        for tool in self.tools.values():
            # 类型与来源
            if isinstance(tool, McpToolSpec):
                tool_type = "mcp"
                source = f"MCP Server: {tool.server_name}"
            elif isinstance(tool, SageMcpToolSpec):
                tool_type = "sage_mcp"
                source = f"内置MCP: {tool.server_name}"
            elif isinstance(tool, ToolSpec):
                tool_type = "basic"
                source = "基础工具"
            else:
                tool_type = "unknown"
                source = "未知来源"

            spec = convert_spec_to_openai_format(tool, lang=lang, fallback_chain=fallback_chain)
            fn = spec.get("function", {})
            params = fn.get("parameters", {})

            tools_with_type.append({
                "name": fn.get("name", getattr(tool, "name", "")),
                "description": fn.get("description", getattr(tool, "description", "")),
                "parameters": params.get("properties", {}),
                "type": tool_type,
                "source": source,
            })

        return tools_with_type

    def get_openai_tools(self, lang: Optional[str] = None, fallback_chain: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get OpenAI-compatible function specs, localized via convert_spec_to_openai_format"""
        logger.debug(f"Getting OpenAI tool specifications for {len(self.tools)} tools")

        tools_json: List[Dict[str, Any]] = []
        for tool in self.tools.values():
            tools_json.append(convert_spec_to_openai_format(tool, lang=lang, fallback_chain=fallback_chain))

        return tools_json

    async def run_tool_async(
        self,
        tool_name: str,
        session_context: SessionContext,
        session_id: str = "",
        **kwargs,
    ) -> Any:
        """Execute a tool by name with provided arguments (async version)"""
        execution_start = time.time()
        logger.debug(f"Executing tool: {tool_name} (session: {session_id})")
        logger.debug(f"Tool arguments: {kwargs}")
        
        # Step 1: Tool Lookup
        tool = self.get_tool(tool_name)
        if not tool:
            error_msg = (
                f"Tool '{tool_name}' not found. Available: {list(self.tools.keys())}"
            )
            logger.error(error_msg)
            return self._format_error_response(error_msg, tool_name, "TOOL_NOT_FOUND")

        logger.debug(f"Found tool: {tool_name} (type: {type(tool).__name__})")

        # Step 2: Execute based on tool type (self-call prevention handled at agent level)

        try:
            # Step 3: Execute tool
            if isinstance(tool, McpToolSpec):
                # For MCP tools, session_id is passed explicitly, so remove from kwargs
                kwargs.pop("session_id", None)
                final_result = await self._execute_mcp_tool(tool, session_id, **kwargs)
            elif isinstance(tool, SageMcpToolSpec):
                # Ensure session_id is not in kwargs
                kwargs.pop("session_id", None)
                final_result = await self._execute_standard_tool_async(tool, session_id=session_id, **kwargs)
            elif isinstance(tool, ToolSpec):
                # 检查必填参数
                required_params = getattr(tool, 'required', []) or []
                # session_id 是系统注入的参数，如果不在 kwargs 中但工具需要，不算 missing
                missing_params = [p for p in required_params if p != 'session_id' and (p not in kwargs or kwargs.get(p) is None)]
                if missing_params:
                    # 返回错误信息而不是 raise
                    return json.dumps({
                        "success": False,
                        "error": f"缺少必填参数: {', '.join(missing_params)}",
                        "required_params": required_params,
                        "provided_params": list(kwargs.keys())
                    }, ensure_ascii=False, indent=2)
                
                # Check for sandbox execution
                # Define sandbox tools (can be moved to config later)
                SANDBOX_TOOLS = [
                    "execute_shell_command", 
                    "execute_python_code", 
                    "execute_javascript_code",
                    "file_read", 
                    "file_write", 
                    "search_content_in_file", 
                    "download_file_from_url", 
                    "file_update",
                    "extract_text_from_non_text_file",
                    "todo_read",
                    "todo_write",
                    "analyze_image"
                ]
                
                if tool.name in SANDBOX_TOOLS:
                    try:
                        # Use sandbox if available
                        if hasattr(session_context, 'agent_workspace_sandbox') and session_context.agent_workspace_sandbox:
                            # Check if pip/npm is needed
                            needs_pip = False
                            needs_npm = False
                            if tool.name == "execute_python_code" and kwargs.get("requirement_list"):
                                needs_pip = True
                            elif tool.name == "execute_javascript_code" and kwargs.get("npm_packages"):
                                needs_npm = True
                            elif tool.name == "execute_shell_command":
                                cmd = kwargs.get("command", "")
                                if "pip " in cmd or "pip3 " in cmd:
                                    needs_pip = True
                                if "npm " in cmd or "node " in cmd:
                                    needs_npm = True
                            
                            # Note: pip is automatically available in the sandbox venv
                            # No need to explicitly call ensure_pip()
                            # We might want to ensure npm here too in future if sandbox environment management supports it
                            # session_context.sandbox.ensure_npm() 

                            # Inject session_id if the tool function expects it
                            import inspect
                            func_to_inspect = tool.func
                            
                            has_session_id_param = False
                            
                            # For bound methods, check the bound method's signature directly
                            # Don't unwrap __wrapped__ because we need to see the actual signature
                            # that will be used when calling the method
                            try:
                                sig = inspect.signature(func_to_inspect)
                                has_session_id_param = "session_id" in sig.parameters
                                logger.debug(f"[Sandbox] Checking {tool.name} signature: {list(sig.parameters.keys())}, has_session_id: {has_session_id_param}")
                            except (ValueError, TypeError) as e:
                                logger.debug(f"[Sandbox] Failed to get signature for {tool.name}: {e}")
                                pass
                            
                            # Also check from tool spec as fallback
                            if not has_session_id_param and hasattr(tool, 'parameters') and tool.parameters:
                                has_session_id_param = 'session_id' in tool.parameters
                                logger.debug(f"[Sandbox] Checked tool.parameters for {tool.name}: has_session_id={has_session_id_param}")
                            if not has_session_id_param and hasattr(tool, 'required') and tool.required:
                                has_session_id_param = 'session_id' in tool.required
                                logger.debug(f"[Sandbox] Checked tool.required for {tool.name}: has_session_id={has_session_id_param}")
                            
                            if has_session_id_param:
                                kwargs["session_id"] = session_id
                                logger.debug(f"[Sandbox] Injected session_id for {tool.name}")

                            # Use run_tool which handles path mapping and execution
                            # We pass the function object from the tool spec
                            # And try to pass the tool instance if available (though ToolSpec might not store it directly, 
                            # usually it's bound method if created from class)
                            result = await session_context.agent_workspace_sandbox.run_tool(tool.func, kwargs)
                            
                            # Preserve skill_name for load_skill tool
                            if tool_name == 'load_skill':
                                try:
                                    result_dict = json.loads(result) if isinstance(result, str) else result
                                    # Get skill_name from result_dict, fallback to kwargs (the original input parameter)
                                    skill_name_from_result = result_dict.get("skill_name") or kwargs.get("skill_name", "unknown")
                                    final_result = json.dumps({
                                        "skill_name": skill_name_from_result,
                                        "content": make_serializable(result_dict.get("content", result))
                                    }, ensure_ascii=False, indent=2)
                                except Exception:
                                    final_result = json.dumps({"content": make_serializable(result)}, ensure_ascii=False, indent=2)
                            else:
                                final_result = json.dumps({"content": make_serializable(result)}, ensure_ascii=False, indent=2)

                            # Sync context for ToDo tools after successful sandbox execution
                            if tool.name in ["todo_write", "todo_read", "todo_update"]:
                                try:
                                    # logger.info(f"Syncing session_context for {tool.name} after sandbox execution")
                                    # Get tool class directly
                                    from sagents.tool.impl.todo_tool import ToDoTool
                                    
                                    # Read directly from sandbox file system
                                    if hasattr(session_context, 'agent_workspace_sandbox') and session_context.agent_workspace_sandbox:
                                         # Use the same path logic as todo_write to ensure consistency
                                         ws = session_context.agent_workspace_sandbox.file_system
                                         filename = f"TODO_LIST_{session_id}.md"
                                         if isinstance(ws, str):
                                             host_todo_path = os.path.join(ws, filename)
                                         elif hasattr(ws, 'host_path'):  # SandboxFileSystem
                                             host_todo_path = os.path.join(ws.host_path, filename)
                                         else:
                                             # Fallback to agent_workspace
                                             host_todo_path = os.path.join(session_context.agent_workspace, filename)
                                         
                                         if host_todo_path and os.path.exists(host_todo_path):
                                             with open(host_todo_path, 'r', encoding='utf-8') as f:
                                                 content = f.read()
                                             
                                             tasks = ToDoTool.parse_todo_list(content)
                                             
                                             # Update main process memory directly
                                             if not hasattr(session_context, 'system_context') or not isinstance(session_context.system_context, dict):
                                                 logger.warning("session_context.system_context is invalid")
                                             else:
                                                 if 'todo_list' not in session_context.system_context:
                                                     session_context.system_context.update({'todo_list': []})
                                                 session_context.system_context.update({'todo_list': tasks})
                                                 logger.info(f"Session context synced successfully via file read. Tasks: {len(tasks)}")
                                         else:
                                             # File was deleted (all tasks completed), clear todo_list in session_context
                                             if hasattr(session_context, 'system_context') and isinstance(session_context.system_context, dict):
                                                 session_context.system_context.update({'todo_list': []})
                                                 logger.info(f"Todo file deleted, cleared todo_list in session context")
                                             else:
                                                 logger.warning(f"Could not locate todo_list.md at {host_todo_path}")
                                except Exception as e:
                                    logger.warning(f"Failed to sync session context after sandbox execution: {e}")

                        else:
                             # Fallback to standard execution if no sandbox found (should not happen in new setup)
                            logger.warning(f"No sandbox found in session_context for {tool.name}, executing directly.")
                            # Remove session_id from kwargs to avoid duplication, _execute_standard_tool_async will inject it
                            kwargs.pop("session_id", None)
                            final_result = await self._execute_standard_tool_async(tool, session_id=session_id, **kwargs)

                    except Exception as e:
                        logger.error(f"Sandbox execution failed for {tool.name}, aborting.")
                        raise e
                else:
                    # Remove session_id from kwargs to avoid duplication, _execute_standard_tool_async will inject it
                    kwargs.pop("session_id", None)
                    final_result = await self._execute_standard_tool_async(tool, session_id=session_id, **kwargs)
            else:
                error_msg = f"Unknown tool type: {type(tool).__name__}"
                logger.error(error_msg)
                return self._format_error_response(
                    error_msg, tool_name, "UNKNOWN_TOOL_TYPE"
                )

            # Step 4: Validate Result (for non-streaming tools)
            execution_time = time.time() - execution_start
            logger.debug(
                f"Tool '{tool_name}' completed successfully in {execution_time:.2f}s"
            )

            # Validate JSON format
            is_valid, validation_msg = self._validate_json_response(
                final_result, tool_name
            )
            if not is_valid:
                logger.error(
                    f"Tool '{tool_name}' returned invalid JSON: {validation_msg}"
                )
                return self._format_error_response(
                    f"Invalid JSON response: {validation_msg}",
                    tool_name,
                    "INVALID_JSON",
                )

            # Special handling for load_skill: Intercept output and update session_context
            if tool_name == 'load_skill':
                try:
                    result_data = json.loads(final_result)
                    skill_content = result_data.get("content", "")
                    # Get skill_name from result_data, fallback to kwargs (the original input parameter)
                    skill_name = result_data.get("skill_name") or kwargs.get("skill_name", "unknown")
                    
                    # Update SessionContext: Store skill instruction in system_context as a list
                    # Initialize active_skills list if not exists
                    if 'active_skills' not in session_context.system_context:
                        session_context.system_context['active_skills'] = []
                    
                    active_skills = session_context.system_context['active_skills']
                    
                    # Check if skill already exists, remove old entry
                    active_skills = [s for s in active_skills if s.get('skill_name') != skill_name]
                    
                    # Add new skill to the end (newest)
                    active_skills.append({
                        'skill_name': skill_name,
                        'skill_content': skill_content
                    })
                    
                    # Limit total tokens to 8000, remove oldest if exceeded
                    # But always keep at least one skill, even if it exceeds the limit
                    MAX_SKILL_TOKENS = 8000
                    total_tokens = 0
                    # Use calculate_str_token_length for accurate token calculation
                    for skill in active_skills:
                        skill_content = skill.get('skill_content', '')
                        skill_tokens = MessageManager.calculate_str_token_length(skill_content)
                        total_tokens += skill_tokens
                    
                    # Remove oldest skills if total exceeds limit, but keep at least one
                    while total_tokens > MAX_SKILL_TOKENS and len(active_skills) > 1:
                        removed_skill = active_skills.pop(0)  # Remove oldest (first)
                        removed_content = removed_skill.get('skill_content', '')
                        removed_tokens = MessageManager.calculate_str_token_length(removed_content)
                        total_tokens -= removed_tokens
                        logger.info(f"Removed skill '{removed_skill.get('skill_name')}' due to token limit. Total tokens: {total_tokens}")
                    
                    # Ensure at least one skill remains (even if it exceeds token limit)
                    if len(active_skills) == 0:
                        logger.warning("All skills were removed due to token limit, but at least one skill should remain")
                    
                    session_context.system_context['active_skills'] = active_skills
                    
                    # Also update legacy field for backward compatibility
                    # Concatenate all active skills
                    all_instructions = "\n\n".join([
                        f"=== {s.get('skill_name', 'Unknown')} ===\n{s.get('skill_content', '')}"
                        for s in active_skills
                    ])
                    session_context.system_context['active_skill_instruction'] = all_instructions
                    
                    # Modify the return result to be a simple confirmation
                    skill_list = ", ".join([s.get('skill_name', 'Unknown') for s in active_skills])
                    new_message = f"Skill '{skill_name}' loaded successfully. Current Active skills: {skill_list}. Total skills: {len(active_skills)}. Please follow the instructions in the System Prompt."
                    final_result = json.dumps({"content": new_message}, ensure_ascii=False, indent=2)
                    
                    logger.info(f"Intercepted load_skill output and updated session_context for session {session_id}. Active skills: {skill_list}")
                except Exception as e:
                    logger.error(f"Failed to process load_skill interception: {e}")
                    # If interception fails, we continue with original result but log the error

            return final_result

        except Exception as e:
            execution_time = time.time() - execution_start
            error_detail = _innermost_exception_message(e)
            error_msg = (
                f"Tool '{tool_name}' failed after {execution_time:.2f}s: {error_detail}"
            )
            return self._format_error_response(
                error_msg, tool_name, "EXECUTION_ERROR", error_detail
            )

    async def _execute_mcp_tool(
        self, tool: McpToolSpec, session_id: str, **kwargs
    ) -> str:
        """Execute MCP tool and format result"""
        logger.info(f"Executing MCP tool: {tool.name} on server: {tool.server_name}")
        mcp_proxy = McpProxy()
        try:
            result = await mcp_proxy.run_mcp_tool(tool, session_id, **kwargs)
            logger.info(f"MCP tool {tool.name} execution completed successfully")
            # Process MCP result
            if isinstance(result, dict) and result.get("content"):
                content = result["content"]
                if isinstance(content, list) and len(content) > 0:
                    # Handle list content (e.g., from text/plain results)
                    formatted_content = "\n".join(
                        [item.get("text", str(item)) for item in content]
                    )
                else:
                    formatted_content = content
                return json.dumps(
                    {"content": make_serializable(formatted_content)}, ensure_ascii=False, indent=2
                )
            else:
                return json.dumps(make_serializable(result), ensure_ascii=False, indent=2)

        except Exception as e:
            if isinstance(e, BaseExceptionGroup):
                msg = _innermost_exception_message(e)
                logger.error(f"MCP tool execution failed: {tool.name} - {msg}")
                _raise_innermost_exception(e)
            logger.error(f"MCP tool execution failed: {tool.name} - {str(e)}")
            raise

    async def _execute_standard_tool_async(self, tool: ToolSpec, session_id: str = "", **kwargs) -> str:
        """Execute standard tool and format result (async version)"""
        logger.debug(f"Executing standard tool: {tool.name}")
        execute_start = time.perf_counter()

        try:
            # Inject session_id if the tool function expects it
            import inspect
            func_to_inspect = tool.func
            
            has_session_id_param = False
            
            # For bound methods, check the bound method's signature directly
            # Don't unwrap __wrapped__ because we need to see the actual signature
            # that will be used when calling the method
            try:
                sig = inspect.signature(func_to_inspect)
                has_session_id_param = "session_id" in sig.parameters
                logger.debug(f"[_execute_standard_tool_async] Checking {tool.name} signature: {list(sig.parameters.keys())}, has_session_id: {has_session_id_param}")
            except (ValueError, TypeError) as e:
                logger.debug(f"[_execute_standard_tool_async] Failed to get signature for {tool.name}: {e}")
                pass
            
            # Also check from tool spec parameters (as fallback)
            if not has_session_id_param and hasattr(tool, 'parameters') and tool.parameters:
                has_session_id_param = 'session_id' in tool.parameters
                logger.debug(f"[_execute_standard_tool_async] Checked tool.parameters for {tool.name}: has_session_id={has_session_id_param}")
            
            # Also check from tool spec required params (as fallback)
            if not has_session_id_param and hasattr(tool, 'required') and tool.required:
                has_session_id_param = 'session_id' in tool.required
                logger.debug(f"[_execute_standard_tool_async] Checked tool.required for {tool.name}: has_session_id={has_session_id_param}")
            
            if has_session_id_param:
                kwargs["session_id"] = session_id
                logger.debug(f"[_execute_standard_tool_async] Injected session_id for tool: {tool.name}")

            # Execute the tool function
            if hasattr(tool.func, "__self__"):
                # Bound method
                if asyncio.iscoroutinefunction(tool.func):
                    result = await tool.func(**kwargs)
                else:
                    # 在单独的线程中执行同步方法，避免阻塞事件循环
                    result = await asyncio.to_thread(tool.func, **kwargs)
            else:
                # Unbound method - need to create instance
                tool_class = getattr(tool.func, "__objclass__", None)
                if tool_class:
                    # 检查是否有预先创建的实例
                    if (
                        hasattr(self, "_tool_instances")
                        and tool_class in self._tool_instances
                    ):
                        instance = self._tool_instances[tool_class]
                    else:
                        instance = tool_class()
                    bound_method = tool.func.__get__(instance)
                    if asyncio.iscoroutinefunction(bound_method):
                        result = await bound_method(**kwargs)
                    else:
                        # 在单独的线程中执行同步方法
                        result = await asyncio.to_thread(bound_method, **kwargs)
                else:
                    if asyncio.iscoroutinefunction(tool.func):
                        result = await tool.func(**kwargs)
                    else:
                        # 在单独的线程中执行同步函数
                        result = await asyncio.to_thread(tool.func, **kwargs)

            # Format result - 避免双重JSON序列化
            execute_cost = time.perf_counter() - execute_start
            if execute_cost > 0.2:
                logger.warning(f"Standard tool slow: {tool.name}, cost={execute_cost:.3f}s")
            return json.dumps({"content": make_serializable(result)}, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Standard tool execution failed: {tool.name} - {str(e)}")
            raise

    def _format_error_response(
        self,
        error_msg: str,
        tool_name: str,
        error_type: str,
        exception_detail: Optional[str] = None,
    ) -> str:
        """Format a consistent error response"""
        error_response = {
            "error": True,
            "error_type": error_type,
            "message": error_msg,
            "tool_name": tool_name,
            "timestamp": time.time(),
        }

        if exception_detail:
            error_response["exception_detail"] = exception_detail

        return json.dumps(error_response, ensure_ascii=False, indent=2)

    def _validate_json_response(
        self, response_text: str, tool_name: str
    ) -> tuple[bool, str]:
        """Validate if response is proper JSON and return validation result"""
        if not response_text:
            return False, "Empty response"

        try:
            parsed = json.loads(response_text)

            # Check for common issues
            if isinstance(parsed, str) and len(parsed) > 10000:
                logger.warning(
                    f"Tool '{tool_name}' returned very large response ({len(parsed)} chars)"
                )

            return True, "Valid JSON"

        except json.JSONDecodeError as e:
            error_pos = getattr(e, "pos", "unknown")
            if hasattr(e, "pos") and e.pos < len(response_text):
                start = max(0, e.pos - 50)
                end = min(len(response_text), e.pos + 50)
                context = response_text[start:end]
                logger.error(f"JSON parse error at position {error_pos}: {context}")

            return False, f"JSON decode error at position {error_pos}: {e}"
        except Exception as e:
            logger.error(f"Unexpected JSON validation error for '{tool_name}': {e}")
            return False, f"Validation error: {e}"
