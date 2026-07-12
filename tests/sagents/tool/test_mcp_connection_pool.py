import asyncio
import os
import socket
import sys
import unittest
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import anyio
from mcp import ErrorData, StdioServerParameters
from mcp.shared.exceptions import McpError

from sagents.tool.mcp_connection_pool import (
    McpConnectionPool,
    McpPooledConnection,
    _create_mcp_http_client,
)
from sagents.tool.tool_schema import SseServerParameters, StreamableHttpServerParameters


class _FakeResult:
    isError = False
    content = []

    def model_dump(self):
        return {"content": []}


class _FakeListToolsResponse:
    def __init__(self, tools=None):
        self.tools = [] if tools is None else tools


class _BaseFakeFastMCPClient:
    instances = []

    def __init__(self, transport, **kwargs):
        self.transport = transport
        self.kwargs = kwargs
        self.closed = False
        self.entered = False
        type(self).instances.append(self)

    async def __aenter__(self):
        self.entered = True
        return self

    async def close(self):
        self.closed = True

    def is_connected(self):
        return self.entered and not self.closed

    async def list_tools(self):
        return []

    async def call_tool_mcp(self, name, arguments, timeout=None):
        return _FakeResult()


def _stdio_params():
    return StdioServerParameters(command="mcp-server", args=[])


class TestMcpStdioConnectionPool(unittest.IsolatedAsyncioTestCase):
    async def test_101_concurrent_calls_expand_to_second_connection(self):
        pool = McpConnectionPool()
        release = asyncio.Event()
        all_started = asyncio.Event()
        started = 0
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                nonlocal started
                started += 1
                if started == 101:
                    all_started.set()
                await release.wait()
                return _FakeResult()

        async def fake_open(connection):
            nonlocal open_count
            open_count += 1
            connection.session = FakeSession()
            return connection

        with patch.object(McpPooledConnection, "open", fake_open):
            tasks = [
                asyncio.create_task(
                    pool.call_tool("server", _stdio_params(), "echo", {"i": i})
                )
                for i in range(101)
            ]
            await asyncio.wait_for(all_started.wait(), timeout=2)
            self.assertEqual(open_count, 2)
            release.set()
            await asyncio.gather(*tasks)

        await pool.close_all(drain=False)

    async def test_low_concurrency_reuses_initialized_connection(self):
        pool = McpConnectionPool()
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                return _FakeResult()

        async def fake_open(connection):
            nonlocal open_count
            open_count += 1
            connection.session = FakeSession()
            return connection

        with patch.object(McpPooledConnection, "open", fake_open):
            await pool.call_tool("server", _stdio_params(), "echo", {"i": 1})
            await pool.call_tool("server", _stdio_params(), "echo", {"i": 2})

        self.assertEqual(open_count, 1)
        await pool.close_all(drain=False)

    async def test_server_config_overrides_concurrency(self):
        pool = McpConnectionPool()
        release = asyncio.Event()
        all_started = asyncio.Event()
        started = 0
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                nonlocal started
                started += 1
                if started == 3:
                    all_started.set()
                await release.wait()
                return _FakeResult()

        async def fake_open(connection):
            nonlocal open_count
            open_count += 1
            connection.session = FakeSession()
            return connection

        with patch.object(McpPooledConnection, "open", fake_open):
            tasks = [
                asyncio.create_task(
                    pool.call_tool(
                        "server",
                        _stdio_params(),
                        "echo",
                        {"i": i},
                        config={"per_connection_concurrency": 2},
                    )
                )
                for i in range(3)
            ]
            await asyncio.wait_for(all_started.wait(), timeout=2)
            self.assertEqual(open_count, 2)
            release.set()
            await asyncio.gather(*tasks)

        await pool.close_all(drain=False)

    async def test_call_reuses_entry_created_with_runtime_config(self):
        pool = McpConnectionPool()
        open_count = 0

        class FakeSession:
            async def list_tools(self):
                return _FakeListToolsResponse()

            async def call_tool(self, name, arguments):
                return _FakeResult()

        async def fake_open(connection):
            nonlocal open_count
            open_count += 1
            connection.session = FakeSession()
            return connection

        with patch.object(McpPooledConnection, "open", fake_open):
            await pool.list_tools(
                "server",
                _stdio_params(),
                config={"per_connection_concurrency": 2},
            )
            await pool.call_tool("server", _stdio_params(), "echo", {})

        self.assertEqual(open_count, 1)
        await pool.close_all(drain=False)

    async def test_list_tools_reconnects_after_closed_connection(self):
        pool = McpConnectionPool()
        open_count = 0

        class FakeSession:
            def __init__(self, fail):
                self.fail = fail

            async def list_tools(self):
                if self.fail:
                    raise BrokenPipeError("closed stream")
                return _FakeListToolsResponse()

        async def fake_open(connection):
            nonlocal open_count
            open_count += 1
            connection.session = FakeSession(fail=open_count == 1)
            return connection

        with patch.object(McpPooledConnection, "open", fake_open):
            await pool.list_tools("server", _stdio_params())

        self.assertEqual(open_count, 2)
        await pool.close_all(drain=False)

    async def test_call_timeout_discards_connection(self):
        pool = McpConnectionPool()

        class FakeSession:
            async def call_tool(self, name, arguments):
                await asyncio.sleep(1)

        async def fake_open(connection):
            connection.session = FakeSession()
            return connection

        with patch.object(McpPooledConnection, "open", fake_open):
            with self.assertRaises(TimeoutError):
                await pool.call_tool(
                    "server",
                    _stdio_params(),
                    "slow",
                    {},
                    config={"call_timeout_seconds": 0.01},
                )

        self.assertEqual(len(pool._entries["server"].connections), 0)  # pyright: ignore[reportAttributeAccessIssue]
        await pool.close_all(drain=False)

    async def test_call_retries_closed_resource_error(self):
        pool = McpConnectionPool()
        open_count = 0

        class FakeSession:
            def __init__(self, fail):
                self.fail = fail

            async def call_tool(self, name, arguments):
                if self.fail:
                    raise anyio.ClosedResourceError()
                return _FakeResult()

        async def fake_open(connection):
            nonlocal open_count
            open_count += 1
            connection.session = FakeSession(fail=open_count == 1)
            return connection

        with patch.object(McpPooledConnection, "open", fake_open):
            result = await pool.call_tool("server", _stdio_params(), "echo", {})

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(open_count, 2)
        await pool.close_all(drain=False)


class TestMcpHttpClientPool(unittest.IsolatedAsyncioTestCase):
    async def test_http_transport_has_no_active_connection_limit(self):
        client = _create_mcp_http_client()
        try:
            transport = cast(Any, client._transport)
            pool = transport._pool
            self.assertEqual(pool._max_connections, sys.maxsize)
            self.assertEqual(pool._max_keepalive_connections, 20)
        finally:
            await client.aclose()

    async def test_one_session_runs_unlimited_concurrent_calls(self):
        pool = McpConnectionPool()
        release = asyncio.Event()
        all_started = asyncio.Event()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []
            started = 0

            async def call_tool_mcp(self, name, arguments, timeout=None):
                type(self).started += 1
                if type(self).started == 200:
                    all_started.set()
                await release.wait()
                return _FakeResult()

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            tasks = [
                asyncio.create_task(pool.call_tool("server", params, "echo", {"i": i}))
                for i in range(200)
            ]
            await asyncio.wait_for(all_started.wait(), timeout=2)
            self.assertEqual(len(FakeClient.instances), 1)
            release.set()
            await asyncio.gather(*tasks)

        await pool.close_all(drain=False)

    async def test_long_call_does_not_block_short_call(self):
        pool = McpConnectionPool()
        long_started = asyncio.Event()
        release_long = asyncio.Event()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []

            async def call_tool_mcp(self, name, arguments, timeout=None):
                if arguments.get("long"):
                    long_started.set()
                    await release_long.wait()
                return _FakeResult()

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            long_call = asyncio.create_task(
                pool.call_tool("server", params, "work", {"long": True})
            )
            await asyncio.wait_for(long_started.wait(), timeout=1)
            short_result = await asyncio.wait_for(
                pool.call_tool("server", params, "work", {"long": False}),
                timeout=0.2,
            )
            self.assertIsInstance(short_result, _FakeResult)
            release_long.set()
            await long_call

        await pool.close_all(drain=False)

    async def test_connect_failure_retries_before_request_is_sent(self):
        pool = McpConnectionPool()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []
            calls = 0

            async def __aenter__(self):
                if len(type(self).instances) == 1:
                    raise ConnectionError("network unavailable")
                return await super().__aenter__()

            async def call_tool_mcp(self, name, arguments, timeout=None):
                type(self).calls += 1
                return _FakeResult()

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            result = await pool.call_tool("server", params, "echo", {})

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(len(FakeClient.instances), 2)
        self.assertEqual(FakeClient.calls, 1)
        await pool.close_all(drain=False)

    async def test_in_flight_connection_failure_is_not_retried(self):
        pool = McpConnectionPool()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []
            calls = 0

            async def call_tool_mcp(self, name, arguments, timeout=None):
                type(self).calls += 1
                if len(type(self).instances) == 1:
                    self.closed = True
                    raise ConnectionError("connection reset")
                return _FakeResult()

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            with self.assertRaises(ConnectionError):
                await pool.call_tool("server", params, "side_effect", {})
            self.assertEqual(FakeClient.calls, 1)

            result = await pool.call_tool("server", params, "side_effect", {})

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(len(FakeClient.instances), 2)
        self.assertEqual(FakeClient.calls, 2)
        await pool.close_all(drain=False)

    async def test_server_restart_session_terminated_reconnects_and_retries_safely(
        self,
    ):
        pool = McpConnectionPool()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []
            calls = 0

            async def call_tool_mcp(self, name, arguments, timeout=None):
                type(self).calls += 1
                if len(type(self).instances) == 1:
                    raise McpError(ErrorData(code=32600, message="Session terminated"))
                return _FakeResult()

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            result = await pool.call_tool("server", params, "echo", {})

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(len(FakeClient.instances), 2)
        self.assertEqual(FakeClient.calls, 2)
        await pool.close_all(drain=False)

    async def test_closed_local_sse_stream_reconnects_before_sending(self):
        pool = McpConnectionPool()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []
            calls = 0

            async def call_tool_mcp(self, name, arguments, timeout=None):
                type(self).calls += 1
                if len(type(self).instances) == 1:
                    raise anyio.ClosedResourceError()
                return _FakeResult()

        params = SseServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            result = await pool.call_tool("server", params, "echo", {})

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(len(FakeClient.instances), 2)
        self.assertEqual(FakeClient.calls, 2)
        await pool.close_all(drain=False)

    async def test_request_timeout_does_not_cancel_other_calls(self):
        pool = McpConnectionPool()
        long_started = asyncio.Event()
        release_long = asyncio.Event()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []

            async def call_tool_mcp(self, name, arguments, timeout=None):
                if arguments.get("long"):
                    long_started.set()
                    await release_long.wait()
                    return _FakeResult()
                raise asyncio.TimeoutError("request timed out")

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            long_call = asyncio.create_task(
                pool.call_tool("server", params, "work", {"long": True})
            )
            await asyncio.wait_for(long_started.wait(), timeout=1)

            with self.assertRaises(asyncio.TimeoutError):
                await pool.call_tool("server", params, "work", {"long": False})
            self.assertFalse(FakeClient.instances[0].closed)

            release_long.set()
            result = await asyncio.wait_for(long_call, timeout=1)

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(len(FakeClient.instances), 1)
        await pool.close_all(drain=False)

    async def test_list_tools_timeout_does_not_cancel_active_tool_call(self):
        pool = McpConnectionPool()
        long_started = asyncio.Event()
        release_long = asyncio.Event()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []

            async def list_tools(self):
                raise asyncio.TimeoutError("list_tools timed out")

            async def call_tool_mcp(self, name, arguments, timeout=None):
                long_started.set()
                await release_long.wait()
                return _FakeResult()

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            long_call = asyncio.create_task(
                pool.call_tool("server", params, "work", {})
            )
            await asyncio.wait_for(long_started.wait(), timeout=1)

            with self.assertRaises(asyncio.TimeoutError):
                await pool.list_tools("server", params)
            self.assertFalse(FakeClient.instances[0].closed)

            release_long.set()
            result = await asyncio.wait_for(long_call, timeout=1)

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(len(FakeClient.instances), 1)
        await pool.close_all(drain=False)

    async def test_runtime_call_reuses_configured_registration_session(self):
        pool = McpConnectionPool()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []
            observed_timeout = None

            async def list_tools(self):
                return ["echo"]

            async def call_tool_mcp(self, name, arguments, timeout=None):
                type(self).observed_timeout = timeout
                return _FakeResult()

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            await pool.list_tools(
                "server",
                params,
                config={"call_timeout_seconds": 1200},
            )
            result = await pool.call_tool("server", params, "echo", {})

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(len(FakeClient.instances), 1)
        self.assertEqual(FakeClient.observed_timeout, 1200)
        await pool.close_all(drain=False)

    async def test_broken_session_fails_all_current_calls_and_next_call_recovers(self):
        pool = McpConnectionPool()
        all_started = asyncio.Event()
        fail = asyncio.Event()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []
            started = 0

            async def call_tool_mcp(self, name, arguments, timeout=None):
                if len(type(self).instances) == 1:
                    type(self).started += 1
                    if type(self).started == 20:
                        all_started.set()
                    await fail.wait()
                    self.closed = True
                    raise ConnectionError("server session was closed")
                return _FakeResult()

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            calls = [
                asyncio.create_task(pool.call_tool("server", params, "echo", {}))
                for _ in range(20)
            ]
            await asyncio.wait_for(all_started.wait(), timeout=1)
            fail.set()
            results = await asyncio.wait_for(
                asyncio.gather(*calls, return_exceptions=True), timeout=1
            )
            self.assertTrue(all(isinstance(item, ConnectionError) for item in results))

            recovered = await pool.call_tool("server", params, "echo", {})

        self.assertIsInstance(recovered, _FakeResult)
        self.assertEqual(len(FakeClient.instances), 2)
        await pool.close_all(drain=False)

    async def test_force_refresh_does_not_cancel_active_long_call(self):
        pool = McpConnectionPool()
        long_started = asyncio.Event()
        release_long = asyncio.Event()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []

            async def call_tool_mcp(self, name, arguments, timeout=None):
                long_started.set()
                await release_long.wait()
                return _FakeResult()

            async def list_tools(self):
                return ["echo"]

        params = StreamableHttpServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            long_call = asyncio.create_task(
                pool.call_tool("server", params, "work", {})
            )
            await asyncio.wait_for(long_started.wait(), timeout=1)
            old_client = FakeClient.instances[0]

            tools = await pool.list_tools("server", params, force=True)
            self.assertEqual(tools, ["echo"])
            self.assertEqual(len(FakeClient.instances), 2)
            self.assertFalse(old_client.closed)

            release_long.set()
            result = await asyncio.wait_for(long_call, timeout=1)
            self.assertIsInstance(result, _FakeResult)
            self.assertTrue(old_client.closed)

        await pool.close_all(drain=False)

    async def test_default_timeout_supports_twenty_minute_task(self):
        pool = McpConnectionPool()

        class FakeClient(_BaseFakeFastMCPClient):
            instances = []
            observed_timeout = None

            async def call_tool_mcp(self, name, arguments, timeout=None):
                type(self).observed_timeout = timeout
                return _FakeResult()

        params = SseServerParameters(url="http://mcp.example")
        with patch("sagents.tool.mcp_connection_pool.FastMCPClient", FakeClient):
            await pool.call_tool("server", params, "slow", {})

        self.assertEqual(FakeClient.observed_timeout, 1800.0)
        await pool.close_all(drain=False)


@unittest.skipUnless(
    os.environ.get("SAGE_RUN_MCP_RESTART_INTEGRATION_TEST") == "1",
    "set SAGE_RUN_MCP_RESTART_INTEGRATION_TEST=1 to run process restart test",
)
class TestMcpHttpServerRestartIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        self.port = sock.getsockname()[1]
        sock.close()
        self.server_script = Path(__file__).with_name("restartable_mcp_server.py")
        self.transport = "http"
        self.pool = McpConnectionPool()
        self.params = StreamableHttpServerParameters(
            url=f"http://127.0.0.1:{self.port}/mcp"
        )
        self.process = await self._start_server()

    async def asyncTearDown(self):
        await self.pool.close_all(drain=False)
        await self._stop_server()

    async def _start_server(self):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.server_script),
            str(self.port),
            self.transport,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        for _ in range(100):
            try:
                _, writer = await asyncio.open_connection("127.0.0.1", self.port)
                writer.close()
                await writer.wait_closed()
                return process
            except OSError:
                await asyncio.sleep(0.05)
        process.terminate()
        await process.wait()
        self.fail("restartable MCP test server did not start")

    async def _stop_server(self):
        if self.process.returncode is not None:
            return
        self.process.terminate()
        await asyncio.wait_for(self.process.wait(), timeout=5)

    async def test_call_recovers_after_real_server_process_restart(self):
        first = await self.pool.call_tool(
            "restartable",
            self.params,
            "echo",
            {"value": "before"},
        )
        self.assertEqual(first.content[0].text, "before")

        await self._stop_server()
        self.process = await self._start_server()

        second = await self.pool.call_tool(
            "restartable",
            self.params,
            "echo",
            {"value": "after"},
        )
        self.assertEqual(second.content[0].text, "after")

    async def test_sse_call_recovers_after_real_server_process_restart(self):
        await self._stop_server()
        self.transport = "sse"
        self.params = SseServerParameters(url=f"http://127.0.0.1:{self.port}/sse")
        self.process = await self._start_server()

        first = await self.pool.call_tool(
            "restartable-sse",
            self.params,
            "echo",
            {"value": "before"},
        )
        self.assertEqual(first.content[0].text, "before")

        await self._stop_server()
        self.process = await self._start_server()

        second = await self.pool.call_tool(
            "restartable-sse",
            self.params,
            "echo",
            {"value": "after"},
        )
        self.assertEqual(second.content[0].text, "after")


if __name__ == "__main__":
    unittest.main()
