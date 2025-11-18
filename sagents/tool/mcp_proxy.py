from typing import Dict, Any, List, Type, Optional, Union
import httpx

from mcp.client.stdio import stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession, Tool

from .tool_config import McpToolSpec, SseServerParameters, StreamableHttpServerParameters, StdioServerParameters


# 专用异常类型，用于更精确地区分失败原因
class McpConnectionError(Exception):
    """MCP 连接建立失败（进入流式 HTTP 上下文前失败）"""


class McpInitializationError(Exception):
    """MCP 会话初始化失败（调用 session.initialize() 时失败）"""


class McpToolsRetrievalError(Exception):
    """MCP 工具列表获取失败（调用 session.list_tools() 时失败）"""


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
        headers = None
        if tool.server_params.api_key:
            headers = {
                "Authorization": f"Bearer {tool.server_params.api_key}",
                "Content-Type": "application/json"
            }
        async with sse_client(tool.server_params.url, headers=headers) as (read, write):
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
        # 如果需要鉴权，附加请求头
        headers = None
        if getattr(server_params, "api_key", None):
            headers = {
                "Authorization": f"Bearer {server_params.api_key}",
                "Content-Type": "application/json",
            }

        entered_context = False  # 标记是否成功进入 streamable http 上下文
        try:
            async with streamablehttp_client(server_params.url, headers=headers) as (read, write, _):
                entered_context = True
                async with ClientSession(read, write) as session:
                    # 初始化失败分类
                    try:
                        await session.initialize()
                    except Exception as init_err:
                        raise McpInitializationError(
                            f"MCP 初始化失败: server='{server_name}', url='{server_params.url}'"
                        ) from init_err

                    # 获取工具列表失败分类
                    try:
                        response = await session.list_tools()
                        tools = response.tools
                        return tools
                    except Exception as list_err:
                        raise McpToolsRetrievalError(
                            f"MCP 工具获取失败: server='{server_name}', url='{server_params.url}'"
                        ) from list_err
        except BaseExceptionGroup as eg:
            # 解包并识别 HTTP 状态错误（如 502、503 等）
            exceptions = getattr(eg, "exceptions", None)
            if exceptions is None:
                exceptions = []
            elif not isinstance(exceptions, (list, tuple)):
                exceptions = [exceptions]

            http_errors = [
                ex for ex in exceptions if isinstance(ex, httpx.HTTPStatusError)
            ]
            if http_errors:
                first = http_errors[0]
                status_code = getattr(getattr(first, "response", None), "status_code", None)
                raise McpConnectionError(
                    f"MCP 服务器HTTP错误: status={status_code}, server='{server_name}', url='{server_params.url}'"
                ) from first
            # 其它异常组统一视作连接层故障
            raise McpConnectionError(
                f"MCP 连接异常组: server='{server_name}', url='{server_params.url}'"
            ) from eg
        except Exception as e:
            # 在进入上下文前的错误视为连接问题
            if not entered_context:
                raise McpConnectionError(
                    f"MCP 连接失败: server='{server_name}', url='{server_params.url}'"
                ) from e
            # 其他情况直接抛出原始错误（已被内部分类处理）
            raise

    async def _get_mcp_tools_sse(self, server_name: str, server_params: SseServerParameters) -> List[Tool]:
        """Register tools from SSE MCP server"""

        try:
            headers = None
            if server_params.api_key:
                headers = {
                    "Authorization": f"Bearer {server_params.api_key}",
                    "Content-Type": "application/json"
                }
            async with sse_client(server_params.url, headers=headers) as (read, write):
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
