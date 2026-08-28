"""Native MCP tools projected into the v2 Tool provider contracts.

The bridge intentionally opens a short-lived MCP session for discovery or one
tool call. This is slower than a production pool, but it keeps lifecycle and
cancellation ownership correct across asyncio/AnyIO tasks. A host can replace
``session_factory`` with a durable pool without changing AgentLoopEngine.
"""

from __future__ import annotations

import asyncio
import base64
import re
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

from pydantic import Field, model_validator

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


class McpServerConfig(StrictModel):
    """Persistable MCP transport configuration without runtime objects."""

    name: str = Field(min_length=1, max_length=255)
    protocol: Literal["stdio", "sse", "streamable_http"]
    url: str | None = None
    api_key: str | None = None
    command: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30, gt=0)

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
        self._lock = asyncio.Lock()

    async def list_tools(self, *, run_id: str) -> tuple[ToolDefinition, ...]:
        del run_id
        discovered: dict[str, ToolDefinition] = {}
        routes: dict[str, tuple[McpServerConfig, str]] = {}
        for server in self.servers:
            try:
                async with self.session_factory(server) as session:
                    response = await asyncio.wait_for(
                        session.list_tools(), timeout=server.timeout_seconds
                    )
            except Exception as exc:
                raise self._provider_error("mcp.discovery_failed", server, exc) from exc
            for raw in _value(response, "tools", ()) or ():
                remote_name = str(_value(raw, "name", "") or "").strip()
                if not remote_name:
                    continue
                public_name = self._public_name(server.name, remote_name)
                if public_name in discovered:
                    raise self._error(
                        "mcp.tool_name_collision",
                        f"multiple MCP tools map to {public_name!r}",
                        ErrorCategory.CONFLICT,
                    )
                schema = _value(raw, "inputSchema", None) or _value(
                    raw, "input_schema", None
                )
                if not isinstance(schema, dict):
                    schema = {"type": "object", "properties": {}}
                discovered[public_name] = ToolDefinition(
                    name=public_name,
                    description=str(_value(raw, "description", "") or ""),
                    input_schema=schema,
                    # MCP does not declare a universal side-effect contract.
                    # The conservative default forces policy approval and avoids
                    # replay after an uncertain transport failure.
                    side_effect_level=SideEffectLevel.WRITE,
                    idempotency_strategy=IdempotencyStrategy.RECONCILE_ONLY,
                    resume_strategy=ResumeStrategy.MANUAL_RESOLUTION,
                    requires_approval=True,
                    required_scopes=("tool.external_side_effect",),
                )
                routes[public_name] = (server, remote_name)
        async with self._lock:
            self._definitions = discovered
            self._routes = routes
        return tuple(discovered[name] for name in sorted(discovered))

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
        async with self._lock:
            previous = self._results.get(call.idempotency_key)
            route = self._routes.get(call.tool_name)
        if previous is not None:
            return previous
        if route is None:
            raise self._error(
                "tool.not_found", f"MCP tool {call.tool_name!r} is not registered"
            )
        server, remote_name = route
        try:
            async with self.session_factory(server) as session:
                response = await asyncio.wait_for(
                    session.call_tool(remote_name, call.arguments),
                    timeout=server.timeout_seconds,
                )
        except Exception as exc:
            # The request may have reached the remote server. Do not retry here;
            # AgentLoop will persist an uncertain side-effect barrier.
            raise self._provider_error("mcp.call_failed", server, exc) from exc
        result = ToolExecutionResult(
            tool_call_id=call.tool_call_id,
            operation_id=call.operation_id,
            content=self._content(response),
            error=(
                RuntimeErrorInfo(
                    code="mcp.tool_error",
                    category=ErrorCategory.PROVIDER_PERMANENT,
                    message=self._error_text(response),
                    safe_to_resume=True,
                    metadata={"server": server.name, "tool": remote_name},
                )
                if bool(_value(response, "isError", False))
                else None
            ),
            metadata={"mcp_server": server.name, "mcp_tool": remote_name},
        )
        async with self._lock:
            self._results[call.idempotency_key] = result
        return result

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
        return ReconcileResult(
            operation_id=operation_id,
            state=(ReconcileState.SUCCEEDED if result else ReconcileState.UNKNOWN),
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
        code: str, server: McpServerConfig, exc: Exception
    ) -> SageV2Error:
        return McpToolPlugin._error(
            code,
            f"MCP server {server.name!r} failed: {exc}",
            ErrorCategory.PROVIDER_TRANSIENT,
            metadata={"server": server.name, "protocol": server.protocol},
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
                safe_to_resume=True,
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

    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else None
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
