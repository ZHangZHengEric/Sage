"""Shared official MCP SDK session lifecycle for Tool transports."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Protocol


class McpClientSession(Protocol):
    async def initialize(self) -> Any: ...
    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


@asynccontextmanager
async def sdk_session(config: Any) -> AsyncIterator[McpClientSession]:
    """Open and initialize one official MCP Python SDK client session."""

    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.sse import sse_client
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamablehttp_client
    except ImportError as exc:  # pragma: no cover - depends on host packaging
        raise RuntimeError("the optional 'mcp' package is not installed") from exc

    headers = (
        {"Authorization": f"Bearer {config.api_key.get_secret_value()}"}
        if config.api_key
        else None
    )
    async with AsyncExitStack() as stack:
        if config.protocol == "stdio":
            if not config.command:
                raise ValueError("stdio MCP requires command")
            streams = await stack.enter_async_context(
                stdio_client(
                    StdioServerParameters(
                        command=config.command,
                        args=list(config.args),
                        env=dict(config.env),
                    )
                )
            )
            read, write = streams
        elif config.protocol == "sse":
            if not config.url:
                raise ValueError("SSE MCP requires URL")
            read, write = await stack.enter_async_context(
                sse_client(config.url, headers=headers, timeout=config.timeout_seconds)
            )
        else:
            if not config.url:
                raise ValueError("streamable HTTP MCP requires URL")
            read, write, _ = await stack.enter_async_context(
                streamablehttp_client(
                    config.url, headers=headers, timeout=config.timeout_seconds
                )
            )
        session = await stack.enter_async_context(ClientSession(read, write))
        await asyncio.wait_for(session.initialize(), timeout=config.timeout_seconds)
        yield session
