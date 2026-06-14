import asyncio
import unittest
from unittest.mock import patch

import anyio
from mcp import StdioServerParameters

from sagents.tool.mcp_connection_pool import McpConnectionPool, McpPooledConnection
from sagents.tool.tool_schema import SseServerParameters, StreamableHttpServerParameters


class _FakeResult:
    isError = False
    content = []

    def model_dump(self):
        return {"content": []}


class _FakeListToolsResponse:
    tools = []


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


if __name__ == "__main__":
    unittest.main()
