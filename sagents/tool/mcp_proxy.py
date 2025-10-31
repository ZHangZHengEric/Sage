from typing import Dict, Any, List, Type, Optional, Union

from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession, Tool

from .tool_config import McpToolSpec,SseServerParameters,StreamableHttpServerParameters, StdioServerParameters

class McpProxy:

    async def run_mcp_tool(self, tool: McpToolSpec, session_id: str = None, **kwargs) -> Any:
        """Run an MCP tool asynchronously"""
        if not session_id:
            session_id = "default"
        try:
            if isinstance(tool.server_params, SseServerParameters):
                return await self._execute_sse_mcp_tool(tool, **kwargs)
            elif isinstance(tool.server_params, StreamableHttpServerParameters):
                return await self._execute_streamable_http_mcp_tool(tool, **kwargs)
            elif isinstance(tool.server_params, StdioServerParameters):
                return await self._execute_stdio_mcp_tool(tool, **kwargs)
            else:
                raise ValueError(f"Unknown server params type: {type(tool.server_params)}")
        except Exception as e:
            raise e

    async def get_mcp_tools(self, server_name: str, server_params: Union[SseServerParameters, StreamableHttpServerParameters, StdioServerParameters]) -> List[Tool]:
        """Get MCP tools"""
        try:
            if isinstance(server_params, SseServerParameters):
                return await self._get_mcp_tools_sse(server_name, server_params)
            elif isinstance(server_params, StreamableHttpServerParameters):
                return await self._get_mcp_tools_streamable_http(server_name, server_params)  
            elif isinstance(server_params, StdioServerParameters):
                return await self._get_mcp_tools_stdio(server_name, server_params)
            else:
                raise ValueError(f"Unknown server params type: {type(server_params)}")
        except Exception as e:
            raise e

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


    async def _get_mcp_tools_streamable_http(self, server_name: str, server_params: StreamableHttpServerParameters) -> List[Tool]:
        """Register tools from streamable HTTP MCP server"""
        try:
            async with streamablehttp_client(server_params.url) as (read, write,_):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.list_tools()
                    tools = response.tools
                    return tools
        except Exception as e:
            """ 抛出异常"""
            raise e

    async def _get_mcp_tools_sse(self, server_name: str, server_params: SseServerParameters) -> List[Tool]:
        """Register tools from SSE MCP server"""

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
                    await session.initialize()
                    response = await session.list_tools()
                    tools = response.tools
                    return tools
        except Exception as e:
            """ 抛出异常"""
            raise e

    async def _get_mcp_tools_stdio(self, server_name: str, server_params: StdioServerParameters) -> List[Tool]:
        """Register tools from stdio MCP server"""
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    response = await session.list_tools()
                    tools = response.tools
                    return tools
        except Exception as e:
            """ 抛出异常"""
            raise e