from typing import Any, Dict, List, Optional, Union, cast

try:
    from builtins import BaseExceptionGroup
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from exceptiongroup import BaseExceptionGroup
from mcp import Tool, StdioServerParameters
from mcp.types import TextContent

from .mcp_connection_pool import (
    McpConnectionPool,
    get_global_mcp_connection_pool,
)
from .tool_schema import (
    McpToolSpec,
    SseServerParameters,
    StreamableHttpServerParameters,
)


# 专用异常类型，用于更精确地区分失败原因
class McpConnectionError(Exception):
    """MCP 连接建立失败（进入流式 HTTP 上下文前失败）"""


class McpInitializationError(Exception):
    """MCP 会话初始化失败（调用 session.initialize() 时失败）"""


class McpToolsRetrievalError(Exception):
    """MCP 工具列表获取失败（调用 session.list_tools() 时失败）"""


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


class McpProxy:
    def __init__(self, isolated: bool = False):
        self._pool = (
            McpConnectionPool() if isolated else get_global_mcp_connection_pool()
        )

    async def run_mcp_tool(
        self,
        tool: McpToolSpec,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Run an MCP tool asynchronously"""
        if not session_id:
            session_id = "default"
        # 只有当工具参数定义中包含 session_id / user_id 时才传递
        tool_params = getattr(tool, "parameters", {}) or {}
        is_anytool_server = getattr(tool, "server_name", "") == "AnyTool"
        if is_anytool_server:
            if session_id and "session_id" not in kwargs:
                kwargs["session_id"] = session_id
            if user_id and "user_id" not in kwargs:
                kwargs["user_id"] = user_id
        if "session_id" in tool_params:
            kwargs["session_id"] = session_id
        if user_id and "user_id" in tool_params and "user_id" not in kwargs:
            kwargs["user_id"] = user_id
        try:
            if isinstance(tool.server_params, SseServerParameters):
                return await self._execute_sse_mcp_tool(tool, **kwargs)
            elif isinstance(tool.server_params, StreamableHttpServerParameters):
                return await self._execute_streamable_http_mcp_tool(tool, **kwargs)
            elif isinstance(tool.server_params, StdioServerParameters):
                return await self._execute_stdio_mcp_tool(tool, **kwargs)
            else:
                raise ValueError(
                    f"Unknown server params type: {type(tool.server_params)}"
                )
        except BaseExceptionGroup as eg:
            _raise_innermost_exception(eg)

    async def _call_pooled_tool(self, tool: McpToolSpec, **kwargs) -> Any:
        result = await self._pool.call_tool(
            tool.server_name,
            tool.server_params,
            tool.name,
            kwargs,
        )
        if result.isError:
            err = cast(TextContent, result.content[0])
            raise Exception(err.text)
        return result.model_dump()

    async def get_mcp_tools(
        self,
        server_name: str,
        server_params: Union[
            SseServerParameters, StreamableHttpServerParameters, StdioServerParameters
        ],
        config: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> List[Tool]:
        """Get MCP tools"""
        try:
            if not isinstance(
                server_params,
                (
                    SseServerParameters,
                    StreamableHttpServerParameters,
                    StdioServerParameters,
                ),
            ):
                raise ValueError(f"Unknown server params type: {type(server_params)}")
            return await self._pool.list_tools(
                server_name,
                server_params,
                config=config,
                force=force,
            )
        except Exception:
            raise

    def get_cached_tools(
        self,
        server_name: str,
        server_params: Union[
            SseServerParameters, StreamableHttpServerParameters, StdioServerParameters
        ],
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Tool]]:
        return self._pool.get_cached_tools(server_name, server_params, config=config)

    async def close_server(self, server_name: str, drain: bool = True) -> None:
        await self._pool.close_server(server_name, drain=drain)

    async def close_all(self, drain: bool = True) -> None:
        await self._pool.close_all(drain=drain)

    async def _execute_streamable_http_mcp_tool(
        self, tool: McpToolSpec, **kwargs
    ) -> Any:
        """Execute streamable HTTP MCP tool"""
        try:
            return await self._call_pooled_tool(tool, **kwargs)
        except BaseExceptionGroup as eg:
            _raise_innermost_exception(eg)

    async def _execute_sse_mcp_tool(self, tool: McpToolSpec, **kwargs) -> Any:
        """Execute SSE MCP tool"""
        try:
            return await self._call_pooled_tool(tool, **kwargs)
        except BaseExceptionGroup as eg:
            _raise_innermost_exception(eg)

    async def _execute_stdio_mcp_tool(self, tool: McpToolSpec, **kwargs) -> Any:
        """Execute stdio MCP tool"""
        try:
            return await self._call_pooled_tool(tool, **kwargs)
        except BaseExceptionGroup as eg:
            _raise_innermost_exception(eg)

    async def _get_mcp_tools_streamable_http(
        self, server_name: str, server_params: StreamableHttpServerParameters
    ) -> List[Tool]:
        """Register tools from streamable HTTP MCP server"""
        try:
            return await self.get_mcp_tools(server_name, server_params)
        except BaseExceptionGroup as eg:
            raise McpConnectionError(
                f"MCP 连接异常组: server='{server_name}', url='{server_params.url}'"
            ) from eg
        except Exception as e:
            raise McpConnectionError(
                f"MCP 连接失败: server='{server_name}', url='{server_params.url}'"
            ) from e

    async def _get_mcp_tools_sse(
        self, server_name: str, server_params: SseServerParameters
    ) -> List[Tool]:
        """Register tools from SSE MCP server"""

        try:
            return await self.get_mcp_tools(server_name, server_params)
        except Exception:
            raise

    async def _get_mcp_tools_stdio(
        self, server_name: str, server_params: StdioServerParameters
    ) -> List[Tool]:
        """Register tools from stdio MCP server"""
        try:
            return await self.get_mcp_tools(server_name, server_params)
        except Exception:
            raise
