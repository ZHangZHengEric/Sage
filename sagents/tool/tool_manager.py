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
    AgentToolSpec,
)
from sagents.utils.logger import logger
from sagents.context.session_context import SessionContext
from pathlib import Path
import json
import asyncio
from mcp import StdioServerParameters
from mcp import Tool
import traceback
import time
import os
import sys
from .mcp_proxy import McpProxy

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
    def __init__(self, is_auto_discover=True):
        """初始化工具管理器"""
        logger.info("Initializing ToolManager")

        self.tools: Dict[str, Union[ToolSpec, McpToolSpec, AgentToolSpec, SageMcpToolSpec]] = {}
        self._tool_instances: Dict[type, Any] = {}  # 缓存工具实例
        self._mcp_setting_path = None

        if is_auto_discover:
            self.discover_tools_from_path()
            self.discover_builtin_mcp_tools_from_path()
            # self._mcp_setting_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'mcp_servers', 'mcp_setting.json')
            # # 在测试环境中，我们不希望自动发现MCP工具
            # if not os.environ.get('TESTING'):
            #     logger.debug("Not in testing environment, discovering MCP tools")
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
            # 默认情况：导入 sagents.tool.impl 包
            # 依赖 impl/__init__.py 自动导入所有子模块
            try:
                from . import impl
            except ImportError as e:
                logger.warning(f"Failed to import impl package: {e}")

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
        logger.info(f"Registered {count} tools from package_path")

    def register_tool(self, tool_spec: Union[ToolSpec, McpToolSpec, AgentToolSpec, SageMcpToolSpec]):
        """Register a tool specification with priority-based replacement

        Priority order (high to low):
        1. McpToolSpec (MCP tools)
        2. AgentToolSpec (Agent tools)
        3. SageMcpToolSpec (Built-in MCP tools)
        4. ToolSpec (Local tools)
        """

        if tool_spec.name in self.tools:
            existing_tool = self.tools[tool_spec.name]

            # 定义优先级：MCP > Agent > SageMcp > Local
            priority_order = {McpToolSpec: 3, AgentToolSpec: 2, SageMcpToolSpec: 1.5, ToolSpec: 1}

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
                logger.warning(
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
        logger.info(f"Successfully registered new tool: {tool_spec.name} ({tool_type})")
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
                logger.info(
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
        logger.info(f"Registering MCP server: {server_name}")
        if config.get("disabled", True):
            logger.debug(f"Server {server_name} is disabled, skipping")
            return bool_registered
        server_name = server_name.strip()
        server_params: Optional[Union[StdioServerParameters, SseServerParameters, StreamableHttpServerParameters]] = None
        try:
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
                server_params = StdioServerParameters(
                    command=config["command"],
                    args=config.get("args", []),
                    env=config.get("env", None),
                )
            mcp_proxy = McpProxy()
            mcp_tools = await mcp_proxy.get_mcp_tools(server_name, server_params)
            for mcp_tool in mcp_tools:
                await self._register_mcp_tool(server_name, mcp_tool, server_params)
        except Exception as e:
            error_detail = _innermost_exception_message(e)
            logger.warning(f"Error registering MCP server {server_name}: {error_detail}")
            return bool_registered
        bool_registered = True
        logger.info(f"Successfully registered MCP server: {server_name}")
        return bool_registered

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

    def get_tool(self, name: str) -> Optional[Union[ToolSpec, McpToolSpec, AgentToolSpec]]:
        """Get a tool by name"""
        logger.debug(f"Getting tool by name: {name}")
        return self.tools.get(name)

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
            elif isinstance(tool, AgentToolSpec):
                tool_type = "agent"
                source = "专业智能体"
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
        # Remove duplicate session_id from kwargs if present
        session_id = kwargs.pop("session_id", session_id)

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
                final_result = await self._execute_mcp_tool(tool, session_id, **kwargs)
            elif isinstance(tool, SageMcpToolSpec):
                final_result = await self._execute_standard_tool_async(tool, **kwargs)
            elif isinstance(tool, ToolSpec):
                # Check for sandbox execution
                # Define sandbox tools (can be moved to config later)
                SANDBOX_TOOLS = [
                    "execute_shell_command", 
                    "execute_python_code", 
                    "file_read", 
                    "file_write", 
                    "search_content_in_file", 
                    "download_file_from_url", 
                    "update_file",
                    "extract_text_from_non_text_file"
                ]
                
                if tool.name in SANDBOX_TOOLS:
                    try:
                        # Use sandbox if available
                        if hasattr(session_context, 'sandbox') and session_context.sandbox:
                            # Check if pip is needed
                            needs_pip = False
                            if tool.name == "execute_python_code" and kwargs.get("requirement_list"):
                                needs_pip = True
                            elif tool.name == "execute_shell_command":
                                cmd = kwargs.get("command", "")
                                if "pip " in cmd or "pip3 " in cmd:
                                    needs_pip = True
                            
                            if needs_pip:
                                session_context.sandbox.ensure_pip()

                            # Use run_tool which handles path mapping and execution
                            # We pass the function object from the tool spec
                            # And try to pass the tool instance if available (though ToolSpec might not store it directly, 
                            # usually it's bound method if created from class)
                            result = session_context.sandbox.run_tool(tool.func, kwargs)
                            final_result = json.dumps({"content": result}, ensure_ascii=False, indent=2)
                        else:
                             # Fallback to standard execution if no sandbox found (should not happen in new setup)
                            logger.warning(f"No sandbox found in session_context for {tool.name}, executing directly.")
                            final_result = await self._execute_standard_tool_async(tool, **kwargs)

                    except Exception as e:
                        logger.error(f"Sandbox execution failed for {tool.name}, aborting.")
                        raise e
                else:
                    final_result = await self._execute_standard_tool_async(tool, **kwargs)
            elif isinstance(tool, AgentToolSpec):
                # For AgentToolSpec, return a generator for streaming
                return self._execute_agent_tool_streaming_async(
                    tool, session_context, session_id
                )
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
                    {"content": formatted_content}, ensure_ascii=False, indent=2
                )
            else:
                return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            if isinstance(e, BaseExceptionGroup):
                msg = _innermost_exception_message(e)
                logger.error(f"MCP tool execution failed: {tool.name} - {msg}")
                _raise_innermost_exception(e)
            logger.error(f"MCP tool execution failed: {tool.name} - {str(e)}")
            raise

    async def _execute_standard_tool_async(self, tool: ToolSpec, **kwargs) -> str:
        """Execute standard tool and format result (async version)"""
        logger.debug(f"Executing standard tool: {tool.name}")

        try:
            # Execute the tool function
            if hasattr(tool.func, "__self__"):
                # Bound method
                if asyncio.iscoroutinefunction(tool.func):
                    result = await tool.func(**kwargs)
                else:
                    result = tool.func(**kwargs)
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
                        result = bound_method(**kwargs)
                else:
                    if asyncio.iscoroutinefunction(tool.func):
                        result = await tool.func(**kwargs)
                    else:
                        result = tool.func(**kwargs)

            # Format result - 避免双重JSON序列化
            return json.dumps({"content": result}, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"Standard tool execution failed: {tool.name} - {str(e)}")
            raise

    async def _execute_agent_tool_streaming_async(
        self, tool: AgentToolSpec, session_context: SessionContext, session_id: str
    ):
        """
        执行AgentToolSpec并返回流式结果 (async version)

        Args:
            tool: AgentToolSpec实例
            session_context: 会话上下文
            session_id: 会话ID

        Yields:
            流式返回的结果
        """
        logger.info(f"Executing agent tool with streaming: {tool.name}")
        execution_start = time.time()

        try:
            # 检查agent是否有run_stream方法
            agent_instance = (
                tool.func.__self__ if hasattr(tool.func, "__self__") else None
            )

            if agent_instance and hasattr(agent_instance, "run_stream"):
                logger.debug(f"Using run_stream method for agent: {tool.name}")
                # 使用流式方法
                stream_generator = agent_instance.run_stream(
                    session_context=session_context,
                    tool_manager=self,
                    session_id=session_id,
                )

                # 流式返回结果
                async for chunk in stream_generator:
                    yield chunk

            else:
                logger.debug(f"Using non-streaming method for agent: {tool.name}")
                # 回退到非流式方法
                result = await tool.func(
                    session_context=session_context, session_id=session_id
                )

                # 将结果包装为流式格式
                if isinstance(result, list):
                    for message in result:
                        yield [message]
                else:
                    yield [{"role": "assistant", "content": str(result)}]

            # 记录执行统计
            execution_time = time.time() - execution_start
            logger.info(
                f"Agent tool '{tool.name}' completed streaming in {execution_time:.2f}s"
            )

        except Exception as e:
            execution_time = time.time() - execution_start
            error_msg = (
                f"Agent tool '{tool.name}' failed after {execution_time:.2f}s: {str(e)}"
            )
            logger.error(error_msg)
            logger.error(f"Exception details: {type(e).__name__}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")

            # 返回错误消息作为流
            error_response = {
                "role": "assistant",
                "content": f"工具执行失败: {error_msg}",
                "error": True,
                "error_type": "EXECUTION_ERROR",
            }
            yield [error_response]

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
