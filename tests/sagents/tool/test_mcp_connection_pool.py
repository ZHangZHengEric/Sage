import asyncio
import unittest
from unittest.mock import patch

import anyio

from sagents.tool.mcp_connection_pool import McpConnectionPool, McpPooledConnection
from sagents.tool.tool_schema import StreamableHttpServerParameters


class _FakeResult:
    isError = False
    content = []

    def model_dump(self):
        return {"content": []}


class _FakeListToolsResponse:
    tools = []


class TestMcpConnectionPool(unittest.IsolatedAsyncioTestCase):
    async def test_101_concurrent_calls_expand_to_second_connection(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
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
            self.assertEqual(len(pool._entries["server"].connections), 2)
            release.set()
            await asyncio.gather(*tasks)

        await pool.close_all(drain=False)

    async def test_low_concurrency_reuses_initialized_connection(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
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
        self.assertEqual(len(pool._entries["server"].connections), 1)
        await pool.close_all(drain=False)

    async def test_server_config_overrides_per_connection_concurrency(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
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
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
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
        self.assertEqual(pool._entries["server"].per_connection_concurrency, 2)
        await pool.close_all(drain=False)

    async def test_list_tools_retries_closed_connection_when_cache_missing(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
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
        self.assertEqual(len(pool._entries["server"].connections), 1)
        await pool.close_all(drain=False)

    async def test_force_list_tools_replaces_pool_and_closes_existing_connections(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
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

        with patch.object(McpPooledConnection, "open", fake_open), patch.object(
            McpPooledConnection, "close", fake_close
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
            self.assertNotIn(old_connection, new_entry.connections)
            self.assertEqual(len(new_entry.connections), 1)

            await pool.close_all(drain=False)

    async def test_call_tool_times_out_and_discards_connection(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
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
        self.assertEqual(len(pool._entries["server"].connections), 0)
        await pool.close_all(drain=False)

    async def test_call_tool_retries_anyio_closed_resource_error(self):
        pool = McpConnectionPool()
        server_params = StreamableHttpServerParameters(url="http://mcp.example")
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
        self.assertEqual(len(pool._entries["server"].connections), 1)
        await pool.close_all(drain=False)


if __name__ == "__main__":
    unittest.main()
