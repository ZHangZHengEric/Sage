from __future__ import annotations

import anyio
from starlette.responses import PlainTextResponse

from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.server.lowlevel.server import Server

from common.models.mcp_server import MCPServerDao
from common.services.mcp_service import DEFAULT_ANYTOOL_SERVER_NAME

from .anytool_server import build_anytool_server


def resolve_anytool_server_name(path: str | None) -> str:
    raw_path = (path or "").strip("/")
    path_segments = [segment for segment in raw_path.split("/") if segment]
    return path_segments[-1] if path_segments else DEFAULT_ANYTOOL_SERVER_NAME


class AnyToolStreamableHTTPApp:
    """ASGI app that exposes AnyTool MCP servers over streamable HTTP."""

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            response = PlainTextResponse("Not found", status_code=404)
            await response(scope, receive, send)
            return

        server_name = resolve_anytool_server_name(scope.get("path"))

        dao = MCPServerDao()
        server = await dao.get_by_name(server_name)
        if not server and server_name != DEFAULT_ANYTOOL_SERVER_NAME:
            server = await dao.get_by_name(DEFAULT_ANYTOOL_SERVER_NAME)
            server_name = DEFAULT_ANYTOOL_SERVER_NAME if server else server_name
        if not server:
            response = PlainTextResponse("AnyTool server not found", status_code=404)
            await response(scope, receive, send)
            return

        server_config = dict(server.config or {})
        if server_config.get("kind") != "anytool":
            response = PlainTextResponse("Not an AnyTool server", status_code=404)
            await response(scope, receive, send)
            return
        if server_config.get("disabled", False):
            response = PlainTextResponse("AnyTool server disabled", status_code=404)
            await response(scope, receive, send)
            return

        mcp_server: Server = build_anytool_server(server_name, {**server_config, "user_id": server.user_id})
        transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=True,
        )

        async def run_stateless_server(*, task_status=anyio.TASK_STATUS_IGNORED):
            async with transport.connect() as streams:
                read_stream, write_stream = streams
                task_status.started()
                await mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp_server.create_initialization_options(),
                    stateless=True,
                )

        async with anyio.create_task_group() as tg:
            await tg.start(run_stateless_server)
            try:
                await transport.handle_request(scope, receive, send)
            finally:
                await transport.terminate()
                tg.cancel_scope.cancel()
