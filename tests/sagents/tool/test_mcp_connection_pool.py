import asyncio
import unittest
from unittest.mock import patch

import anyio
import httpx
from mcp import StdioServerParameters

from sagents.tool.mcp_connection_pool import (
    McpConnectionPool,
    McpPooledConnection,
    McpWorkerClosedError,
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


class _FakeGeneration:
    def __init__(self, generation):
        self.generation = generation

    def model_dump(self):
        return {"metadata": {"server_generation": self.generation}}


def _stdio_params():
    return StdioServerParameters(command="mcp-server", args=[])


class TestMcpConnectionPool(unittest.IsolatedAsyncioTestCase):
    async def test_101_concurrent_calls_expand_to_second_connection(self):
        pool = McpConnectionPool()
        server_params = _stdio_params()
        release = asyncio.Event()
        condition = asyncio.Condition()
        started = 0
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                nonlocal started
                async with condition:
                    started += 1
                    condition.notify_all()
                await release.wait()
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        async def wait_until_started(expected):
            async with condition:
                await asyncio.wait_for(
                    condition.wait_for(lambda: started >= expected),
                    timeout=2,
                )

        with patch.object(McpPooledConnection, "open", fake_open):
            tasks = [
                asyncio.create_task(
                    pool.call_tool("server", server_params, "echo", {"i": i})
                )
                for i in range(101)
            ]
            await wait_until_started(101)
            self.assertEqual(open_count, 2)
            self.assertEqual(len(pool._entries["server"].connections), 2)  # pyright: ignore[reportAttributeAccessIssue]
            release.set()
            await asyncio.gather(*tasks)

        await pool.close_all(drain=False)

    async def test_low_concurrency_reuses_initialized_connection(self):
        pool = McpConnectionPool()
        server_params = _stdio_params()
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            await pool.call_tool("server", server_params, "echo", {"i": 1})
            await pool.call_tool("server", server_params, "echo", {"i": 2})

        self.assertEqual(open_count, 1)
        self.assertEqual(len(pool._entries["server"].connections), 1)  # pyright: ignore[reportAttributeAccessIssue]
        await pool.close_all(drain=False)

    async def _assert_http_transport_reuses_worker_connection(self, server_params):
        pool = McpConnectionPool()
        open_count = 0
        close_count = 0
        open_task = None
        close_task = None

        class FakeSession:
            async def call_tool(self, name, arguments):
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count, open_task
            open_count += 1
            open_task = asyncio.current_task()
            self.session = FakeSession()
            return self

        async def fake_close(self):
            nonlocal close_count, close_task
            close_count += 1
            close_task = asyncio.current_task()
            self.closed = True

        with (
            patch.object(McpPooledConnection, "open", fake_open),
            patch.object(McpPooledConnection, "close", fake_close),
        ):
            await pool.call_tool("server", server_params, "echo", {"i": 1})
            await pool.call_tool("server", server_params, "echo", {"i": 2})
            self.assertEqual(open_count, 1)
            self.assertEqual(close_count, 0)
            self.assertIn("server", pool._entries)
            await pool.close_all(drain=True)
            self.assertEqual(close_count, 1)
            self.assertIs(close_task, open_task)
            self.assertNotIn("server", pool._entries)

    async def test_streamable_http_reuses_worker_connection(self):
        await self._assert_http_transport_reuses_worker_connection(
            StreamableHttpServerParameters(url="http://mcp.example")
        )

    async def test_sse_reuses_worker_connection(self):
        await self._assert_http_transport_reuses_worker_connection(
            SseServerParameters(url="http://mcp.example")
        )

    async def test_server_config_overrides_per_connection_concurrency(self):
        pool = McpConnectionPool()
        server_params = _stdio_params()
        release = asyncio.Event()
        condition = asyncio.Condition()
        started = 0
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                nonlocal started
                async with condition:
                    started += 1
                    condition.notify_all()
                await release.wait()
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        async def wait_until_started(expected):
            async with condition:
                await asyncio.wait_for(
                    condition.wait_for(lambda: started >= expected),
                    timeout=2,
                )

        with patch.object(McpPooledConnection, "open", fake_open):
            tasks = [
                asyncio.create_task(
                    pool.call_tool(
                        "server",
                        server_params,
                        "echo",
                        {"i": i},
                        config={"per_connection_concurrency": 2},
                    )
                )
                for i in range(3)
            ]
            await wait_until_started(3)
            self.assertEqual(open_count, 2)
            release.set()
            await asyncio.gather(*tasks)

        await pool.close_all(drain=False)

    async def test_call_reuses_registered_entry_when_runtime_config_was_used(self):
        pool = McpConnectionPool()
        server_params = _stdio_params()
        open_count = 0

        class FakeSession:
            async def list_tools(self):
                return _FakeListToolsResponse()

            async def call_tool(self, name, arguments):
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            await pool.list_tools(
                "server",
                server_params,
                config={"per_connection_concurrency": 2, "tools": [{"name": "echo"}]},
            )
            await pool.call_tool("server", server_params, "echo", {"i": 1})

        self.assertEqual(open_count, 1)
        self.assertEqual(pool._entries["server"].per_connection_concurrency, 2)  # pyright: ignore[reportAttributeAccessIssue]
        await pool.close_all(drain=False)

    async def test_list_tools_retries_closed_connection_when_cache_missing(self):
        pool = McpConnectionPool()
        server_params = _stdio_params()
        open_count = 0

        class FakeSession:
            def __init__(self, fail_after_first_success=False):
                self.fail_after_first_success = fail_after_first_success
                self.list_tools_count = 0

            async def list_tools(self):
                self.list_tools_count += 1
                if self.fail_after_first_success and self.list_tools_count > 1:
                    raise BrokenPipeError("closed stream")
                return _FakeListToolsResponse()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession(fail_after_first_success=open_count == 1)
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            await pool.list_tools("server", server_params)
            pool._entries["server"].tools_cache = None
            await pool.list_tools("server", server_params)

        self.assertEqual(open_count, 2)
        self.assertEqual(len(pool._entries["server"].connections), 1)  # pyright: ignore[reportAttributeAccessIssue]
        await pool.close_all(drain=False)

    async def test_force_list_tools_replaces_pool_and_closes_existing_connections(self):
        pool = McpConnectionPool()
        server_params = _stdio_params()
        opened_connections = []
        closed_connections = []

        class FakeSession:
            async def list_tools(self):
                return _FakeListToolsResponse()

        async def fake_open(self):
            opened_connections.append(self)
            self.session = FakeSession()
            return self

        async def fake_close(self):
            self.closed = True
            closed_connections.append(self)

        with (
            patch.object(McpPooledConnection, "open", fake_open),
            patch.object(McpPooledConnection, "close", fake_close),
        ):
            await pool.list_tools("server", server_params)
            old_entry = pool._entries["server"]
            old_connection = opened_connections[0]

            await pool.list_tools("server", server_params, force=True)
            new_entry = pool._entries["server"]

            self.assertIsNot(new_entry, old_entry)
            self.assertTrue(old_entry.draining)
            self.assertIn(old_connection, closed_connections)
            self.assertTrue(old_connection.closed)
            self.assertNotIn(old_connection, new_entry.connections)  # pyright: ignore[reportAttributeAccessIssue]
            self.assertEqual(len(new_entry.connections), 1)  # pyright: ignore[reportAttributeAccessIssue]

            await pool.close_all(drain=False)

    async def test_call_tool_times_out_and_discards_connection(self):
        pool = McpConnectionPool()
        server_params = _stdio_params()
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                await asyncio.sleep(1)
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            with self.assertRaises(TimeoutError):
                await pool.call_tool(
                    "server",
                    server_params,
                    "slow",
                    {},
                    config={"call_timeout_seconds": 0.01},
                )

        self.assertEqual(open_count, 1)
        self.assertEqual(len(pool._entries["server"].connections), 0)  # pyright: ignore[reportAttributeAccessIssue]
        await pool.close_all(drain=False)

    async def test_call_tool_retries_anyio_closed_resource_error(self):
        pool = McpConnectionPool()
        server_params = _stdio_params()
        open_count = 0

        class FakeSession:
            def __init__(self, fail=False):
                self.fail = fail

            async def call_tool(self, name, arguments):
                if self.fail:
                    raise anyio.ClosedResourceError()
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession(fail=open_count == 1)
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            result = await pool.call_tool("server", server_params, "echo", {})

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(open_count, 2)
        self.assertEqual(len(pool._entries["server"].connections), 1)  # pyright: ignore[reportAttributeAccessIssue]
        await pool.close_all(drain=False)

    async def test_streamable_http_does_not_retry_in_flight_http_400(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                request = httpx.Request("POST", "http://mcp.example")
                response = httpx.Response(400, request=request)
                raise httpx.HTTPStatusError(
                    "400 Bad Request",
                    request=request,
                    response=response,
                )

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            with self.assertRaises(httpx.HTTPStatusError):
                await pool.call_tool("server", server_params, "echo", {})

        self.assertEqual(open_count, 1)
        await pool.close_all(drain=False)

    async def test_streamable_http_does_not_retry_in_flight_session_terminated_error(
        self,
    ):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                raise RuntimeError("Session terminated")

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            with self.assertRaisesRegex(RuntimeError, "Session terminated"):
                await pool.call_tool("server", server_params, "echo", {})

        self.assertEqual(open_count, 1)
        await pool.close_all(drain=False)

    async def test_streamable_http_does_not_retry_in_flight_worker_closed_error(
        self,
    ):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0

        class FakeSession:
            def __init__(self, generation):
                self.generation = generation

            async def call_tool(self, name, arguments):
                if self.generation == 1:
                    raise McpWorkerClosedError(
                        "MCP streamable_http worker closed: server"
                    )
                if self.generation == 2:
                    raise RuntimeError("Session terminated")
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession(open_count)
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            with self.assertRaises(McpWorkerClosedError):
                await pool.call_tool("server", server_params, "echo", {})

        self.assertEqual(open_count, 1)
        await pool.close_all(drain=False)

    async def test_streamable_http_stale_worker_health_check_fails_fast(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0
        stale_call_used = False

        class FakeSession:
            def __init__(self, generation):
                self.generation = generation

            async def send_ping(self):
                if self.generation == 1:
                    await asyncio.sleep(1)

            async def call_tool(self, name, arguments):
                nonlocal stale_call_used
                if self.generation == 1:
                    stale_call_used = True
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession(open_count)
            return self

        started_at = asyncio.get_running_loop().time()
        with patch.object(McpPooledConnection, "open", fake_open):
            result = await pool.call_tool(
                "server",
                server_params,
                "echo",
                {},
                config={
                    "call_timeout_seconds": 60,
                    "http_worker_health_check_timeout_seconds": 0.01,
                },
            )
        elapsed = asyncio.get_running_loop().time() - started_at

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(open_count, 2)
        self.assertFalse(stale_call_used)
        self.assertLess(elapsed, 0.5)
        await pool.close_all(drain=False)

    async def test_streamable_http_retries_preflight_session_terminated_error(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0
        stale_call_used = False

        class FakeSession:
            def __init__(self, generation):
                self.generation = generation

            async def send_ping(self):
                if self.generation == 1:
                    raise RuntimeError("Session terminated")

            async def call_tool(self, name, arguments):
                nonlocal stale_call_used
                if self.generation == 1:
                    stale_call_used = True
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession(open_count)
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            result = await pool.call_tool(
                "server",
                server_params,
                "echo",
                {},
            )

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(open_count, 2)
        self.assertFalse(stale_call_used)
        await pool.close_all(drain=False)

    async def test_streamable_http_preflight_replaces_worker_only_once(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0

        class FakeSession:
            async def send_ping(self):
                raise RuntimeError("Session terminated")

            async def call_tool(self, name, arguments):
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            with self.assertRaisesRegex(ConnectionError, "Session terminated"):
                await pool.call_tool(
                    "server",
                    server_params,
                    "echo",
                    {},
                )

        self.assertEqual(open_count, 2)
        await pool.close_all(drain=False)

    async def test_streamable_http_generation_change_replaces_worker_before_call(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0
        stale_call_used = False

        class FakeSession:
            def __init__(self, generation):
                self.generation = generation

            async def send_ping(self):
                if self.generation == 1:
                    return _FakeGeneration("boot-2")
                return _FakeGeneration(f"boot-{self.generation}")

            async def list_tools(self):
                return _FakeListToolsResponse([f"tool-{self.generation}"])

            async def call_tool(self, name, arguments):
                nonlocal stale_call_used
                if self.generation == 1:
                    stale_call_used = True
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.server_generation = f"boot-{open_count}"
            self.session = FakeSession(open_count)
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            self.assertEqual(
                await pool.list_tools("server", server_params),
                ["tool-1"],
            )
            self.assertEqual(
                pool.get_cached_tools("server", server_params),
                ["tool-1"],
            )

            pool._entries["server"]._last_activity_at -= 60  # pyright: ignore[reportAttributeAccessIssue]
            result = await pool.call_tool("server", server_params, "echo", {})

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(open_count, 2)
        self.assertFalse(stale_call_used)
        self.assertIsNone(pool.get_cached_tools("server", server_params))
        await pool.close_all(drain=False)

    async def test_streamable_http_cached_tools_expire_before_next_health_window(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")

        class FakeSession:
            async def list_tools(self):
                return _FakeListToolsResponse(["tool-1"])

        async def fake_open(self):
            self.session = FakeSession()
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            tools = await pool.list_tools(
                "server",
                server_params,
                config={
                    "http_worker_health_check_idle_seconds": 10,
                },
            )
            self.assertEqual(tools, ["tool-1"])
            self.assertEqual(
                pool.get_cached_tools(
                    "server",
                    server_params,
                    config={
                        "http_worker_health_check_idle_seconds": 10,
                    },
                ),
                ["tool-1"],
            )

            pool._entries["server"]._tools_cache_observed_at -= 11  # pyright: ignore[reportAttributeAccessIssue]
            self.assertIsNone(
                pool.get_cached_tools(
                    "server",
                    server_params,
                    config={
                        "http_worker_health_check_idle_seconds": 10,
                    },
                )
            )

        await pool.close_all(drain=False)

    async def test_streamable_http_409_is_not_retried_as_connection_error(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0

        class FakeSession:
            async def call_tool(self, name, arguments):
                request = httpx.Request("POST", "http://mcp.example")
                response = httpx.Response(409, request=request)
                raise httpx.HTTPStatusError(
                    "409 Conflict",
                    request=request,
                    response=response,
                )

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession()
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            with self.assertRaises(httpx.HTTPStatusError):
                await pool.call_tool("server", server_params, "echo", {})

        self.assertEqual(open_count, 1)
        await pool.close_all(drain=False)

    async def test_streamable_http_does_not_retry_in_flight_cancelled_call(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0

        class FakeSession:
            def __init__(self, fail=False):
                self.fail = fail

            async def call_tool(self, name, arguments):
                if self.fail:
                    raise asyncio.CancelledError()
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession(fail=open_count == 1)
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            with self.assertRaises(asyncio.CancelledError):
                await pool.call_tool("server", server_params, "echo", {})

        self.assertEqual(open_count, 1)
        await pool.close_all(drain=False)

    async def test_streamable_http_force_refresh_releases_blocked_call_to_retry(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
        open_count = 0
        first_call_started = asyncio.Event()
        never_release = asyncio.Event()

        class FakeSession:
            def __init__(self, generation):
                self.generation = generation

            async def list_tools(self):
                return _FakeListToolsResponse()

            async def call_tool(self, name, arguments):
                if self.generation == 1:
                    first_call_started.set()
                    await never_release.wait()
                return _FakeResult()

        async def fake_open(self):
            nonlocal open_count
            open_count += 1
            self.session = FakeSession(open_count)
            return self

        with patch.object(McpPooledConnection, "open", fake_open):
            call_task = asyncio.create_task(
                pool.call_tool("server", server_params, "echo", {})
            )
            await asyncio.wait_for(first_call_started.wait(), timeout=1)

            await pool.list_tools("server", server_params, force=True)
            result = await asyncio.wait_for(call_task, timeout=1)

        self.assertIsInstance(result, _FakeResult)
        self.assertEqual(open_count, 2)
        await pool.close_all(drain=False)


if __name__ == "__main__":
    unittest.main()
