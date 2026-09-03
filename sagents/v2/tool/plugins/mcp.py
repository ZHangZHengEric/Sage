"""Native MCP tools projected into the v2 Tool provider contracts.

The bridge intentionally opens a short-lived MCP session for discovery or one
tool call. This is slower than a production pool, but it keeps lifecycle and
cancellation ownership correct across asyncio/AnyIO tasks. A host can replace
``session_factory`` with a durable pool without changing AgentLoopEngine.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import Field, SecretStr, model_validator

from sagents.v2.contracts.common import StrictModel
from sagents.v2.contracts.errors import (
    ErrorCategory,
    RuntimeErrorInfo,
    SageV2Error,
)
from sagents.v2.contracts.items import ImageBlock, JsonBlock, TextBlock
from sagents.v2.contracts.principals import RequestContext
from sagents.v2.tool.contracts import (
    IdempotencyStrategy,
    ReconcileResult,
    ReconcileState,
    ResumeStrategy,
    SideEffectLevel,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool._idempotency import call_fingerprint


class McpServerConfig(StrictModel):
    """Persistable MCP transport configuration without runtime objects."""

    name: str = Field(min_length=1, max_length=255)
    protocol: Literal["stdio", "sse", "streamable_http"]
    url: str | None = None
    api_key: SecretStr | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30, gt=0)
    required: bool = True
    max_tools: int = Field(default=256, gt=0, le=10_000)
    max_pages: int = Field(default=64, gt=0, le=1_024)
    max_schema_bytes: int = Field(default=262_144, gt=0, le=16_777_216)
    max_result_bytes: int = Field(default=4_194_304, gt=0, le=67_108_864)

    @model_validator(mode="after")
    def validate_transport(self) -> "McpServerConfig":
        if self.protocol == "stdio":
            if not self.command:
                raise ValueError("stdio MCP requires command")
            if self.url is not None:
                raise ValueError("stdio MCP cannot define URL")
            return self
        if not self.url:
            raise ValueError(f"{self.protocol} MCP requires URL")
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MCP URL must be an absolute http(s) URL")
        if self.command is not None:
            raise ValueError(f"{self.protocol} MCP cannot define command")
        return self


class McpClientSession(Protocol):
    async def initialize(self) -> Any: ...
    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


McpSessionFactory = Callable[[McpServerConfig], Any]


class McpToolPlugin:
    """Tool plugin backed by explicitly configured external MCP servers.

    External MCP tools cannot use the local Python decorator because their
    definitions are owned by another process.  Their ``list_tools`` response
    is the authoritative declaration and is projected into the same Tool
    Catalog/Executor contracts used by decorator-backed local plugins.
    """

    plugin_id = "sage.tool.mcp"
    name = "MCP Tool provider"
    description = (
        "Bridges configured MCP servers into the Sage Tool catalog and executor."
    )

    def __init__(
        self,
        servers: tuple[McpServerConfig, ...],
        *,
        session_factory: McpSessionFactory | None = None,
    ) -> None:
        self.servers = tuple(sorted(servers, key=lambda value: value.name))
        self.session_factory = session_factory or _sdk_session
        self._routes: dict[str, tuple[McpServerConfig, str]] = {}
        self._definitions: dict[str, ToolDefinition] = {}
        self._results: dict[str, ToolExecutionResult] = {}
        self._failures: dict[str, RuntimeErrorInfo] = {}
        self._inflight: dict[str, asyncio.Future[ToolExecutionResult]] = {}
        self._operation_keys: dict[str, str] = {}
        self._call_fingerprints: dict[str, str] = {}
        self._call_run_ids: dict[str, str] = {}
        self._discovery_errors: dict[str, RuntimeErrorInfo] = {}
        self._lock = asyncio.Lock()

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        del run_id
        discovered: dict[str, ToolDefinition] = {}
        routes: dict[str, tuple[McpServerConfig, str]] = {}
        discovery_errors: dict[str, RuntimeErrorInfo] = {}
        for server in self.servers:
            try:
                async with self.session_factory(server) as session:
                    raw_tools = await self._list_server_tools(server, session)
            except SageV2Error as error:
                if server.required:
                    raise
                discovery_errors[server.name] = error.info
                continue
            except Exception as exc:
                # Discovery is read-only and happens before a tool call is
                # dispatched, so its failure cannot leave an uncertain side
                # effect behind and is safe to retry.
                error = self._provider_error(
                    "mcp.discovery_failed",
                    server,
                    exc,
                    category=ErrorCategory.PROVIDER_TRANSIENT,
                )
                if server.required:
                    raise error from exc
                discovery_errors[server.name] = error.info
                continue
            try:
                server_definitions, server_routes = self._project_tools(
                    server, raw_tools, existing_names=frozenset(discovered)
                )
            except SageV2Error as exc:
                if server.required:
                    raise
                discovery_errors[server.name] = exc.info
                continue
            discovered.update(server_definitions)
            routes.update(server_routes)
        async with self._lock:
            self._definitions = discovered
            self._routes = routes
            self._discovery_errors = discovery_errors
        return tuple(discovered[name] for name in sorted(discovered))

    async def _list_server_tools(
        self, server: McpServerConfig, session: Any
    ) -> tuple[Any, ...]:
        """Read every MCP catalog page with bounded, loop-safe pagination."""

        tools: list[Any] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _page in range(server.max_pages):
            request = (
                session.list_tools() if cursor is None else session.list_tools(cursor)
            )
            response = await asyncio.wait_for(
                request,
                timeout=server.timeout_seconds,
            )
            tools.extend(tuple(_value(response, "tools", ()) or ()))
            if len(tools) > server.max_tools:
                raise self._error(
                    "mcp.tool_catalog_too_large",
                    f"MCP server {server.name!r} returned more than the configured "
                    f"{server.max_tools}-tool limit",
                    ErrorCategory.PROVIDER_PERMANENT,
                    metadata={"server": server.name, "limit": server.max_tools},
                )
            next_cursor = _value(response, "nextCursor", None) or _value(
                response, "next_cursor", None
            )
            if next_cursor is None:
                return tuple(tools)
            cursor = str(next_cursor)
            if not cursor or cursor in seen_cursors:
                raise self._error(
                    "mcp.pagination_invalid",
                    f"MCP server {server.name!r} returned a repeated or empty cursor",
                    ErrorCategory.PROVIDER_PERMANENT,
                    metadata={"server": server.name},
                )
            seen_cursors.add(cursor)
        raise self._error(
            "mcp.pagination_limit_exceeded",
            f"MCP server {server.name!r} exceeded the configured "
            f"{server.max_pages}-page limit",
            ErrorCategory.PROVIDER_PERMANENT,
            metadata={"server": server.name, "limit": server.max_pages},
        )

    async def get_tool(self, name: str, *, run_id: str) -> ToolDefinition:
        if name not in self._definitions:
            await self.list_tools(run_id=run_id)
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise self._error(
                "tool.not_found", f"MCP tool {name!r} is not registered"
            ) from exc

    async def execute(
        self, call: ToolCall, context: RequestContext
    ) -> ToolExecutionResult:
        del context
        fingerprint = call_fingerprint(call)
        async with self._lock:
            bound = self._call_fingerprints.get(call.idempotency_key)
            if bound is not None and bound != fingerprint:
                raise self._error(
                    "tool.idempotency_conflict",
                    "idempotency key was already bound to a different Tool call",
                    ErrorCategory.CONFLICT,
                    metadata={"side_effect_state": "not_applied"},
                )
            previous = self._results.get(call.idempotency_key)
            failure = self._failures.get(call.idempotency_key)
            route = self._routes.get(call.tool_name)
            definition = self._definitions.get(call.tool_name)
            if previous is not None:
                return previous
            if failure is not None:
                raise SageV2Error(failure)
            if route is None or definition is None:
                raise self._error(
                    "tool.not_found", f"MCP tool {call.tool_name!r} is not registered"
                )
            try:
                Draft202012Validator(definition.input_schema).validate(call.arguments)
            except ValidationError as exc:
                raise self._error(
                    "tool.arguments_invalid",
                    exc.message,
                    ErrorCategory.VALIDATION,
                    metadata={"side_effect_state": "not_applied"},
                ) from exc
            future = self._inflight.get(call.idempotency_key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                self._inflight[call.idempotency_key] = future
                self._operation_keys[call.operation_id] = call.idempotency_key
                self._call_fingerprints[call.idempotency_key] = fingerprint
                self._call_run_ids[call.idempotency_key] = call.owner_run_id
                owner = True
            else:
                owner = False
        if not owner:
            return await asyncio.shield(future)
        server, remote_name = route
        try:
            async with self.session_factory(server) as session:
                response = await asyncio.wait_for(
                    session.call_tool(remote_name, call.arguments),
                    timeout=server.timeout_seconds,
                )
        except asyncio.CancelledError as exc:
            error = self._provider_error(
                "mcp.result_cancelled",
                server,
                RuntimeError("tool call was cancelled before a result was received"),
                category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                metadata={
                    "mcp_result_received": False,
                    "transport_failure": "cancelled",
                },
            )
            async with self._lock:
                self._failures[call.idempotency_key] = error.info
                if not future.done():
                    future.set_exception(exc)
                    future.exception()
            raise
        except TimeoutError as exc:
            error = self._provider_error(
                "mcp.result_timeout",
                server,
                RuntimeError(
                    f"Tool did not return within {server.timeout_seconds:g} seconds"
                ),
                category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                metadata={
                    "mcp_result_received": False,
                    "transport_failure": "timeout",
                },
            )
            async with self._lock:
                self._failures[call.idempotency_key] = error.info
                if not future.done():
                    future.set_exception(error)
                    future.exception()
            raise error from exc
        except Exception as exc:
            # The request may have reached the remote server and completed even
            # though its response was lost. Never replay a write from this state.
            error = self._provider_error(
                "mcp.result_not_received",
                server,
                exc,
                category=ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                metadata={
                    "mcp_result_received": False,
                    "transport_failure": "connection",
                },
            )
            async with self._lock:
                self._failures[call.idempotency_key] = error.info
                if not future.done():
                    future.set_exception(error)
                    future.exception()
            raise error from exc
        else:
            response_bytes = len(
                json.dumps(
                    _dump(response),
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
            result_truncated = response_bytes > server.max_result_bytes
            content = (
                (
                    TextBlock(
                        text=(
                            "MCP result omitted because it exceeded the configured "
                            f"{server.max_result_bytes}-byte limit."
                        )
                    ),
                )
                if result_truncated
                else self._content(response)
            )
            result = ToolExecutionResult(
                tool_call_id=call.tool_call_id,
                operation_id=call.operation_id,
                content=content,
                error=(
                    RuntimeErrorInfo(
                        code="mcp.tool_error",
                        category=ErrorCategory.PROVIDER_PERMANENT,
                        message=self._error_text(response)[:4096],
                        safe_to_resume=True,
                        metadata={
                            "server": server.name,
                            "tool": remote_name,
                            "mcp_result_received": True,
                            "tool_result_received": True,
                        },
                    )
                    if bool(_value(response, "isError", False))
                    else None
                ),
                metadata={
                    "mcp_server": server.name,
                    "mcp_tool": remote_name,
                    "mcp_result_received": True,
                    "tool_result_received": True,
                    "mcp_result_truncated": result_truncated,
                    "mcp_result_size_bytes": response_bytes,
                },
            )
            async with self._lock:
                self._results[call.idempotency_key] = result
                if not future.done():
                    future.set_result(result)
            return result
        finally:
            async with self._lock:
                self._inflight.pop(call.idempotency_key, None)
                self._operation_keys.pop(call.operation_id, None)

    async def release_run(self, run_id: str) -> None:
        """Release terminal Run state without disturbing in-flight calls."""

        async with self._lock:
            keys = {
                key
                for key, owner_run_id in self._call_run_ids.items()
                if owner_run_id == run_id and key not in self._inflight
            }
            for key in keys:
                self._results.pop(key, None)
                self._failures.pop(key, None)
                self._call_fingerprints.pop(key, None)
                self._call_run_ids.pop(key, None)

    @classmethod
    def _project_tools(
        cls,
        server: McpServerConfig,
        raw_tools: tuple[Any, ...],
        *,
        existing_names: frozenset[str],
    ) -> tuple[
        dict[str, ToolDefinition],
        dict[str, tuple[McpServerConfig, str]],
    ]:
        definitions: dict[str, ToolDefinition] = {}
        routes: dict[str, tuple[McpServerConfig, str]] = {}
        for raw in raw_tools:
            remote_name = str(_value(raw, "name", "") or "").strip()
            if not remote_name:
                continue
            public_name = cls._public_name(server.name, remote_name)
            if public_name in existing_names or public_name in definitions:
                raise cls._error(
                    "mcp.tool_name_collision",
                    f"multiple MCP tools map to {public_name!r}",
                    ErrorCategory.CONFLICT,
                )
            schema = _value(raw, "inputSchema", None) or _value(
                raw, "input_schema", None
            )
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            try:
                schema_bytes = len(
                    json.dumps(
                        schema,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                )
                Draft202012Validator.check_schema(schema)
            except (SchemaError, TypeError, ValueError) as exc:
                raise cls._error(
                    "mcp.tool_schema_invalid",
                    f"MCP tool {public_name!r} returned an invalid input schema: {exc}",
                    ErrorCategory.PROVIDER_PERMANENT,
                    metadata={"server": server.name, "tool": remote_name},
                ) from exc
            if schema_bytes > server.max_schema_bytes:
                raise cls._error(
                    "mcp.tool_schema_too_large",
                    f"MCP tool {public_name!r} schema exceeds the configured "
                    f"{server.max_schema_bytes}-byte limit",
                    ErrorCategory.PROVIDER_PERMANENT,
                    metadata={
                        "server": server.name,
                        "tool": remote_name,
                        "size_bytes": schema_bytes,
                        "limit_bytes": server.max_schema_bytes,
                    },
                )
            definitions[public_name] = ToolDefinition(
                name=public_name,
                description=str(_value(raw, "description", "") or "")[:4096],
                input_schema=schema,
                # MCP annotations are untrusted hints and there is no
                # protocol-wide exactly-once guarantee. A lost response may
                # therefore hide a completed remote write.
                side_effect_level=SideEffectLevel.WRITE,
                idempotency_strategy=IdempotencyStrategy.RECONCILE_ONLY,
                resume_strategy=ResumeStrategy.MANUAL_RESOLUTION,
                requires_approval=True,
                required_scopes=("tool.external_side_effect",),
            )
            routes[public_name] = (server, remote_name)
        return definitions, routes

    async def reconcile(
        self, operation_id: str, context: RequestContext
    ) -> ReconcileResult:
        del context
        async with self._lock:
            result = next(
                (
                    value
                    for value in self._results.values()
                    if value.operation_id == operation_id
                ),
                None,
            )
            key = self._operation_keys.get(operation_id)
            pending = key in self._inflight if key is not None else False
        return ReconcileResult(
            operation_id=operation_id,
            state=(
                ReconcileState.FAILED
                if result is not None and result.error is not None
                else ReconcileState.SUCCEEDED
                if result is not None
                else ReconcileState.PENDING
                if pending
                else ReconcileState.UNKNOWN
            ),
            result=result,
        )

    @classmethod
    def _public_name(cls, server: str, tool: str) -> str:
        # ToolName deliberately forbids dots. Prefixing the configured server
        # keeps routes deterministic while remaining provider-compatible.
        return f"mcp_{cls._identifier(server)}_{cls._identifier(tool)}"[:192]

    @staticmethod
    def _identifier(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")
        return normalized or "unnamed"

    @staticmethod
    def _content(response: Any) -> tuple:
        blocks = []
        for value in _value(response, "content", ()) or ():
            kind = str(_value(value, "type", "") or "")
            if kind == "text":
                blocks.append(TextBlock(text=str(_value(value, "text", "") or "")))
            elif kind == "image":
                mime_type = str(_value(value, "mimeType", "image/png") or "image/png")
                data = str(_value(value, "data", "") or "")
                blocks.append(
                    ImageBlock(
                        uri=f"data:{mime_type};base64,{data}", mime_type=mime_type
                    )
                )
            else:
                blocks.append(JsonBlock(value=_dump(value)))
        structured = _value(response, "structuredContent", None)
        if structured is not None:
            blocks.append(JsonBlock(value=structured))
        return tuple(blocks) or (JsonBlock(value=_dump(response)),)

    @staticmethod
    def _error_text(response: Any) -> str:
        texts = [
            str(_value(value, "text", "") or "")
            for value in (_value(response, "content", ()) or ())
            if str(_value(value, "type", "") or "") == "text"
        ]
        return "\n".join(value for value in texts if value) or "MCP tool failed"

    @staticmethod
    def _provider_error(
        code: str,
        server: McpServerConfig,
        exc: Exception,
        *,
        category: ErrorCategory = ErrorCategory.UNCERTAIN_SIDE_EFFECT,
        metadata: dict[str, Any] | None = None,
    ) -> SageV2Error:
        return McpToolPlugin._error(
            code,
            f"MCP server {server.name!r} failed: {exc}",
            category,
            metadata={
                "server": server.name,
                "protocol": server.protocol,
                **dict(metadata or {}),
            },
        )

    @staticmethod
    def _error(
        code: str,
        message: str,
        category: ErrorCategory = ErrorCategory.VALIDATION,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> SageV2Error:
        return SageV2Error(
            RuntimeErrorInfo(
                code=code,
                category=category,
                message=message,
                retryable=category == ErrorCategory.PROVIDER_TRANSIENT,
                safe_to_resume=category != ErrorCategory.UNCERTAIN_SIDE_EFFECT,
                metadata=dict(metadata or {}),
            )
        )


@asynccontextmanager
async def _sdk_session(config: McpServerConfig) -> AsyncIterator[McpClientSession]:
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


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _dump(value: Any) -> Any:
    if isinstance(value, dict):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return dump(mode="json")
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    return {"type": type(value).__name__, "value": str(value)}
