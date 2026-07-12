import asyncio
import hashlib
import json
import os
import time
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

try:
    from builtins import BaseExceptionGroup
except ImportError:  # pragma: no cover - Python < 3.11 compatibility
    from exceptiongroup import BaseExceptionGroup

import httpx
from fastmcp import Client as FastMCPClient
from fastmcp.client.transports import SSETransport, StreamableHttpTransport
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


class McpConnectionStaleError(ConnectionError):
    """Raised when a pooled MCP connection is stale before a request is sent."""


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


def _extract_server_generation(value: Any) -> Optional[str]:
    if value is None:
        return None

    payload: Optional[Dict[str, Any]] = None
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        dumped: Any = model_dump()
        if isinstance(dumped, dict):
            payload = dumped
    elif isinstance(value, dict):
        payload = value

    if not isinstance(payload, dict):
        return None

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        return None

    observed = metadata.get("server_generation")
    if observed:
        return str(observed)

    return None


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
    if isinstance(exc, httpx.HTTPStatusError):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code in {400, 404, 410}:
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
            "eof",
            "closed resource",
            "broken pipe",
            "connection reset",
            "session terminated",
            "session expired",
            "session not found",
            "session task",
            "client failed to connect",
            "server session was closed",
            "connection closed",
            "closed unexpectedly",
        )
    )


class McpPooledConnection:
    def __init__(self, server_name: str, server_params: ServerParams):
        self.server_name = server_name
        self.server_params = server_params
        self.session: Optional[ClientSession] = None
        self.server_generation: Optional[str] = None
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
            raise ValueError(
                f"Unknown MCP server params type: {type(self.server_params)}"
            )

        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        initialize_result = await self.session.initialize()
        self.server_generation = _extract_server_generation(initialize_result)
        self.last_used_at = time.monotonic()
        logger.info(
            f"MCP connection initialized: server={self.server_name}, "
            f"protocol={protocol}, server_generation={self.server_generation or '-'}"
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
        raise RuntimeError(
            f"MCP call failed: server={self.server_name}, tool={tool_name}"
        )

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


HttpClientServerParams = Union[SseServerParameters, StreamableHttpServerParameters]


def _is_http_client_server_params(server_params: ServerParams) -> bool:
    return isinstance(
        server_params, (SseServerParameters, StreamableHttpServerParameters)
    )


class McpHttpClientPoolEntry:
    """Long-lived FastMCP client with unrestricted concurrent requests."""

    def __init__(
        self,
        server_name: str,
        server_params: HttpClientServerParams,
        fingerprint: str,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.server_name = server_name
        self.server_params = server_params
        self.fingerprint = fingerprint
        self.config = dict(config or {})
        self.connect_timeout_seconds = _get_config_float(
            self.config,
            ["connect_timeout_seconds"],
            _env_float("SAGE_MCP_CONNECT_TIMEOUT_SECONDS", 20.0, minimum=0.01),
            minimum=0.01,
        )
        self.list_tools_timeout_seconds = _get_config_float(
            self.config,
            ["list_tools_timeout_seconds"],
            _env_float("SAGE_MCP_LIST_TOOLS_TIMEOUT_SECONDS", 60.0, minimum=0.01),
            minimum=0.01,
        )
        self.call_timeout_seconds = _get_config_float(
            self.config,
            ["call_timeout_seconds"],
            _env_float("SAGE_MCP_CALL_TIMEOUT_SECONDS", 1800.0, minimum=0.01),
            minimum=0.01,
        )
        self.close_timeout_seconds = _get_config_float(
            self.config,
            ["close_timeout_seconds"],
            _env_float("SAGE_MCP_CLOSE_TIMEOUT_SECONDS", 5.0, minimum=0.01),
            minimum=0.01,
        )
        self.drain_timeout_seconds = _env_float(
            "SAGE_MCP_REFRESH_DRAIN_TIMEOUT_SECONDS", 30.0, minimum=0.0
        )
        self.tools_cache: Optional[List[Tool]] = None
        self.draining = False
        self._closed = False
        self._client: Optional[FastMCPClient] = None
        self._active_requests = 0
        self._idle_event = asyncio.Event()
        self._idle_event.set()
        self._lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()

    @property
    def closed(self) -> bool:
        return self._closed or self._client_session_done(self._client)

    @property
    def has_fresh_tools_cache(self) -> bool:
        return self.tools_cache is not None and not self.draining and not self.closed

    @staticmethod
    def _client_session_done(client: Optional[FastMCPClient]) -> bool:
        if client is None:
            return False
        return not client.is_connected()

    def _build_client(self) -> FastMCPClient:
        api_key = getattr(self.server_params, "api_key", None)
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
        transport_cls = (
            SSETransport
            if isinstance(self.server_params, SseServerParameters)
            else StreamableHttpTransport
        )
        transport = transport_cls(
            self.server_params.url,
            headers=headers,
        )
        return FastMCPClient(
            transport,
            name=f"sage:{self.server_name}",
            timeout=self.call_timeout_seconds,
            init_timeout=self.connect_timeout_seconds,
        )

    async def _checkout_client(self) -> FastMCPClient:
        async with self._lock:
            if self.draining or self._closed:
                raise RuntimeError(f"MCP client is draining: {self.server_name}")
            client = self._client
            if client is None or self._client_session_done(client):
                if client is not None:
                    await self._close_client_instance(client)
                client = self._build_client()
                try:
                    await asyncio.wait_for(
                        client.__aenter__(),
                        timeout=self.connect_timeout_seconds,
                    )
                except asyncio.CancelledError:
                    await self._close_client_instance(client)
                    raise
                except BaseException as exc:
                    await self._close_client_instance(client)
                    raise McpConnectionStaleError(
                        f"FastMCP client failed to connect: "
                        f"server={self.server_name}, error={exc}"
                    ) from exc
                self._client = client
                self._closed = False
                logger.info(
                    f"FastMCP client connected: server={self.server_name}, "
                    f"protocol={_server_protocol(self.server_params)}"
                )
            self._active_requests += 1
            self._idle_event.clear()
            return client

    async def _checkin_client(self) -> None:
        async with self._lock:
            self._active_requests = max(0, self._active_requests - 1)
            idle = self._active_requests == 0
            if idle:
                self._idle_event.set()
            should_close = idle and self.draining
        if should_close:
            await self._close_current_client()

    async def list_tools(self) -> List[Tool]:
        client = await self._checkout_client()
        try:
            tools = await asyncio.wait_for(
                client.list_tools(),
                timeout=self.list_tools_timeout_seconds,
            )
            self.tools_cache = tools
            return tools
        finally:
            await self._checkin_client()

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        client = await self._checkout_client()
        try:
            return await client.call_tool_mcp(
                tool_name,
                arguments,
                timeout=self.call_timeout_seconds,
            )
        finally:
            await self._checkin_client()

    async def retire(self, reason: str) -> None:
        logger.info(
            f"Retiring FastMCP client: server={self.server_name}, reason={reason}"
        )
        async with self._lock:
            if self._closed:
                return
            self.draining = True
            should_close = self._active_requests == 0
        if should_close:
            await self._close_current_client()

    async def close(self, drain: bool = True) -> None:
        async with self._lock:
            self.draining = True
            has_active = self._active_requests > 0
        if drain and has_active and self.drain_timeout_seconds > 0:
            try:
                await asyncio.wait_for(
                    self._idle_event.wait(),
                    timeout=self.drain_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"FastMCP client drain timed out: server={self.server_name}"
                )
        await self._close_current_client()

    async def _close_current_client(self) -> None:
        async with self._close_lock:
            async with self._lock:
                client = self._client
                self._client = None
                self._closed = True
            if client is not None:
                await self._close_client_instance(client)

    async def _close_client_instance(self, client: FastMCPClient) -> None:
        try:
            await asyncio.wait_for(
                client.close(),
                timeout=self.close_timeout_seconds,
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"FastMCP client close timed out after "
                f"{self.close_timeout_seconds:g}s: server={self.server_name}"
            )
        except Exception as exc:
            logger.debug(f"Failed to close FastMCP client {self.server_name}: {exc}")


class McpConnectionPool:
    def __init__(self):
        self._entries: Dict[str, Union[McpServerPoolEntry, McpHttpClientPoolEntry]] = {}
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
        if isinstance(entry, McpHttpClientPoolEntry):
            if (
                entry.fingerprint == fingerprint
                and not entry.draining
                and not entry.closed
                and entry.has_fresh_tools_cache
            ):
                return entry.tools_cache
            return None
        if (
            entry
            and entry.fingerprint == fingerprint
            and not entry.draining
            and not getattr(entry, "closed", False)
            and entry.tools_cache is not None
        ):
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
        if _is_http_client_server_params(server_params):
            entry = await self._get_or_create_http_client_entry(
                key,
                server_params,  # pyright: ignore[reportArgumentType]
                config,
                force=force,
            )
            retry_enabled = _env_bool(
                "SAGE_MCP_LIST_TOOLS_RETRY_ON_CONNECTION_ERROR", True
            )
            attempts = 2 if retry_enabled else 1
            for attempt in range(attempts):
                try:
                    return await entry.list_tools()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    if not _is_connection_error(exc) or attempt + 1 >= attempts:
                        raise
                    await self._discard_http_client_entry(key, entry)
                    logger.warning(
                        f"MCP {_server_protocol(server_params)} list_tools failed, "
                        f"reconnecting once: server={key}, error={exc}"
                    )
                    entry = await self._get_or_create_http_client_entry(
                        key,
                        server_params,  # pyright: ignore[reportArgumentType]
                        config,
                    )

        fingerprint = config_fingerprint(key, server_params, config)
        current = self._entries.get(key)

        if force:
            candidate = McpServerPoolEntry(key, server_params, fingerprint, config)
            async with self._lock:
                old = self._entries.get(key)
                if old is not None and old is not candidate:
                    old.draining = True
                self._entries[key] = candidate
            if old is not None and old is not candidate:
                await old.close(drain=False)
            return await candidate.list_tools()

        if (
            isinstance(current, McpServerPoolEntry)
            and current.fingerprint == fingerprint
            and current.tools_cache is not None
        ):
            return current.tools_cache

        if (
            isinstance(current, McpServerPoolEntry)
            and current.fingerprint == fingerprint
        ):
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
        if _is_http_client_server_params(server_params):
            key = server_name.strip()
            retry_enabled = _env_bool("SAGE_MCP_CALL_RETRY_ON_CONNECTION_ERROR", True)
            attempts = 2 if retry_enabled else 1
            for attempt in range(attempts):
                entry = await self._get_or_create_http_client_entry(
                    key,
                    server_params,  # pyright: ignore[reportArgumentType]
                    config,
                )
                try:
                    return await entry.call_tool(tool_name, arguments)
                except asyncio.CancelledError:
                    raise
                except McpConnectionStaleError as exc:
                    await self._discard_http_client_entry(key, entry)
                    if attempt + 1 >= attempts:
                        raise
                    logger.warning(
                        f"FastMCP client failed before tool call, reconnecting once: "
                        f"server={key}, tool={tool_name}, error={exc}"
                    )
                except Exception as exc:
                    if _is_connection_error(exc):
                        await self._discard_http_client_entry(key, entry)
                    # The request may already have reached the MCP server. Do not
                    # retry automatically because tools may have side effects.
                    raise
        entry = await self._get_or_create_entry(server_name, server_params, config)
        return await entry.call_tool(tool_name, arguments)

    async def _get_or_create_http_client_entry(
        self,
        key: str,
        server_params: HttpClientServerParams,
        config: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> McpHttpClientPoolEntry:
        fingerprint = config_fingerprint(key, server_params, config)
        async with self._lock:
            current = self._entries.get(key)
            if (
                not force
                and isinstance(current, McpHttpClientPoolEntry)
                and current.fingerprint == fingerprint
                and not current.draining
                and not current.closed
            ):
                return current
            candidate = McpHttpClientPoolEntry(
                key,
                server_params,
                fingerprint,
                config,
            )
            old = self._entries.get(key)
            if old is not None and old is not candidate:
                old.draining = True
            self._entries[key] = candidate

        if old is not None and old is not candidate:
            if isinstance(old, McpHttpClientPoolEntry):
                await old.retire("pool entry replaced")
            else:
                await old.close(drain=False)
        return candidate

    async def _discard_http_client_entry(
        self,
        key: str,
        entry: McpHttpClientPoolEntry,
    ) -> None:
        async with self._lock:
            current = self._entries.get(key)
            if current is entry:
                self._entries.pop(key, None)
        await entry.close(drain=False)

    async def _get_or_create_entry(
        self,
        server_name: str,
        server_params: ServerParams,
        config: Optional[Dict[str, Any]] = None,
    ) -> McpServerPoolEntry:
        key = server_name.strip()
        fingerprint = config_fingerprint(key, server_params, config)

        async with self._lock:
            entry = self._entries.get(key)
            if isinstance(entry, McpServerPoolEntry) and (
                config is None or entry.fingerprint == fingerprint
            ):
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
