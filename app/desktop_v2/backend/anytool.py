"""Desktop v2 owned ASGI host for the built-in AnyTool MCP endpoint."""

from __future__ import annotations

import anyio
from starlette.responses import PlainTextResponse

from mcp.server.lowlevel.server import Server
from mcp.server.streamable_http import StreamableHTTPServerTransport

from app.desktop_v2.backend.catalog import DesktopCatalogStore
from mcp_servers.anytool.anytool_server import build_anytool_server


class DesktopV2AnyToolApp:
    def __init__(
        self,
        catalog: DesktopCatalogStore,
        *,
        user_id: str = "default_user",
    ) -> None:
        self.catalog = catalog
        self.user_id = user_id

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await PlainTextResponse("Not found", status_code=404)(scope, receive, send)
            return
        server_name = str(scope.get("path") or "").strip("/").split("/")[-1]
        server_name = server_name or "AnyTool"
        record = next(
            (
                value
                for value in await self.catalog.list_mcp(self.user_id)
                if value.name == server_name
                or (server_name != "AnyTool" and value.name == "AnyTool")
            ),
            None,
        )
        if record is None or record.kind != "anytool" or record.disabled:
            await PlainTextResponse("AnyTool server not found", status_code=404)(
                scope, receive, send
            )
            return
        config = {
            **record.model_dump(mode="python"),
            "tools": list(record.tools),
            "user_id": record.user_id,
        }
        mcp_server: Server = build_anytool_server(record.name, config)
        transport = StreamableHTTPServerTransport(
            mcp_session_id=None,
            is_json_response_enabled=True,
        )

        async def run_server(*, task_status=anyio.TASK_STATUS_IGNORED):
            async with transport.connect() as streams:
                read_stream, write_stream = streams
                task_status.started()
                await mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp_server.create_initialization_options(),
                    stateless=True,
                )

        async with anyio.create_task_group() as group:
            await group.start(run_server)
            try:
                await transport.handle_request(scope, receive, send)
            finally:
                await transport.terminate()
                group.cancel_scope.cancel()
