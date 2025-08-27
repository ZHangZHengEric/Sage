from typing import Dict, Any, List, Type, Optional, Union
from .tool_base import ToolBase
from .tool_config import convert_spec_to_openai_format,ToolSpec, McpToolSpec,SseServerParameters,StreamableHttpServerParameters,AgentToolSpec
from sagents.utils.logger import logger
import importlib
import pkgutil
from pathlib import Path
import inspect
import json
import asyncio
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession, Tool
from mcp.types import CallToolResult
import traceback
import time
import os,sys

class ToolManager:
    def __init__(self, is_auto_discover=True):
        """初始化工具管理器"""
        logger.info("Initializing ToolManager")
        
        self.tools: Dict[str, Union[ToolSpec, McpToolSpec, AgentToolSpec]] = {}
        self._tool_instances: Dict[type, ToolBase] = {}  # 缓存工具实例
        
        if is_auto_discover:
            self._auto_discover_tools()
            # self._mcp_setting_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'mcp_servers', 'mcp_setting.json')
            # # 在测试环境中，我们不希望自动发现MCP工具
            # if not os.environ.get('TESTING'):
            #     logger.debug("Not in testing environment, discovering MCP tools")
            #     asyncio.run(self._discover_mcp_tools(mcp_setting_path=self._mcp_setting_path))
            # else:
            #     logger.debug("In testing environment, skipping MCP tool discovery")

    def discover_tools_from_path(self, path: str):
        """Discover and register tools from a custom path
        
        Args:
            path: Path to scan for tools
        """
        return self._auto_discover_tools(path=path)
    async def initialize(self):
        """异步初始化，用于测试环境"""
        logger.info("Asynchronously initializing ToolManager")
        await self._discover_mcp_tools(mcp_setting_path=self._mcp_setting_path)
    

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
        logger.info(f"Registering MCP server: {server_name}")
        if config.get('disabled', False):
            logger.debug(f"Server {server_name} is disabled, skipping")
            return False

        if 'sse_url' in config:
            logger.debug(f"Registering SSE server {server_name} with URL: {config['sse_url']}")
            server_params = SseServerParameters(url=config['sse_url'])
            success = await self._register_mcp_tools_sse(server_name, server_params)
        elif 'url' in config or 'streamable_http_url' in config:
            logger.debug(f"Registering streamable HTTP server {server_name} with URL: {config['url']}")
            server_params = StreamableHttpServerParameters(url=config['url'])
            success = await self._register_mcp_tools_streamable_http(server_name, server_params)
        else:
            logger.debug(f"Registering stdio server {server_name} with command: {config['command']}")
            server_params = StdioServerParameters(
                command=config['command'],
                args=config.get('args', []),
                env=config.get('env', None)
            )
            success = await self._register_mcp_tools_stdio(server_name, server_params)
        logger.info(f"Successfully registered MCP server: {server_name}")
        return success

    def _auto_discover_tools(self, path: str = None):
        """Auto-discover and register all tools in the tools package
        Args:
            path: Optional custom path to scan for tools. If None, uses package directory.
        """
        logger.info("Auto-discovering tools")
        package_path = Path(path) if path else Path(__file__).parent
        sys_package_path = package_path.parent
        # 自动推断完整包名（如 sagents.tool）
        pkg_parts = []
        p = package_path
        while p.name != 'sagents' and p.parent != p:
            pkg_parts.insert(0, p.name)
            p = p.parent
        if p.name == 'sagents':
            pkg_parts.insert(0, 'sagents')
        full_package_name = '.'.join(pkg_parts)
        logger.info(f"Auto-discovery full package name: {full_package_name}")
        logger.info(f"Scanning path: {package_path}")
        # 需要将package_path 加入sys.path
        if str(sys_package_path) not in sys.path:
            sys.path.append(str(sys_package_path))
            logger.info(f"Added path to sys.path: {sys_package_path}")
        for _, module_name, _ in pkgutil.iter_modules([str(package_path)]):
            if module_name == 'tool_base' or module_name.endswith('_base'):
                logger.debug(f"Skipping base module: {module_name}")
                continue
            try:
                logger.info(f"Attempting to import module: {module_name}")
                module = importlib.import_module(f'.{module_name}', full_package_name)
                for _, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, ToolBase):
                        logger.info(f"Found tool class: {obj.__name__}")
                        self.register_tool_class(obj)
            except ImportError as e:
                logger.error(f"Failed to import module {module_name}: {e}")
                logger.error(traceback.format_exc())
                continue
        logger.info(f"Auto-discovery completed with {len(self.tools)} total tools")
        # 将package_path 从sys.path 中移除
        if str(sys_package_path) in sys.path:
            sys.path.remove(str(sys_package_path))
            logger.info(f"Removed package path from sys.path: {sys_package_path}")
    def register_tool_class(self, tool_class: Type[ToolBase]):
        """Register all tools from a ToolBase subclass"""
        logger.info(f"Registering tools from class: {tool_class.__name__}")
        tool_instance = tool_class()
        # 缓存工具实例，以便后续执行时重用
        self._tool_instances[tool_class] = tool_instance
        instance_tools = tool_instance.tools
        
        if not instance_tools:
            logger.warning(f"No tools found in {tool_class.__name__}")
            return False
        
        logger.info(f"\nRegistering tools to manager from {tool_class.__name__}:")
        registered = False
        for tool_name, tool_spec in instance_tools.items():
            # 修正工具规格中的__objclass__
            if hasattr(tool_spec.func, '__objclass__'):
                tool_spec.func.__objclass__ = tool_class
            if self.register_tool(tool_spec):
                registered = True
        logger.info(f"Completed registering tools from {tool_class.__name__}, success: {registered}")
        return registered

    def register_tool(self, tool_spec: Union[ToolSpec, McpToolSpec, AgentToolSpec]):
        """Register a tool specification"""
        logger.debug(f"Registering tool: {tool_spec.name}")
        if tool_spec.name in self.tools:
            logger.warning(f"Tool already registered: {tool_spec.name}")

            return False
        
        self.tools[tool_spec.name] = tool_spec
        logger.info(f"Successfully registered tool: {tool_spec.name}")
        return True

    async def _discover_mcp_tools(self,mcp_setting_path: str = None):
        """Discover and register tools from MCP servers"""
        logger.info(f"Discovering MCP tools from settings file: {mcp_setting_path}")
        if os.path.exists(mcp_setting_path)==False:
            logger.warning(f"MCP setting file not found: {mcp_setting_path}")
            return
        try:
            with open(mcp_setting_path) as f:
                mcp_config = json.load(f)
                logger.debug(f"Loaded MCP config with {len(mcp_config.get('mcpServers', {}))} servers")
                logger.debug(f"mcp_config: {mcp_config}")
            
            for server_name, config in mcp_config.get('mcpServers', {}).items():
                logger.debug(f"Processing MCP server config for {server_name}")
                logger.debug(f"Loading MCP server config for {server_name}: {config}")
                if config.get('disabled', False):
                    logger.debug(f"Skipping disabled MCP server: {server_name}")
                    continue
                
                if 'sse_url' in config:
                    logger.debug(f"Setting up SSE server: {server_name} at URL: {config['sse_url']}")
                    server_params = SseServerParameters(url=config['sse_url'],api_key=config.get('api_key',None))
                    success = await self._register_mcp_tools_sse(server_name, server_params)
                elif 'url' in config or 'streamable_http_url' in config:
                    logger.debug(f"Setting up streamable HTTP server: {server_name} at URL: {config['url']}")
                    server_params = StreamableHttpServerParameters(url=config.get('url',config.get('streamable_http_url')))
                    success = await self._register_mcp_tools_streamable_http(server_name, server_params)
                else:
                    logger.debug(f"Setting up stdio server: {server_name} with command: {config['command']}")
                    server_params = StdioServerParameters(
                        command=config['command'],
                        args=config.get('args', []),
                        env=config.get('env', None)
                    )
                    success = await self._register_mcp_tools_stdio(server_name, server_params)
        except Exception as e:
            logger.error(f"Error loading MCP config: {str(e)}")
            return False
        return success

    async def _register_mcp_tools_stdio(self, server_name: str, server_params: StdioServerParameters):
        """Register tools from stdio MCP server"""
        logger.info(f"Registering tools from stdio MCP server: {server_name}")
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    logger.debug(f"Initializing session for stdio MCP server {server_name}")
                    start_time = time.time()
                    await session.initialize()
                    elapsed = time.time() - start_time
                    logger.debug(f"Initialized session for stdio MCP server {server_name} in {elapsed:.2f} seconds")

                    response = await session.list_tools()
                    tools = response.tools
                    logger.info(f"Received {len(tools)} tools from stdio MCP server {server_name}")
                    for tool in tools:
                        await self._register_mcp_tool(server_name,tool, server_params)
        except Exception as e:
            logger.error(f"Failed to connect to stdio MCP server {server_name}: {str(e)}")
            logger.error(traceback.format_exc())
            return False
        return True
    async def _register_mcp_tools_streamable_http(self, server_name: str, server_params: StreamableHttpServerParameters):
        """Register tools from streamable HTTP MCP server"""
        logger.info(f"Registering tools from streamable HTTP MCP server: {server_name} at {server_params.url}")
        try:
            async with streamablehttp_client(server_params.url) as (read, write,_):
                async with ClientSession(read, write) as session:
                    logger.debug(f"Initializing session for streamable HTTP MCP server {server_name}")
                    start_time = time.time()
                    await session.initialize()
                    elapsed = time.time() - start_time
                    logger.debug(f"Initialized session for streamable HTTP MCP server {server_name} in {elapsed:.2f} seconds")
                    response = await session.list_tools()
                    tools = response.tools
                    logger.info(f"Received {len(tools)} tools from streamable HTTP MCP server {server_name}")
                    for tool in tools:
                        await self._register_mcp_tool(server_name, tool, server_params)
                    return True
        except Exception as e:
            logger.error(f"Failed to connect to streamable HTTP MCP server {server_name}: {str(e)}")
            return False

    async def _register_mcp_tools_sse(self, server_name: str, server_params: SseServerParameters):
        """Register tools from SSE MCP server"""
        logger.info(f"Registering tools from SSE MCP server: {server_name} at {server_params.url}")

        try:
            headers= None
            if server_params.api_key:
                headers = {
                    "Authorization": f"Bearer {server_params.api_key}",
                    "Content-Type": "application/json"
                }
            logger.info(f'SSE MCP server header {headers}')
            async with sse_client(server_params.url,headers=headers) as (read, write):
                async with ClientSession(read, write) as session:
                    logger.debug(f"Initializing session for SSE MCP server {server_name}")

                    start_time = time.time()
                    await session.initialize()
                    elapsed = time.time() - start_time
                    logger.debug(f"Session initialized in {elapsed:.2f} seconds")

                    response = await session.list_tools()
                    tools = response.tools
                    logger.info(f"Received {len(tools)} tools from SSE MCP server {server_name}")
                    for tool in tools:
                        await self._register_mcp_tool(server_name, tool, server_params)
                    return True
        except Exception as e:
            logger.error(f"Failed to connect to SSE MCP server {server_name}: {str(e)}")
            return False
        
    async def _register_mcp_tool(self, server_name: str, tool_info:Union[Tool, dict], 
                               server_params: Union[StdioServerParameters, SseServerParameters]):
        
        if isinstance(tool_info, Tool):
            tool_info = tool_info.model_dump()
        if not isinstance(tool_info, dict):
            logger.warning(f"Invalid tool info type: {type(tool_info)}")
        logger.debug(f"Registering MCP tool: {tool_info['name']} from server: {server_name}")
        """Register a tool from MCP server"""
        if 'input_schema' in tool_info:
            input_schema = tool_info.get('input_schema', {})
        else:
            input_schema = tool_info.get('inputSchema', {})
        tool_spec = McpToolSpec(
            name=tool_info['name'],
            description=tool_info.get('description', ''),
            func=None,
            parameters=input_schema.get('properties', {}),
            required=input_schema.get('required', []),
            server_name=server_name,
            server_params=server_params
        )
        registered = self.register_tool(tool_spec)
        logger.debug(f"MCP tool {tool_info['name']} registration result: {registered}")
    
    def register_tools_from_directory(self, dir_path: str):
        """Register all tools from a directory containing tool modules"""
        logger.info(f"Registering tools from directory: {dir_path}")
        dir_path = Path(dir_path)
        if not dir_path.is_dir():
            logger.warning(f"Directory not found: {dir_path}")
            return False
            
        logger.info(f"\nScanning directory for tools: {dir_path}")
        tool_count = 0
            
        for py_file in dir_path.glob('*.py'):
            if py_file.stem == '__init__' or py_file.stem.endswith('_base'):
                logger.debug(f"Skipping file: {py_file.name}")
                continue
                
            module_name = py_file.stem
            logger.debug(f"Found tool module: {module_name}")
            
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, ToolBase) and obj is not ToolBase:
                        logger.debug(f"Registering tool class: {name}")

                        if self.register_tool_class(obj):
                            tool_count = len(self.tools)
            except Exception as e:
                logger.error(f"Error loading tool from {py_file}: {str(e)}")

                continue
                
        logger.info(f"Successfully registered {tool_count} tools from directory")

        return tool_count > 0

    def get_tool(self, name: str) -> Optional[Union[ToolSpec, McpToolSpec]]:
        """Get a tool by name"""
        logger.debug(f"Getting tool by name: {name}")
        return self.tools.get(name)

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available tools with metadata"""
        logger.debug(f"Listing all {len(self.tools)} tools with metadata")
        return [{
            'name': tool.name,
            'description': tool.description,
            'parameters': tool.parameters,
            'required': tool.required
        } for tool in self.tools.values()]

    def list_tools_simplified(self) -> List[Dict[str, Any]]:
        """List all available tools with simplified metadata"""
        logger.debug(f"Listing all {len(self.tools)} tools with simplified metadata")
        return [{
            'name': tool.name,
            'description': tool.description
        } for tool in self.tools.values()]
    
    def list_all_tools_name(self) -> List[str]:
        """List all available tools with name"""
        logger.debug(f"Listing all {len(self.tools)} tools with name")
        return [tool.name for tool in self.tools.values()]

    def list_tools_with_type(self) -> List[Dict[str, Any]]:
        """List all available tools with type and source information"""
        logger.debug(f"Listing all {len(self.tools)} tools with type information")
        tools_with_type = []
        
        for tool in self.tools.values():
            # 根据工具类型判断
            if isinstance(tool, McpToolSpec):
                tool_type = "mcp"
                source = f"MCP Server: {tool.server_name}"
            elif isinstance(tool, AgentToolSpec):
                tool_type = "agent"
                source = "专业智能体"
            elif isinstance(tool, ToolSpec):
                tool_type = "basic"
                # 根据工具名称推断来源
                source = "基础工具"
            else:
                tool_type = "unknown"
                source = "未知来源"
            
            tools_with_type.append({
                'name': tool.name,
                'description': tool.description,
                'parameters': getattr(tool, 'parameters', {}),
                'type': tool_type,
                'source': source
            })
        
        return tools_with_type

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Get tool specifications in OpenAI-compatible format"""
        logger.debug(f"Getting OpenAI tool specifications for {len(self.tools)} tools")
        return [convert_spec_to_openai_format(tool) for tool in self.tools.values()]

    def run_tool(self, tool_name: str, messages: list, session_id: str, **kwargs) -> Any:
        """Execute a tool by name with provided arguments"""
        execution_start = time.time()
        logger.info(f"Executing tool: {tool_name} (session: {session_id})")
        logger.info(f"Tool arguments: {kwargs}")
        # Remove duplicate session_id from kwargs if present
        session_id = kwargs.pop('session_id', session_id)
        
        # Step 1: Tool Lookup
        tool = self.get_tool(tool_name)
        if not tool:
            error_msg = f"Tool '{tool_name}' not found. Available: {list(self.tools.keys())}"
            logger.error(error_msg)

            return self._format_error_response(error_msg, tool_name, "TOOL_NOT_FOUND")
        
        logger.debug(f"Found tool: {tool_name} (type: {type(tool).__name__})")
        
        # Step 2: Execute based on tool type (self-call prevention handled at agent level)
        
        try:
            # Step 3: Execute tool
            if isinstance(tool, McpToolSpec):
                from concurrent.futures import ThreadPoolExecutor
                
                def run_async_task():
                    return asyncio.run(self._execute_mcp_tool(tool, session_id, **kwargs))
                
                with ThreadPoolExecutor(max_workers=1) as executor:
                    try:
                        future = executor.submit(run_async_task)
                        final_result = future.result(timeout=300)
                    except TimeoutError:
                        logger.error(f"MCP tool {tool.name} execution timed out")
                        raise RuntimeError(f"MCP tool {tool.name} execution timed out after 300 seconds")
                    except Exception as e:
                        logger.error(f"MCP tool {tool.name} execution failed: {str(e)}")
                        raise
            elif isinstance(tool, ToolSpec):
                final_result = self._execute_standard_tool(tool, **kwargs)
            elif isinstance(tool, AgentToolSpec):
                # For AgentToolSpec, return a generator for streaming
                return self._execute_agent_tool_streaming(tool, messages, session_id)
            else:
                error_msg = f"Unknown tool type: {type(tool).__name__}"
                logger.error(error_msg)
                return self._format_error_response(error_msg, tool_name, "UNKNOWN_TOOL_TYPE")
            
            # Step 4: Validate Result (for non-streaming tools)
            execution_time = time.time() - execution_start
            logger.info(f"Tool '{tool_name}' completed successfully in {execution_time:.2f}s")
            
            # Validate JSON format
            is_valid, validation_msg = self._validate_json_response(final_result, tool_name)
            if not is_valid:
                logger.error(f"Tool '{tool_name}' returned invalid JSON: {validation_msg}")
                return self._format_error_response(f"Invalid JSON response: {validation_msg}", 
                                                 tool_name, "INVALID_JSON")
            
            return final_result
            
        except Exception as e:
            execution_time = time.time() - execution_start
            error_msg = f"Tool '{tool_name}' failed after {execution_time:.2f}s: {str(e)}"
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return self._format_error_response(error_msg, tool_name, "EXECUTION_ERROR", str(e))


    def _execute_agent_tool_streaming(self, tool: AgentToolSpec, messages: list, session_id: str):
        """
        执行AgentToolSpec并返回流式结果
        
        Args:
            tool: AgentToolSpec实例
            messages: 消息列表
            session_id: 会话ID
            
        Yields:
            流式返回的结果
        """
        logger.info(f"Executing agent tool with streaming: {tool.name}")
        execution_start = time.time()
        
        try:
            # 检查agent是否有run_stream方法
            agent_instance = tool.func.__self__ if hasattr(tool.func, '__self__') else None
            
            if agent_instance and hasattr(agent_instance, 'run_stream'):
                logger.debug(f"Using run_stream method for agent: {tool.name}")
                # 使用流式方法
                stream_generator = agent_instance.run_stream(
                    messages=messages, 
                    tool_manager=self,
                    session_id=session_id
                )
                
                # 流式返回结果
                for chunk in stream_generator:
                    yield chunk
                    
            else:
                logger.debug(f"Using non-streaming method for agent: {tool.name}")
                # 回退到非流式方法
                result = tool.func(messages=messages, session_id=session_id)
                
                # 将结果包装为流式格式
                if isinstance(result, list):
                    for message in result:
                        yield [message]
                else:
                    yield [{"role": "assistant", "content": str(result)}]
            
            # 记录执行统计
            execution_time = time.time() - execution_start
            logger.info(f"Agent tool '{tool.name}' completed streaming in {execution_time:.2f}s")
            
        except Exception as e:
            execution_time = time.time() - execution_start
            error_msg = f"Agent tool '{tool.name}' failed after {execution_time:.2f}s: {str(e)}"
            logger.error(error_msg)
            logger.error(f"Exception details: {type(e).__name__}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            
            
            # 返回错误消息作为流
            error_response = {
                "role": "assistant",
                "content": f"工具执行失败: {error_msg}",
                "error": True,
                "error_type": "EXECUTION_ERROR"
            }
            yield [error_response]

    async def _execute_mcp_tool(self, tool: McpToolSpec, session_id: str, **kwargs) -> str:
        """Execute MCP tool and format result"""
        logger.info(f"Executing MCP tool: {tool.name} on server: {tool.server_name}")
        
        try:
            result = await self._run_mcp_tool_async(tool, session_id, **kwargs)
            logger.info(f"MCP tool {tool.name} execution completed successfully")
            # Process MCP result
            if isinstance(result, dict) and result.get('content'):
                content = result['content']
                if isinstance(content, list) and len(content) > 0:
                    # Handle list content (e.g., from text/plain results)
                    formatted_content = '\n'.join([item.get('text', str(item)) for item in content])
                else:
                    formatted_content = content
                return json.dumps({"content": formatted_content}, ensure_ascii=False, indent=2)
            else:
                return json.dumps(result, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"MCP tool execution failed: {tool.name} - {str(e)}")
            raise

    def _execute_standard_tool(self, tool: ToolSpec, **kwargs) -> str:
        """Execute standard tool and format result"""
        logger.debug(f"Executing standard tool: {tool.name}")
        
        try:
            # Execute the tool function
            if hasattr(tool.func, '__self__'):
                # Bound method
                result = tool.func(**kwargs)
            else:
                # Unbound method - need to create instance
                tool_class = getattr(tool.func, '__objclass__', None)
                if tool_class:
                    # 检查是否有预先创建的实例
                    if hasattr(self, '_tool_instances') and tool_class in self._tool_instances:
                        instance = self._tool_instances[tool_class]
                    else:
                        instance = tool_class()
                    result = tool.func.__get__(instance)(**kwargs)
                else:
                    result = tool.func(**kwargs)
            
            # Format result - 避免双重JSON序列化
            # if isinstance(result, (dict, list)):
            #     # 直接返回dict/list结果，不进行JSON字符串化
            #     return json.dumps(result, ensure_ascii=False, indent=2)
            # else:
            return json.dumps({"content": result}, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"Standard tool execution failed: {tool.name} - {str(e)}")
            raise

    def _format_error_response(self, error_msg: str, tool_name: str, error_type: str, 
                              exception_detail: str = None) -> str:
        """Format a consistent error response"""
        error_response = {
            "error": True,
            "error_type": error_type,
            "message": error_msg,
            "tool_name": tool_name,
            "timestamp": time.time()
        }
        
        if exception_detail:
            error_response["exception_detail"] = exception_detail
            
        return json.dumps(error_response, ensure_ascii=False, indent=2)

    async def _run_mcp_tool_async(self, tool: McpToolSpec, session_id: str = None, **kwargs) -> Any:
        """Run an MCP tool asynchronously"""
        if not session_id:
            session_id = "default"
        
        server_name = tool.server_name
        logger.debug(f"MCP tool execution: {tool.name} on {server_name}")
        
        try:
            if isinstance(tool.server_params, SseServerParameters):
                return await self._execute_sse_mcp_tool(tool, **kwargs)
            elif isinstance(tool.server_params, StreamableHttpServerParameters):
                return await self._execute_streamable_http_mcp_tool(tool, **kwargs)
            else:
                return await self._execute_stdio_mcp_tool(tool, **kwargs)
        except Exception as e:
            logger.error(f"MCP tool '{tool.name}' failed on server '{server_name}': {str(e)}")
            logger.debug(f"MCP error details - Tool: {tool.name}, Server: {server_name}, Args: {kwargs}")
            raise

    async def _execute_streamable_http_mcp_tool(self, tool: McpToolSpec, **kwargs) -> Any:
        """Execute streamable HTTP MCP tool"""
        headers = None
        if tool.server_params.api_key:
            headers = {
                "Authorization": f"Bearer {tool.server_params.api_key}",
                "Content-Type": "application/json"
            }
        async with streamablehttp_client(tool.server_params.url, headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool.name, kwargs)
                return result.model_dump()

    
    async def _execute_sse_mcp_tool(self, tool: McpToolSpec, **kwargs) -> Any:
        """Execute SSE MCP tool"""
        headers= None
        if tool.server_params.api_key:
            headers = {
                "Authorization": f"Bearer {tool.server_params.api_key}",
                "Content-Type": "application/json"
            }
        async with sse_client(tool.server_params.url,headers=headers) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool.name, kwargs)
                return result.model_dump()

    async def _execute_stdio_mcp_tool(self, tool: McpToolSpec, **kwargs) -> Any:
        """Execute stdio MCP tool"""
        async with stdio_client(tool.server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool.name, kwargs)
                return result.model_dump()

    def _validate_json_response(self, response_text: str, tool_name: str) -> tuple[bool, str]:
        """Validate if response is proper JSON and return validation result"""
        if not response_text:
            return False, "Empty response"
        
        try:
            parsed = json.loads(response_text)
            
            # Check for common issues
            if isinstance(parsed, str) and len(parsed) > 10000:
                logger.warning(f"Tool '{tool_name}' returned very large response ({len(parsed)} chars)")
                
            return True, "Valid JSON"
            
        except json.JSONDecodeError as e:
            error_pos = getattr(e, 'pos', 'unknown')
            if hasattr(e, 'pos') and e.pos < len(response_text):
                start = max(0, e.pos - 50)
                end = min(len(response_text), e.pos + 50)
                context = response_text[start:end]
                logger.error(f"JSON parse error at position {error_pos}: {context}")
            
            return False, f"JSON decode error at position {error_pos}: {e}"
        except Exception as e:
            logger.error(f"Unexpected JSON validation error for '{tool_name}': {e}")
            return False, f"Validation error: {e}"

