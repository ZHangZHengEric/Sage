import asyncio
import hashlib
import json
import os
import time
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

import httpx
from mcp import ClientSession, StdioServerParameters, Tool
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from sagents.utils.logger import logger

from .tool_schema import SseServerParameters, StreamableHttpServerParameters


ServerParams = Union[
    SseServerParameters,
    StreamableHttpServerParameters,
    StdioServerParameters,
]


def _env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
        return max(value, minimum)
    except Exception:
        logger.warning(f"Invalid integer env {name}={raw!r}, using {default}")
        return default


def _env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
        return max(value, minimum)
    except Exception:
        logger.warning(f"Invalid float env {name}={raw!r}, using {default}")
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _get_config_int(
    config: Optional[Dict[str, Any]],
    keys: List[str],
    default: int,
    minimum: int = 0,
) -> int:
    if isinstance(config, dict):
        for key in keys:
            if key not in config:
                continue
            try:
                return max(int(config[key]), minimum)
            except Exception:
                logger.warning(f"Invalid MCP config integer {key}={config[key]!r}")
    return default


def _get_config_float(
    config: Optional[Dict[str, Any]],
    keys: List[str],
    default: float,
    minimum: float = 0.0,
) -> float:
    if isinstance(config, dict):
        for key in keys:
            if key not in config:
                continue
            try:
                return max(float(config[key]), minimum)
            except Exception:
                logger.warning(f"Invalid MCP config float {key}={config[key]!r}")
    return default


def _server_protocol(server_params: ServerParams) -> str:
    if isinstance(server_params, SseServerParameters):
        return "sse"
    if isinstance(server_params, StreamableHttpServerParameters):
        return "streamable_http"
    if isinstance(server_params, StdioServerParameters):
        return "stdio"
    return type(server_params).__name__


def _server_params_payload(server_params: ServerParams) -> Dict[str, Any]:
    if isinstance(server_params, SseServerParameters):
        return {
            "protocol": "sse",
            "url": server_params.url,
            "api_key": server_params.api_key or "",
        }
    if isinstance(server_params, StreamableHttpServerParameters):
        return {
            "protocol": "streamable_http",
            "url": server_params.url,
            "api_key": server_params.api_key or "",
        }
    if isinstance(server_params, StdioServerParameters):
        return {
            "protocol": "stdio",
            "command": server_params.command,
            "args": list(server_params.args or []),
            "env": dict(server_params.env or {}),
            "cwd": str(getattr(server_params, "cwd", "") or ""),
            "encoding": getattr(server_params, "encoding", "utf-8"),
            "encoding_error_handler": getattr(
                server_params, "encoding_error_handler", "strict"
            ),
        }
    return {"protocol": type(server_params).__name__, "repr": repr(server_params)}


def config_fingerprint(
    server_name: str,
    server_params: ServerParams,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    payload = {
        "server_name": server_name.strip(),
        "server_params": _server_params_payload(server_params),
        "config": config or {},
        "per_connection_concurrency": _get_config_int(
            config,
            ["per_connection_concurrency", "max_concurrency"],
            _env_int("SAGE_MCP_PER_CONNECTION_CONCURRENCY", 100, minimum=1),
            minimum=1,
        ),
        "max_connections_per_server": _get_config_int(
            config,
            ["max_connections_per_server"],
            _env_int("SAGE_MCP_MAX_CONNECTIONS_PER_SERVER", 0, minimum=0),
            minimum=0,
        ),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return True
    if isinstance(exc, (ConnectionError, EOFError, TimeoutError, OSError)):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    module = type(exc).__module__
    if module == "anyio" or module.startswith("anyio."):
        return True
    text = str(exc).lower()
    return any(
        marker in text
        for marker in (
            "closed",
            "broken",
            "connection",
            "disconnect",
            "eof",
            "reset",
            "stream",
            "transport",
        )
    )


class McpPooledConnection:
    def __init__(self, server_name: str, server_params: ServerParams):
        self.server_name = server_name
        self.server_params = server_params
        self.session: Optional[ClientSession] = None
        self.active_requests = 0
        self.last_used_at = time.monotonic()
        self.closed = False
        self._stack = AsyncExitStack()

    async def open(self) -> "McpPooledConnection":
        protocol = _server_protocol(self.server_params)
        if isinstance(self.server_params, SseServerParameters):
            headers = self._headers(getattr(self.server_params, "api_key", None))
            read, write = await self._stack.enter_async_context(
                sse_client(self.server_params.url, headers=headers)
            )
        elif isinstance(self.server_params, StreamableHttpServerParameters):
            headers = self._headers(getattr(self.server_params, "api_key", None))
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(self.server_params.url, headers=headers)
            )
        elif isinstance(self.server_params, StdioServerParameters):
            read, write = await self._stack.enter_async_context(
                stdio_client(self.server_params)
            )
        else:
            raise ValueError(f"Unknown MCP server params type: {type(self.server_params)}")

        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        self.last_used_at = time.monotonic()
        logger.info(
            f"MCP connection initialized: server={self.server_name}, protocol={protocol}"
        )
        return self

    @staticmethod
    def _headers(api_key: Optional[str]) -> Optional[Dict[str, str]]:
        if not api_key:
            return None
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def can_accept(self, per_connection_concurrency: int) -> bool:
        return (
            not self.closed
            and self.session is not None
            and self.active_requests < per_connection_concurrency
        )

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self._stack.aclose()
        except Exception as exc:
            logger.debug(f"Failed to close MCP connection {self.server_name}: {exc}")


class McpServerPoolEntry:
    def __init__(
        self,
        server_name: str,
        server_params: ServerParams,
        fingerprint: str,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.server_name = server_name
        self.server_params = server_params
        self.fingerprint = fingerprint
        self.config = dict(config or {})
        self.per_connection_concurrency = _get_config_int(
            self.config,
            ["per_connection_concurrency", "max_concurrency"],
            _env_int("SAGE_MCP_PER_CONNECTION_CONCURRENCY", 100, minimum=1),
            minimum=1,
        )
        self.max_connections_per_server = _get_config_int(
            self.config,
            ["max_connections_per_server"],
            _env_int("SAGE_MCP_MAX_CONNECTIONS_PER_SERVER", 0, minimum=0),
            minimum=0,
        )
        self.idle_ttl_seconds = _env_float(
            "SAGE_MCP_SESSION_IDLE_TTL_SECONDS", 1800.0, minimum=0.0
        )
        self.drain_timeout_seconds = _env_float(
            "SAGE_MCP_REFRESH_DRAIN_TIMEOUT_SECONDS", 30.0, minimum=0.0
        )
        self.call_timeout_seconds = _get_config_float(
            self.config,
            ["call_timeout_seconds"],
            _env_float("SAGE_MCP_CALL_TIMEOUT_SECONDS", 1800.0, minimum=0.0),
            minimum=0.0,
        )
        self.connections: List[McpPooledConnection] = []
        self.tools_cache: Optional[List[Tool]] = None
        self.draining = False
        self._lock = asyncio.Lock()

    async def list_tools(self) -> List[Tool]:
        retry_enabled = _env_bool("SAGE_MCP_LIST_TOOLS_RETRY_ON_CONNECTION_ERROR", True)
        attempts = 2 if retry_enabled else 1
        last_error: Optional[BaseException] = None
        for attempt in range(attempts):
            connection: Optional[McpPooledConnection] = None
            try:
                async with self.checkout() as checked_out:
                    connection = checked_out
                    assert connection.session is not None
                    response = await connection.session.list_tools()
                    tools = response.tools
                    self.tools_cache = tools
                    return tools
            except Exception as exc:
                last_error = exc
                if connection is not None and _is_connection_error(exc):
                    await self.discard_connection(connection)
                    if attempt + 1 < attempts:
                        logger.warning(
                            f"MCP list_tools connection failed, retrying once: "
                            f"server={self.server_name}, error={exc}"
                        )
                        continue
                raise
            except BaseExceptionGroup as exc:
                last_error = exc
                if connection is not None:
                    await self.discard_connection(connection)
                    if attempt + 1 < attempts:
                        logger.warning(
                            f"MCP list_tools exception group, retrying once: "
                            f"server={self.server_name}, error={exc}"
                        )
                        continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"MCP list_tools failed: server={self.server_name}")

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        retry_enabled = _env_bool("SAGE_MCP_CALL_RETRY_ON_CONNECTION_ERROR", True)
        last_error: Optional[BaseException] = None
        attempts = 2 if retry_enabled else 1
        for attempt in range(attempts):
            connection: Optional[McpPooledConnection] = None
            try:
                async with self.checkout() as checked_out:
                    connection = checked_out
                    assert connection.session is not None
                    call = connection.session.call_tool(tool_name, arguments)
                    if self.call_timeout_seconds > 0:
                        return await asyncio.wait_for(
                            call,
                            timeout=self.call_timeout_seconds,
                        )
                    return await call
            except asyncio.TimeoutError as exc:
                last_error = exc
                if connection is not None:
                    await self.discard_connection(connection)
                raise TimeoutError(
                    f"MCP tool call timed out after {self.call_timeout_seconds:g}s: "
                    f"server={self.server_name}, tool={tool_name}"
                ) from exc
            except Exception as exc:
                last_error = exc
                if connection is not None and _is_connection_error(exc):
                    await self.discard_connection(connection)
                    if attempt + 1 < attempts:
                        logger.warning(
                            f"MCP connection failed, retrying once: "
                            f"server={self.server_name}, tool={tool_name}, error={exc}"
                        )
                        continue
                raise
            except BaseExceptionGroup as exc:
                last_error = exc
                if connection is not None:
                    await self.discard_connection(connection)
                    if attempt + 1 < attempts:
                        logger.warning(
                            f"MCP connection exception group, retrying once: "
                            f"server={self.server_name}, tool={tool_name}, error={exc}"
                        )
                        continue
                raise
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"MCP call failed: server={self.server_name}, tool={tool_name}")

    @asynccontextmanager
    async def checkout(self) -> AsyncGenerator[McpPooledConnection, None]:
        connection = await self._checkout()
        try:
            yield connection
        finally:
            await self._checkin(connection)

    async def _checkout(self) -> McpPooledConnection:
        async with self._lock:
            if self.draining:
                raise RuntimeError(f"MCP server pool is draining: {self.server_name}")
            await self._prune_idle_locked()
            for connection in self.connections:
                if connection.can_accept(self.per_connection_concurrency):
                    connection.active_requests += 1
                    connection.last_used_at = time.monotonic()
                    return connection

            if (
                self.max_connections_per_server > 0
                and len([c for c in self.connections if not c.closed])
                >= self.max_connections_per_server
            ):
                raise RuntimeError(
                    f"MCP server '{self.server_name}' reached max connections "
                    f"({self.max_connections_per_server})"
                )

            connection = await McpPooledConnection(
                self.server_name,
                self.server_params,
            ).open()
            connection.active_requests = 1
            self.connections.append(connection)
            return connection

    async def _checkin(self, connection: McpPooledConnection) -> None:
        async with self._lock:
            connection.active_requests = max(0, connection.active_requests - 1)
            connection.last_used_at = time.monotonic()

    async def discard_connection(self, connection: McpPooledConnection) -> None:
        async with self._lock:
            if connection in self.connections:
                self.connections.remove(connection)
        await connection.close()

    async def _prune_idle_locked(self) -> None:
        if self.idle_ttl_seconds <= 0:
            return
        now = time.monotonic()
        stale = [
            connection
            for connection in self.connections
            if (
                connection.active_requests == 0
                and not connection.closed
                and now - connection.last_used_at > self.idle_ttl_seconds
            )
        ]
        for connection in stale:
            self.connections.remove(connection)
            await connection.close()

    async def close(self, drain: bool = True) -> None:
        self.draining = True
        deadline = time.monotonic() + self.drain_timeout_seconds
        if drain and self.drain_timeout_seconds > 0:
            while any(c.active_requests > 0 for c in self.connections):
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(0.05)
        connections = list(self.connections)
        self.connections.clear()
        await asyncio.gather(
            *(connection.close() for connection in connections),
            return_exceptions=True,
        )


class McpConnectionPool:
    def __init__(self):
        self._entries: Dict[str, McpServerPoolEntry] = {}
        self._lock = asyncio.Lock()

    def get_cached_tools(
        self,
        server_name: str,
        server_params: ServerParams,
        config: Optional[Dict[str, Any]] = None,
    ) -> Optional[List[Tool]]:
        key = server_name.strip()
        entry = self._entries.get(key)
        fingerprint = config_fingerprint(key, server_params, config)
        if entry and entry.fingerprint == fingerprint and entry.tools_cache is not None:
            return entry.tools_cache
        return None

    async def list_tools(
        self,
        server_name: str,
        server_params: ServerParams,
        config: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> List[Tool]:
        key = server_name.strip()
        fingerprint = config_fingerprint(key, server_params, config)
        current = self._entries.get(key)

        if force:
            candidate = McpServerPoolEntry(key, server_params, fingerprint, config)
            async with self._lock:
                old = self._entries.get(key)
                self._entries[key] = candidate
            if old is not None and old is not candidate:
                await old.close(drain=False)
            return await candidate.list_tools()

        if (
            current is not None
            and current.fingerprint == fingerprint
            and current.tools_cache is not None
        ):
            return current.tools_cache

        if current is not None and current.fingerprint == fingerprint:
            return await current.list_tools()

        candidate = McpServerPoolEntry(key, server_params, fingerprint, config)
        tools = await candidate.list_tools()
        async with self._lock:
            old = self._entries.get(key)
            self._entries[key] = candidate
        if old is not None and old is not candidate:
            asyncio.create_task(old.close(drain=True))
        return tools

    async def call_tool(
        self,
        server_name: str,
        server_params: ServerParams,
        tool_name: str,
        arguments: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
    ) -> Any:
        entry = await self._get_or_create_entry(server_name, server_params, config)
        return await entry.call_tool(tool_name, arguments)

    async def _get_or_create_entry(
        self,
        server_name: str,
        server_params: ServerParams,
        config: Optional[Dict[str, Any]] = None,
    ) -> McpServerPoolEntry:
        key = server_name.strip()
        fingerprint = config_fingerprint(key, server_params, config)
        entry = self._entries.get(key)
        if entry is not None and (config is None or entry.fingerprint == fingerprint):
            return entry

        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None and (config is None or entry.fingerprint == fingerprint):
                return entry
            candidate = McpServerPoolEntry(key, server_params, fingerprint, config)
            old = self._entries.get(key)
            self._entries[key] = candidate
        if old is not None:
            asyncio.create_task(old.close(drain=True))
        return candidate

    async def close_server(self, server_name: str, drain: bool = True) -> None:
        key = server_name.strip()
        async with self._lock:
            entry = self._entries.pop(key, None)
        if entry is not None:
            await entry.close(drain=drain)

    async def close_all(self, drain: bool = True) -> None:
        async with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        await asyncio.gather(
            *(entry.close(drain=drain) for entry in entries),
            return_exceptions=True,
        )


_GLOBAL_MCP_CONNECTION_POOL: Optional[McpConnectionPool] = None


def get_global_mcp_connection_pool() -> McpConnectionPool:
    global _GLOBAL_MCP_CONNECTION_POOL
    if _GLOBAL_MCP_CONNECTION_POOL is None:
        _GLOBAL_MCP_CONNECTION_POOL = McpConnectionPool()
    return _GLOBAL_MCP_CONNECTION_POOL


async def close_global_mcp_connection_pool() -> None:
    global _GLOBAL_MCP_CONNECTION_POOL
    if _GLOBAL_MCP_CONNECTION_POOL is not None:
        await _GLOBAL_MCP_CONNECTION_POOL.close_all(drain=True)
        _GLOBAL_MCP_CONNECTION_POOL = None
