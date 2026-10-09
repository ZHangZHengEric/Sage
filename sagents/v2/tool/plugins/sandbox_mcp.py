"""Official MCP sessions whose stdio child runs behind a sandbox boundary."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from sagents.v2.contracts.common import new_id
from sagents.v2.runtime.execution.sandbox.contracts import (
    OperationIntent,
    ProcessRequest,
)
from sagents.v2.tool._mcp_session import sdk_session


class SandboxMcpSessionFactory:
    def __init__(self, sandbox, issuer, *, workspace_root="/workspace"):
        self.sandbox = sandbox
        self.issuer = issuer
        self.workspace_root = workspace_root

    @asynccontextmanager
    async def __call__(self, config):
        if config.protocol != "stdio":
            async with sdk_session(config) as session:
                yield session
            return
        import anyio
        from mcp import ClientSession, types
        from mcp.shared.message import SessionMessage

        opener = getattr(self.sandbox.process, "open_process", None)
        if not callable(opener):
            raise PermissionError("sandbox does not support stdio processes")
        if not config.command:
            raise ValueError("stdio MCP requires command")
        request = ProcessRequest(
            argv=(config.command, *config.args),
            cwd=self.workspace_root,
            env=dict(config.env),
            timeout_seconds=config.timeout_seconds,
        )
        intent = OperationIntent(
            operation="process.run",
            run_id=self.sandbox.ref.owner_run_id,
            tool_call_id=new_id("mcp_session"),
            sandbox_id=self.sandbox.ref.sandbox_id,
            path=request.cwd,
            executable=request.argv[0],
            argv=request.argv,
            metadata={"process_request_digest": request.digest()},
        )
        grant = self.issuer.issue(
            ref=self.sandbox.ref,
            intent=intent,
            allowed_operations=frozenset({"process.run"}),
        )
        async with opener(request, intent=intent, grant=grant) as process:
            reader_send, reader = anyio.create_memory_object_stream(0)
            writer, writer_receive = anyio.create_memory_object_stream(0)

            async def read_stdout():
                pending = b""
                async with reader_send:
                    while chunk := await process.read_stdout():
                        pending += chunk
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            try:
                                message = SessionMessage(
                                    types.JSONRPCMessage.model_validate_json(line)
                                )
                            except Exception as exc:
                                message = exc
                            await reader_send.send(message)
                    if pending.strip():
                        await reader_send.send(
                            ValueError("MCP stdout ended with an incomplete message")
                        )

            async def write_stdin():
                async with writer_receive:
                    async for message in writer_receive:
                        await process.write_stdin(
                            (
                                message.message.model_dump_json(
                                    by_alias=True, exclude_none=True
                                )
                                + "\n"
                            ).encode("utf-8")
                        )

            async def drain_stderr():
                while await process.read_stderr():
                    pass

            async with reader, writer, anyio.create_task_group() as group:
                group.start_soon(read_stdout)
                group.start_soon(write_stdin)
                group.start_soon(drain_stderr)
                try:
                    async with ClientSession(reader, writer) as session:
                        await asyncio.wait_for(
                            session.initialize(), config.timeout_seconds
                        )
                        yield session
                finally:
                    await process.close_stdin()
                    group.cancel_scope.cancel()
