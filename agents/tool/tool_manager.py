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
    def __init__(self,is_auto_discover=True):
        """初始化工具管理器"""
        logger.info("Initializing ToolManager")
        self.tools: Dict[str, Union[ToolSpec, McpToolSpec,AgentToolSpec]] = {}
        self._mcp_sessions: Dict[str, Dict[str, Union[ClientSession]]] = {}  # {session_id: {server_name: session}}
        if is_auto_discover:
            self._auto_discover_tools()
            self._mcp_setting_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),'mcp_servers', 'mcp_setting.json')
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
                    server_params = SseServerParameters(url=config['sse_url'])
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
            async with sse_client(server_params.url) as (read, write):
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

    def run_tool(self, tool_name: str,messages:list ,session_id: str, **kwargs) -> Any:
        """Execute a tool by name with provided arguments"""
        logger.info(f"Running tool: {tool_name} with {len(kwargs)} arguments")
        session_id = kwargs.pop('session_id', None)
        logger.debug(f"Session ID for tool execution: {session_id}")
        tool = self.get_tool(tool_name)
        if not tool:
            error_msg = f"Tool not found: {tool_name}"
            logger.error(error_msg)
            return f"Error: {error_msg}"
        
        try:
            if isinstance(tool, McpToolSpec):
                logger.debug(f"Executing MCP tool: {tool_name}")
                mcp_tool_result  = asyncio.run(self._run_mcp_tool(tool, session_id=session_id, **kwargs))
                return json.dumps(mcp_tool_result,ensure_ascii=False, indent=2)
            elif isinstance(tool, ToolSpec):
                if hasattr(tool.func, '__self__'):
                    execute_result = tool.func(**kwargs)
                else:
                    tool_class = getattr(tool.func, '__objclass__', None)
                    print('tool_class',tool_class)
                    if tool_class:
                        instance = tool_class()
                        execute_result = tool.func.__get__(instance)(**kwargs)
                    else:
                        execute_result = tool.func(**kwargs)
                if isinstance(execute_result, dict) or instanceof(execute_result, list):
                    return json.dumps({"content":json.dumps(execute_result,ensure_ascii=False,indent=2)},ensure_ascii=False, indent=2)
                else:
                    return json.dumps({"content": execute_result},ensure_ascii=False, indent=2)
            elif isinstance(tool, AgentToolSpec):
                logger.debug(f"Executing AgentToolSpec: {tool_name}")
                agent_tool_result = tool.func(messages=messages,session_id=session_id)
                return json.dumps({"messages": agent_tool_result},ensure_ascii=False, indent=2)
        except Exception as e:
            error_msg = f"Error executing tool {tool_name}: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            return f"Error: {error_msg}"

    async def _run_mcp_tool(self, tool: McpToolSpec, session_id: str = None, **kwargs) -> CallToolResult:
        """Run an MCP tool through its server connection"""
        logger.debug(f"Running MCP tool: {tool.name} with session ID: {session_id}")
        if not session_id:
            session_id = "default"
            logger.debug(f"No session ID provided, using default")
        
        if session_id not in self._mcp_sessions:
            self._mcp_sessions[session_id] = {}
            logger.debug(f"Created new session mapping for session ID: {session_id}")
        
        server_name = tool.server_name
        logger.debug(f"Server name for tool {tool.name}: {server_name}")
        
        # Get or create server session
        # if server_name not in self._mcp_sessions[session_id]:
        logger.debug(f"Creating new MCP session for server: {server_name}")
        if isinstance(tool.server_params, SseServerParameters):
            async with sse_client(tool.server_params.url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._mcp_sessions[session_id][server_name] = session
                    logger.debug(f"Created new SSE session for server: {server_name}")
                    logger.debug(f"Calling MCP tool {tool.name} with arguments: {kwargs}")
                    try:
                        result = await session.call_tool(tool.name, kwargs)
                        logger.debug(f"MCP tool {tool.name} execution completed successfully")
                        return result.model_dump()
                    except Exception as e:
                        error_msg = f"Error calling MCP tool {tool.name}: {str(e)}"
                        logger.error(error_msg)
                        logger.error(traceback.format_exc())
                        return f"Error: {error_msg}"
        else:
            async with stdio_client(tool.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._mcp_sessions[session_id][server_name] = session
                    logger.debug(f"Created new stdio session for server: {server_name}")
                    # Use existing session to call tool
                    logger.debug(f"Calling MCP tool {tool.name} with arguments: {kwargs}")
                    try:
                        result = await session.call_tool(tool.name, kwargs)
                        logger.debug(f"MCP tool {tool.name} execution completed successfully")
                        return result.model_dump()
                    except Exception as e:
                        error_msg = f"Error calling MCP tool {tool.name}: {str(e)}"
                        logger.error(error_msg)
                        logger.error(traceback.format_exc())
                        return f"Error: {error_msg}"
        
        

    # [Remaining methods stay unchanged...]
