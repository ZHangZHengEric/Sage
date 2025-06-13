from typing import Dict, Any, List, Type, Optional, Union
from agents.tool.tool_base import ToolBase, ToolSpec, McpToolSpec,SseServerParameters,AgentToolSpec
from agents.utils.logger import logger
import importlib
import pkgutil
from pathlib import Path
import inspect
import json
import asyncio
from mcp import StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp import ClientSession, Tool
from mcp.types import CallToolResult
import traceback
import time
import os,sys

class ToolManager:
    def __init__(self, is_auto_discover=True):
        """初始化工具管理器"""
        logger.info("Initializing ToolManager")
        
        # 工具执行统计
        self.execution_stats = {
            'total_executions': 0,
            'successful_executions': 0,
            'failed_executions': 0,
            'tools_called': {},
            'error_types': {}
        }
        
        self.tools: Dict[str, Union[ToolSpec, McpToolSpec, AgentToolSpec]] = {}
        self._mcp_sessions: Dict[str, Dict[str, Union[ClientSession]]] = {}  # {session_id: {server_name: session}}
        
        if is_auto_discover:
            self._auto_discover_tools()
            self._mcp_setting_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'mcp_servers', 'mcp_setting.json')
            # 在测试环境中，我们不希望自动发现MCP工具
            if not os.environ.get('TESTING'):
                logger.debug("Not in testing environment, discovering MCP tools")
                asyncio.run(self._discover_mcp_tools(mcp_setting_path=self._mcp_setting_path))
            else:
                logger.debug("In testing environment, skipping MCP tool discovery")

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
    async def cleanup_session(self, session_id: str):
        """Clean up all sessions for a given session_id"""
        logger.info(f"Cleaning up sessions for session_id: {session_id}")
        if session_id in self._mcp_sessions:
            for server_name, session in self._mcp_sessions[session_id].items():
                try:
                    logger.debug(f"Closing session for server: {server_name}")
                    await session.close()
                except Exception as e:
                    logger.error(f"Error closing session for server {server_name}: {e}")
                    print(f"Error closing session: {e}")
            del self._mcp_sessions[session_id]
            logger.info(f"Successfully cleaned up sessions for session_id: {session_id}")
        else:
            logger.debug(f"No sessions found for session_id: {session_id}")

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
            await self._register_mcp_tools_sse(server_name, server_params)
        else:
            logger.debug(f"Registering stdio server {server_name} with command: {config['command']}")
            server_params = StdioServerParameters(
                command=config['command'],
                args=config.get('args', []),
                env=config.get('env', None)
            )
            await self._register_mcp_tools_stdio(server_name, server_params)
        logger.info(f"Successfully registered MCP server: {server_name}")
        return True

    def _auto_discover_tools(self, path: str = None):
        """Auto-discover and register all tools in the tools package
        
        Args:
            path: Optional custom path to scan for tools. If None, uses package directory.
        """
        logger.info("Auto-discovering tools")
        package_path = Path(path) if path else Path(__file__).parent
        sys_package_path = package_path.parent
        package_name = package_path.name
        logger.info(f"Auto-discovery package name: {package_name}")
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
                module = importlib.import_module(f'.{module_name}',package_name)
                for _, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, ToolBase):
                        logger.info(f"Found tool class: {obj.__name__}")
                        self.register_tool_class(obj)
            except ImportError as e:
                traceback.print_exc()
                logger.error(f"Error importing module {module_name}: {e}")
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
        instance_tools = tool_instance.tools
        
        if not instance_tools:
            logger.warning(f"No tools found in {tool_class.__name__}")
            print(f"No tools found in {tool_class.__name__}")
            return False
        
        print(f"\nRegistering tools to manager from {tool_class.__name__}:")
        registered = False
        for tool_name, tool_spec in instance_tools.items():
            if self.register_tool(tool_spec):
                registered = True
        logger.info(f"Completed registering tools from {tool_class.__name__}, success: {registered}")
        return registered

    def register_tool(self, tool_spec: Union[ToolSpec, McpToolSpec, AgentToolSpec]):
        """Register a tool specification"""
        logger.debug(f"Registering tool: {tool_spec.name}")
        if tool_spec.name in self.tools:
            logger.warning(f"Tool already registered: {tool_spec.name}")
            print(f"Tool already registered: {tool_spec.name}")
            return False
        
        self.tools[tool_spec.name] = tool_spec
        logger.info(f"Successfully registered tool: {tool_spec.name}")
        print(f"Registered tool to manager: {tool_spec.name}")
        return True

    async def _discover_mcp_tools(self,mcp_setting_path: str = None):
        """Discover and register tools from MCP servers"""
        logger.info(f"Discovering MCP tools from settings file: {mcp_setting_path}")
        if os.path.exists(mcp_setting_path)==False:
            logger.warning(f"MCP setting file not found: {mcp_setting_path}")
            print(f"MCP setting file not found: {mcp_setting_path}")
            return
        try:
            with open(mcp_setting_path) as f:
                mcp_config = json.load(f)
                logger.debug(f"Loaded MCP config with {len(mcp_config.get('mcpServers', {}))} servers")
                print('mcp_config',mcp_config)
            
            for server_name, config in mcp_config.get('mcpServers', {}).items():
                logger.debug(f"Processing MCP server config for {server_name}")
                print(f"Loading MCP server config for {server_name}: {config}")
                if config.get('disabled', False):
                    logger.debug(f"Skipping disabled MCP server: {server_name}")
                    print(f"Skipping disabled MCP server: {server_name}")
                    continue
                
                if 'sse_url' in config:
                    logger.debug(f"Setting up SSE server: {server_name} at URL: {config['sse_url']}")
                    server_params = SseServerParameters(url=config['sse_url'],api_key=config.get('api_key',None))
                    await self._register_mcp_tools_sse(server_name, server_params)
                else:
                    logger.debug(f"Setting up stdio server: {server_name} with command: {config['command']}")
                    server_params = StdioServerParameters(
                        command=config['command'],
                        args=config.get('args', []),
                        env=config.get('env', None)
                    )
                    await self._register_mcp_tools_stdio(server_name, server_params)
        except Exception as e:
            logger.error(f"Error loading MCP config: {str(e)}")
            print(f"Error loading MCP config: {e}")

    async def _register_mcp_tools_stdio(self, server_name: str, server_params: StdioServerParameters):
        """Register tools from stdio MCP server"""
        logger.info(f"Registering tools from stdio MCP server: {server_name}")
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    logger.debug(f"Initializing session for stdio MCP server {server_name}")
                    print(f"Initializing session for stdio MCP server {server_name}")
                    start_time = time.time()
                    await session.initialize()
                    elapsed = time.time() - start_time
                    logger.debug(f"Initialized session for stdio MCP server {server_name} in {elapsed:.2f} seconds")
                    print(f"Initialized session for stdio MCP server {server_name} in {elapsed} seconds")
                    response = await session.list_tools()
                    tools = response.tools
                    logger.info(f"Received {len(tools)} tools from stdio MCP server {server_name}")
                    for tool in tools:
                        await self._register_mcp_tool(server_name,tool, server_params)
        except Exception as e:
            logger.error(f"Failed to connect to stdio MCP server {server_name}: {str(e)}")
            logger.error(traceback.format_exc())
            print(traceback.format_exc())
            print(f"Failed to connect to stdio MCP server {server_name}: {e}")

    async def _register_mcp_tools_sse(self, server_name: str, server_params: SseServerParameters):
        """Register tools from SSE MCP server"""
        logger.info(f"Registering tools from SSE MCP server: {server_name} at {server_params.url}")
        print(f"Connecting to SSE MCP server {server_name} at {server_params.url}")
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
                    print(f"Initializing session for SSE MCP server {server_name}")
                    start_time = time.time()
                    await session.initialize()
                    elapsed = time.time() - start_time
                    logger.debug(f"Session initialized in {elapsed:.2f} seconds")
                    print(f"Session initialized in {elapsed:.2f} seconds")
                    response = await session.list_tools()
                    tools = response.tools
                    logger.info(f"Received {len(tools)} tools from SSE MCP server {server_name}")
                    for tool in tools:
                        await self._register_mcp_tool(server_name, tool, server_params)
        except Exception as e:
            logger.error(f"Failed to connect to SSE MCP server {server_name}: {str(e)}")
            print(f"Failed to connect to SSE MCP server {server_name}: {e}")

    async def _register_mcp_tool(self, server_name: str, tool_info:Union[Tool, dict], 
                               server_params: Union[StdioServerParameters, SseServerParameters]):
        
        if isinstance(tool_info, Tool):
            tool_info = tool_info.model_dump()
        if not isinstance(tool_info, dict):
            logger.warning(f"Invalid tool info type: {type(tool_info)}")
            print(f"Invalid tool info type: {type(tool_info)}")        
        logger.debug(f"Registering MCP tool: {tool_info['name']} from server: {server_name}")
        print(f"Tool info: {tool_info}")
        print(f"Registering tool from MCP server: {tool_info['name']}")
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
            print(f"Directory not found: {dir_path}")
            return False
            
        print(f"\nScanning directory for tools: {dir_path}")
        tool_count = 0
            
        for py_file in dir_path.glob('*.py'):
            if py_file.stem == '__init__' or py_file.stem.endswith('_base'):
                logger.debug(f"Skipping file: {py_file.name}")
                continue
                
            module_name = py_file.stem
            logger.debug(f"Found tool module: {module_name}")
            print(f"\nFound tool module: {module_name}")
            
            try:
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                for name, obj in inspect.getmembers(module):
                    if inspect.isclass(obj) and issubclass(obj, ToolBase) and obj is not ToolBase:
                        logger.debug(f"Registering tool class: {name}")
                        print(f"  Registering tool class: {name}")
                        if self.register_tool_class(obj):
                            tool_count = len(self.tools)
            except Exception as e:
                logger.error(f"Error loading tool from {py_file}: {str(e)}")
                print(f"Error loading tool from {py_file}: {e}")
                continue
                
        logger.info(f"Successfully registered {tool_count} tools from directory")
        print(f"\nSuccessfully registered {tool_count} tools from directory")
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

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Get tool specifications in OpenAI-compatible format"""
        logger.debug(f"Getting OpenAI tool specifications for {len(self.tools)} tools")
        return [{
            'type': 'function',
            'function': {
                'name': tool.name,
                'description': tool.description,
                'parameters': {
                    'type': 'object',
                    'properties': tool.parameters,
                    'required': tool.required
                }
            }
        } for tool in self.tools.values()]

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
            self._log_execution(tool_name, False, "TOOL_NOT_FOUND")
            return self._format_error_response(error_msg, tool_name, "TOOL_NOT_FOUND")
        
        logger.debug(f"Found tool: {tool_name} (type: {type(tool).__name__})")
        
        try:
            # Step 2: Execute based on tool type
            if isinstance(tool, McpToolSpec):
                from concurrent.futures import ThreadPoolExecutor
                
                def run_async_task():
                    return asyncio.run(self._execute_mcp_tool(tool, session_id, **kwargs))
                
                with ThreadPoolExecutor(max_workers=1) as executor:
                    try:
                        future = executor.submit(run_async_task)
                        final_result = future.result(timeout=10)
                    except TimeoutError:
                        logger.error(f"MCP tool {tool.name} execution timed out")
                        raise RuntimeError(f"MCP tool {tool.name} execution timed out after 10 seconds")
                    except Exception as e:
                        logger.error(f"MCP tool {tool.name} execution failed: {str(e)}")
                        raise
            elif isinstance(tool, ToolSpec):
                final_result = self._execute_standard_tool(tool, **kwargs)
            elif isinstance(tool, AgentToolSpec):
                final_result = self._execute_agent_tool(tool, messages, session_id)
            else:
                error_msg = f"Unknown tool type: {type(tool).__name__}"
                logger.error(error_msg)
                self._log_execution(tool_name, False, "UNKNOWN_TOOL_TYPE")
                return self._format_error_response(error_msg, tool_name, "UNKNOWN_TOOL_TYPE")
            
            # Step 3: Validate Result
            execution_time = time.time() - execution_start
            logger.info(f"Tool '{tool_name}' completed successfully in {execution_time:.2f}s")
            
            # Validate JSON format
            is_valid, validation_msg = self._validate_json_response(final_result, tool_name)
            if not is_valid:
                logger.error(f"Tool '{tool_name}' returned invalid JSON: {validation_msg}")
                self._log_execution(tool_name, False, "INVALID_JSON")
                return self._format_error_response(f"Invalid JSON response: {validation_msg}", 
                                                 tool_name, "INVALID_JSON")
            
            self._log_execution(tool_name, True, execution_time=execution_time)
            return final_result
            
        except Exception as e:
            execution_time = time.time() - execution_start
            error_msg = f"Tool '{tool_name}' failed after {execution_time:.2f}s: {str(e)}"
            logger.error(error_msg)
            logger.error(f"Exception details: {type(e).__name__}")
            logger.debug(f"Full traceback: {traceback.format_exc()}")
            
            self._log_execution(tool_name, False, "EXECUTION_ERROR")
            return self._format_error_response(error_msg, tool_name, "EXECUTION_ERROR", str(e))

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
                    formatted_content = str(content)
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
                        instance = tool_class()
                        result = tool.func.__get__(instance)(**kwargs)
                    else:
                        result = tool.func(**kwargs)
            
            # Format result
            if isinstance(result, (dict, list)):
                content = json.dumps(result, ensure_ascii=False, indent=2)
                return json.dumps({"content": content}, ensure_ascii=False, indent=2)
            else:
                return json.dumps({"content": str(result)}, ensure_ascii=False, indent=2)
                
        except Exception as e:
            logger.error(f"Standard tool execution failed: {tool.name} - {str(e)}")
            raise

    def _execute_agent_tool(self, tool: AgentToolSpec, messages: list, session_id: str) -> str:
        """Execute agent tool and format result"""
        logger.debug(f"Executing agent tool: {tool.name}")
        
        try:
            result = tool.func(messages=messages, session_id=session_id)
            return json.dumps({"messages": result}, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Agent tool execution failed: {tool.name} - {str(e)}")
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
        
        if session_id not in self._mcp_sessions:
            self._mcp_sessions[session_id] = {}
        
        server_name = tool.server_name
        logger.debug(f"MCP tool execution: {tool.name} on {server_name}")
        
        try:
            if isinstance(tool.server_params, SseServerParameters):
                return await self._execute_sse_mcp_tool(tool, **kwargs)
            else:
                return await self._execute_stdio_mcp_tool(tool, **kwargs)
        except Exception as e:
            logger.error(f"MCP tool '{tool.name}' failed on server '{server_name}': {str(e)}")
            logger.debug(f"MCP error details - Tool: {tool.name}, Server: {server_name}, Args: {kwargs}")
            raise

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

    def get_execution_stats(self) -> dict:
        """获取工具执行统计信息"""
        total = max(1, self.execution_stats['total_executions'])
        return {
            **self.execution_stats,
            'success_rate': (self.execution_stats['successful_executions'] / total) * 100,
            'total_tools_registered': len(self.tools)
        }

    def _log_execution(self, tool_name: str, success: bool, error_type: str = None, execution_time: float = None):
        """记录工具执行统计"""
        self.execution_stats['total_executions'] += 1
        
        if tool_name not in self.execution_stats['tools_called']:
            self.execution_stats['tools_called'][tool_name] = {'success': 0, 'failed': 0, 'avg_time': 0}
            
        if success:
            self.execution_stats['successful_executions'] += 1
            self.execution_stats['tools_called'][tool_name]['success'] += 1
            if execution_time:
                prev_avg = self.execution_stats['tools_called'][tool_name].get('avg_time', 0)
                count = self.execution_stats['tools_called'][tool_name]['success']
                self.execution_stats['tools_called'][tool_name]['avg_time'] = (prev_avg * (count - 1) + execution_time) / count
        else:
            self.execution_stats['failed_executions'] += 1
            self.execution_stats['tools_called'][tool_name]['failed'] += 1
            
            if error_type:
                self.execution_stats['error_types'][error_type] = self.execution_stats['error_types'].get(error_type, 0) + 1

    def print_execution_summary(self):
        """Print a summary of tool execution statistics"""
        stats = self.get_execution_stats()
        print("\n" + "="*50)
        print("🔧 TOOL EXECUTION SUMMARY")
        print("="*50)
        print(f"Total executions: {stats['total_executions']}")
        print(f"Success rate: {stats['success_rate']:.1f}%")
        print(f"Total tools registered: {stats['total_tools_registered']}")
        
        if stats['error_types']:
            print("\nError breakdown:")
            for error_type, count in stats['error_types'].items():
                print(f"  {error_type}: {count}")
        
        if stats['tools_called']:
            print("\nMost used tools:")
            sorted_tools = sorted(stats['tools_called'].items(), 
                                key=lambda x: x[1]['success'] + x[1]['failed'], reverse=True)
            for tool_name, tool_stats in sorted_tools[:5]:
                total_calls = tool_stats['success'] + tool_stats['failed']
                success_rate = (tool_stats['success'] / total_calls) * 100 if total_calls > 0 else 0
                avg_time = tool_stats.get('avg_time', 0)
                print(f"  {tool_name}: {total_calls} calls, {success_rate:.1f}% success, {avg_time:.2f}s avg")
        print("="*50)

    async def _run_mcp_tool(self, tool: McpToolSpec, session_id: str = None, **kwargs) -> CallToolResult:
        """Run an MCP tool through its server connection (legacy compatibility)"""
        return await self._run_mcp_tool_async(tool, session_id, **kwargs)
