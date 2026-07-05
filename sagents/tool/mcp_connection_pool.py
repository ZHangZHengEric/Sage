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


class McpWorkerClosedError(ConnectionError):
    """Raised when a pooled MCP worker is closed locally during replacement."""


class McpConnectionStaleError(ConnectionError):
    """Raised when a pooled MCP connection is stale before a request is sent."""


class McpToolCallInFlightError(Exception):
    """Wraps an error raised after a tool call has been sent."""

    def __init__(self, original: BaseException):
        super().__init__(str(original))
        self.original = original


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
        payload = model_dump()
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
            _env_float("SAGE_MCP_CALL_TIMEOUT_SECONDS", 300.0, minimum=0.0),
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


HttpWorkerServerParams = Union[SseServerParameters, StreamableHttpServerParameters]


def _is_http_worker_server_params(server_params: ServerParams) -> bool:
    return isinstance(
        server_params, (SseServerParameters, StreamableHttpServerParameters)
    )


class McpHttpWorkerPoolEntry:
    HEALTH_CHECK_IDLE_SECONDS = 30.0
    HEALTH_CHECK_TIMEOUT_SECONDS = 2.0

    def __init__(
        self,
        server_name: str,
        server_params: HttpWorkerServerParams,
        fingerprint: str,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.server_name = server_name
        self.server_params = server_params
        self.fingerprint = fingerprint
        self.config = dict(config or {})
        self.drain_timeout_seconds = _env_float(
            "SAGE_MCP_REFRESH_DRAIN_TIMEOUT_SECONDS", 30.0, minimum=0.0
        )
        self.call_timeout_seconds = _get_config_float(
            self.config,
            ["call_timeout_seconds"],
            _env_float("SAGE_MCP_CALL_TIMEOUT_SECONDS", 300.0, minimum=0.0),
            minimum=0.0,
        )
        self.health_check_idle_seconds = _get_config_float(
            self.config,
            ["http_worker_health_check_idle_seconds", "health_check_idle_seconds"],
            self.HEALTH_CHECK_IDLE_SECONDS,
            minimum=0.0,
        )
        self.health_check_timeout_seconds = _get_config_float(
            self.config,
            [
                "http_worker_health_check_timeout_seconds",
                "health_check_timeout_seconds",
            ],
            self.HEALTH_CHECK_TIMEOUT_SECONDS,
            minimum=0.0,
        )
        self.tools_cache: Optional[List[Tool]] = None
        self._tools_cache_observed_at: Optional[float] = None
        self.draining = False
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._current_future: Optional[asyncio.Future] = None
        self._last_activity_at = time.monotonic()
        self._worker_generation = 0
        self.server_generation: Optional[str] = None

    @property
    def closed(self) -> bool:
        return self._closed or (self._task is not None and self._task.done())

    @property
    def worker_generation(self) -> int:
        return self._worker_generation

    @property
    def queue_depth(self) -> int:
        return self._queue.qsize()

    @property
    def has_fresh_tools_cache(self) -> bool:
        if self.tools_cache is None or self._tools_cache_observed_at is None:
            return False
        if self.health_check_idle_seconds <= 0:
            return False
        if self.health_check_timeout_seconds <= 0:
            return False
        return (
            time.monotonic() - self._tools_cache_observed_at
            < self.health_check_idle_seconds
        )

    async def list_tools(self) -> List[Tool]:
        tools = await self._submit("list_tools", None)
        self.tools_cache = tools
        self._tools_cache_observed_at = time.monotonic()
        return tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        return await self._submit(
            "call_tool",
            {
                "tool_name": tool_name,
                "arguments": arguments,
            },
        )

    async def close(self, drain: bool = True) -> None:
        close_future = None
        async with self._lock:
            self.draining = True
            if self._task is None or self._task.done():
                self._closed = True
                await self._fail_pending_requests()
                return
            if not drain:
                self._closed = True
                self._fail_current_request()
                await self._fail_pending_requests()
                self._task.cancel()
                return
            close_future = asyncio.get_running_loop().create_future()
            await self._queue.put(
                ("close", None, close_future, self._worker_generation)
            )

        try:
            if self.drain_timeout_seconds > 0:
                await asyncio.wait_for(
                    close_future,
                    timeout=self.drain_timeout_seconds,
                )
            else:
                await close_future
        except asyncio.TimeoutError:
            logger.warning(
                f"MCP {_server_protocol(self.server_params)} close timed out; "
                f"close remains queued: "
                f"server={self.server_name}"
            )

    async def _submit(self, operation: str, payload: Any) -> Any:
        async with self._lock:
            if self.draining or self._closed:
                raise RuntimeError(
                    f"MCP {_server_protocol(self.server_params)} worker is draining: "
                    f"{self.server_name}"
                )
            if self._task is None or self._task.done():
                self._start_worker_locked()
            future = asyncio.get_running_loop().create_future()
            await self._queue.put((operation, payload, future, self._worker_generation))

        return await future

    def _start_worker_locked(self) -> None:
        self._closed = False
        self._worker_generation += 1
        generation = self._worker_generation
        self._task = asyncio.create_task(self._run(generation))
        logger.info(
            f"MCP {_server_protocol(self.server_params)} worker started: "
            f"server={self.server_name}, worker_generation={generation}"
        )

    async def _run(self, worker_generation: int) -> None:
        connection = McpPooledConnection(self.server_name, self.server_params)
        current_future: Optional[asyncio.Future] = None
        close_future: Optional[asyncio.Future] = None
        worker_error: Optional[BaseException] = None
        try:
            await connection.open()
            self._observe_server_generation(
                connection.server_generation,
                source=f"open worker_generation={worker_generation}",
            )
            self._last_activity_at = time.monotonic()
            while True:
                (
                    operation,
                    payload,
                    current_future,
                    request_generation,
                ) = await self._queue.get()
                self._current_future = current_future
                if operation == "close":
                    close_future = current_future
                    self._current_future = None
                    current_future = None
                    break

                try:
                    if request_generation != worker_generation:
                        raise self._worker_closed_error(
                            worker_generation=request_generation
                        )
                    await self._ensure_connection_healthy(
                        connection,
                        force=operation == "call_tool",
                    )
                    assert connection.session is not None
                    if operation == "list_tools":
                        response = await connection.session.list_tools()
                        result = response.tools
                        self.tools_cache = result
                    elif operation == "call_tool":
                        try:
                            call = connection.session.call_tool(
                                payload["tool_name"],
                                payload["arguments"],
                            )
                            if self.call_timeout_seconds > 0:
                                result = await asyncio.wait_for(
                                    call,
                                    timeout=self.call_timeout_seconds,
                                )
                            else:
                                result = await call
                        except asyncio.TimeoutError:
                            raise
                        except BaseException as exc:
                            raise McpToolCallInFlightError(exc) from exc
                    else:
                        raise RuntimeError(f"Unknown MCP worker operation: {operation}")
                except asyncio.TimeoutError:
                    target = (
                        payload["tool_name"]
                        if operation == "call_tool" and payload is not None
                        else operation
                    )
                    timeout_error = TimeoutError(
                        f"MCP tool call timed out after {self.call_timeout_seconds:g}s: "
                        f"server={self.server_name}, tool={target}"
                    )
                    if not current_future.done():  # pyright: ignore[reportOptionalMemberAccess]
                        current_future.set_exception(timeout_error)  # pyright: ignore[reportOptionalMemberAccess]
                    break
                except BaseException as exc:
                    if not current_future.done():  # pyright: ignore[reportOptionalMemberAccess]
                        current_future.set_exception(exc)  # pyright: ignore[reportOptionalMemberAccess]
                    break
                else:
                    if not current_future.done():  # pyright: ignore[reportOptionalMemberAccess]
                        current_future.set_result(result)  # pyright: ignore[reportOptionalMemberAccess]
                    self._last_activity_at = time.monotonic()
                finally:
                    if self._current_future is current_future:
                        self._current_future = None
                if self._closed:
                    break
        except BaseException as exc:
            worker_error = exc
            if current_future is not None and not current_future.done():
                current_future.set_exception(exc)
        finally:
            self._closed = True
            await connection.close()
            if close_future is not None and not close_future.done():
                close_future.set_result(None)
            await self._fail_pending_requests(worker_error)

    async def _ensure_connection_healthy(
        self,
        connection: McpPooledConnection,
        *,
        force: bool = False,
    ) -> None:
        if (
            self.health_check_timeout_seconds <= 0
            or self.health_check_idle_seconds < 0
            or (
                not force
                and time.monotonic() - self._last_activity_at
                < self.health_check_idle_seconds
            )
        ):
            return
        session = connection.session
        ping = getattr(session, "send_ping", None)
        if not callable(ping):
            return
        try:
            await asyncio.wait_for(
                self._ping_and_observe_generation(ping),
                timeout=self.health_check_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ConnectionError(
                f"MCP {_server_protocol(self.server_params)} health check timed out "
                f"after {self.health_check_timeout_seconds:g}s: "
                f"server={self.server_name}"
            ) from exc
        except ConnectionError:
            raise
        except BaseException as exc:
            raise ConnectionError(
                f"MCP {_server_protocol(self.server_params)} health check failed: "
                f"server={self.server_name}, error={exc}"
            ) from exc
        self._last_activity_at = time.monotonic()

    async def _ping_and_observe_generation(self, ping: Any) -> None:
        ping_result = await ping()
        observed_generation = _extract_server_generation(ping_result)
        changed = self._observe_server_generation(
            observed_generation,
            source="health_check",
        )
        if changed:
            raise McpConnectionStaleError(
                f"MCP {_server_protocol(self.server_params)} server generation "
                f"changed before request: server={self.server_name}, "
                f"server_generation={self.server_generation}"
            )

    def _observe_server_generation(
        self,
        observed_generation: Optional[str],
        source: str,
    ) -> bool:
        if not observed_generation:
            return False
        if self.server_generation is None:
            self.server_generation = observed_generation
            return False
        if observed_generation == self.server_generation:
            return False

        previous_generation = self.server_generation
        self.server_generation = observed_generation
        self.tools_cache = None
        self._tools_cache_observed_at = None
        logger.info(
            f"MCP {_server_protocol(self.server_params)} server generation changed: "
            f"server={self.server_name}, previous_generation={previous_generation}, "
            f"server_generation={observed_generation}, source={source}"
        )
        return True

    def _worker_closed_error(
        self, worker_generation: Optional[int] = None
    ) -> McpWorkerClosedError:
        generation = (
            self._worker_generation if worker_generation is None else worker_generation
        )
        return McpWorkerClosedError(
            f"MCP {_server_protocol(self.server_params)} worker closed: "
            f"{self.server_name}, worker_generation={generation}"
        )

    def _fail_current_request(self) -> None:
        if self._current_future is not None and not self._current_future.done():
            self._current_future.set_exception(self._worker_closed_error())

    async def _fail_pending_requests(
        self, error: Optional[BaseException] = None
    ) -> None:
        while not self._queue.empty():
            _operation, _payload, future, request_generation = await self._queue.get()
            if not future.done():
                future.set_exception(
                    error
                    or self._worker_closed_error(
                        worker_generation=request_generation,
                    )
                )


class McpConnectionPool:
    def __init__(self):
        self._entries: Dict[str, Union[McpServerPoolEntry, McpHttpWorkerPoolEntry]] = {}
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
        if isinstance(entry, McpHttpWorkerPoolEntry):
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
        if _is_http_worker_server_params(server_params):
            entry = await self._get_or_create_http_worker_entry(
                key,
                server_params,  # pyright: ignore[reportArgumentType]
                config,
                force=force,
            )
            retry_enabled = _env_bool(
                "SAGE_MCP_LIST_TOOLS_RETRY_ON_CONNECTION_ERROR", True
            )
            replacement_used = False
            while True:
                try:
                    return await entry.list_tools()
                except asyncio.CancelledError:
                    task = asyncio.current_task()
                    if task is not None and task.cancelling():
                        raise
                    if retry_enabled and not replacement_used:
                        replacement_used = True
                        await self._retire_http_worker_entry(key, entry)
                        logger.warning(
                            f"MCP {_server_protocol(server_params)} list_tools "
                            f"cancelled by worker, replacing once: server={key}, "
                            f"worker_generation={entry.worker_generation}, "
                            f"queue_depth={entry.queue_depth}"
                        )
                        entry = await self._get_or_create_http_worker_entry(
                            key,
                            server_params,  # pyright: ignore[reportArgumentType]
                            config,
                        )
                        continue
                    raise
                except Exception as exc:
                    if not _is_connection_error(exc):
                        raise
                    if retry_enabled and not replacement_used:
                        replacement_used = True
                        await self._retire_http_worker_entry(key, entry)
                        logger.warning(
                            f"MCP {_server_protocol(server_params)} list_tools "
                            f"failed, replacing once: server={key}, "
                            f"worker_generation={entry.worker_generation}, "
                            f"queue_depth={entry.queue_depth}, error={exc}"
                        )
                        entry = await self._get_or_create_http_worker_entry(
                            key,
                            server_params,  # pyright: ignore[reportArgumentType]
                            config,
                        )
                        continue
                    raise

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
        if _is_http_worker_server_params(server_params):
            key = server_name.strip()
            entry = await self._get_or_create_http_worker_entry(
                key,
                server_params,  # pyright: ignore[reportArgumentType]
                config,
            )
            retry_enabled = _env_bool("SAGE_MCP_CALL_RETRY_ON_CONNECTION_ERROR", True)
            replacement_used = False
            while True:
                try:
                    return await entry.call_tool(tool_name, arguments)
                except TimeoutError:
                    await self._discard_http_worker_entry(key, entry)
                    raise
                except McpToolCallInFlightError as exc:
                    await self._discard_http_worker_entry(key, entry)
                    raise exc.original from exc
                except asyncio.CancelledError:
                    task = asyncio.current_task()
                    if task is not None and task.cancelling():
                        raise
                    if retry_enabled and not replacement_used:
                        replacement_used = True
                        await self._retire_http_worker_entry(key, entry)
                        logger.warning(
                            f"MCP {_server_protocol(server_params)} call cancelled "
                            f"by worker, replacing once: server={key}, "
                            f"tool={tool_name}, "
                            f"worker_generation={entry.worker_generation}, "
                            f"queue_depth={entry.queue_depth}"
                        )
                        entry = await self._get_or_create_http_worker_entry(
                            key,
                            server_params,  # pyright: ignore[reportArgumentType]
                            config,
                        )
                        continue
                    raise
                except Exception as exc:
                    if not _is_connection_error(exc):
                        raise
                    if retry_enabled and not replacement_used:
                        replacement_used = True
                        await self._retire_http_worker_entry(key, entry)
                        logger.warning(
                            f"MCP {_server_protocol(server_params)} call "
                            f"failed, replacing once: server={key}, tool={tool_name}, "
                            f"worker_generation={entry.worker_generation}, "
                            f"queue_depth={entry.queue_depth}, error={exc}"
                        )
                        entry = await self._get_or_create_http_worker_entry(
                            key,
                            server_params,  # pyright: ignore[reportArgumentType]
                            config,
                        )
                        continue
                    raise
        entry = await self._get_or_create_entry(server_name, server_params, config)
        return await entry.call_tool(tool_name, arguments)

    async def _get_or_create_http_worker_entry(
        self,
        key: str,
        server_params: HttpWorkerServerParams,
        config: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> McpHttpWorkerPoolEntry:
        fingerprint = config_fingerprint(key, server_params, config)
        async with self._lock:
            current = self._entries.get(key)
            if (
                not force
                and isinstance(current, McpHttpWorkerPoolEntry)
                and current.fingerprint == fingerprint
                and not current.draining
                and not current.closed
            ):
                return current
            candidate = McpHttpWorkerPoolEntry(
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
            await old.close(drain=False)
        return candidate

    async def _discard_http_worker_entry(
        self,
        key: str,
        entry: McpHttpWorkerPoolEntry,
    ) -> None:
        async with self._lock:
            current = self._entries.get(key)
            if current is entry:
                self._entries.pop(key, None)
        await entry.close(drain=False)

    async def _retire_http_worker_entry(
        self,
        key: str,
        entry: McpHttpWorkerPoolEntry,
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
