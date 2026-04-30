import json
import unittest
from unittest.mock import AsyncMock, patch

from common.services import tool_service
from common.services.tool_service import execute_tool
from sagents.tool.mcp_proxy import McpProxy
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_schema import (
    McpToolSpec,
    SageMcpToolSpec,
    StreamableHttpServerParameters,
    ToolSpec,
    convert_spec_to_openai_format,
)


async def echo_kwargs(**kwargs):
    return kwargs


class TestToolContextInjection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool_manager = ToolManager(is_auto_discover=False, isolated=True)
        self.tool_manager.tools = {}

    async def test_standard_tool_injects_session_and_user_id(self):
        tool = ToolSpec(
            name="echo_tool",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={
                "foo": {"type": "string"},
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
            required=["foo"],
        )
        self.tool_manager.tools[tool.name] = tool

        result = await self.tool_manager.run_tool_async(
            tool_name="echo_tool",
            session_id="session-1",
            user_id="user-1",
            foo="bar",
        )

        payload = json.loads(result)
        self.assertEqual(
            payload["content"],
            {
                "foo": "bar",
                "session_id": "session-1",
                "user_id": "user-1",
            },
        )

    async def test_built_in_mcp_tool_injects_session_and_user_id(self):
        tool = SageMcpToolSpec(
            name="builtin_echo",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={
                "foo": {"type": "string"},
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
            required=["foo"],
            server_name="builtin",
        )
        self.tool_manager.tools[tool.name] = tool

        result = await self.tool_manager.run_tool_async(
            tool_name="builtin_echo",
            session_id="session-2",
            user_id="user-2",
            foo="bar",
        )

        payload = json.loads(result)
        self.assertEqual(
            payload["content"],
            {
                "foo": "bar",
                "session_id": "session-2",
                "user_id": "user-2",
            },
        )

    async def test_mcp_tool_manager_passes_user_id_to_proxy(self):
        tool = McpToolSpec(
            name="remote_echo",
            description="echo",
            description_i18n={},
            func=None,
            parameters={
                "foo": {"type": "string"},
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
            required=["foo"],
            server_name="remote",
            server_params=StreamableHttpServerParameters(url="http://example.invalid"),
        )
        self.tool_manager.tools[tool.name] = tool

        with patch.object(
            McpProxy,
            "run_mcp_tool",
            new_callable=AsyncMock,
            return_value={"content": [{"text": "ok"}]},
        ) as mock_run_mcp_tool:
            result = await self.tool_manager.run_tool_async(
                tool_name="remote_echo",
                session_id="session-3",
                user_id="user-3",
                foo="bar",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], "ok")
        mock_run_mcp_tool.assert_awaited_once()
        call_kwargs = mock_run_mcp_tool.await_args.kwargs
        self.assertEqual(call_kwargs["user_id"], "user-3")
        self.assertEqual(call_kwargs["foo"], "bar")

    async def test_mcp_proxy_injects_session_and_user_id_when_declared(self):
        tool = McpToolSpec(
            name="remote_echo",
            description="echo",
            description_i18n={},
            func=None,
            parameters={
                "foo": {"type": "string"},
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
            required=["foo"],
            server_name="remote",
            server_params=StreamableHttpServerParameters(url="http://example.invalid"),
        )

        with patch.object(
            McpProxy,
            "_execute_streamable_http_mcp_tool",
            new_callable=AsyncMock,
            return_value={"content": [{"text": "ok"}]},
        ) as mock_execute:
            proxy = McpProxy()
            result = await proxy.run_mcp_tool(
                tool,
                session_id="session-4",
                user_id="user-4",
                foo="bar",
            )

        self.assertEqual(result, {"content": [{"text": "ok"}]})
        mock_execute.assert_awaited_once()
        call_kwargs = mock_execute.await_args.kwargs
        self.assertEqual(call_kwargs["foo"], "bar")
        self.assertEqual(call_kwargs["session_id"], "session-4")
        self.assertEqual(call_kwargs["user_id"], "user-4")

    def test_auto_injected_params_are_hidden_from_openai_schema(self):
        tool = McpToolSpec(
            name="remote_echo",
            description="echo",
            description_i18n={},
            func=None,
            parameters={
                "foo": {"type": "string"},
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
            required=["foo"],
            server_name="remote",
            server_params=StreamableHttpServerParameters(url="http://example.invalid"),
        )

        openai_tool = convert_spec_to_openai_format(tool)
        params = openai_tool["function"]["parameters"]

        self.assertEqual(set(params["properties"].keys()), {"foo"})
        self.assertEqual(params["required"], ["foo"])

    async def test_tool_service_passes_user_id_to_tool_manager(self):
        fake_manager = type("FakeManager", (), {})()
        fake_manager.tools = {"basic_tool": object()}
        fake_manager.get_tool_info = lambda name: {"type": "basic"}
        fake_manager.run_tool_async = AsyncMock(return_value='{"content":"ok"}')

        with patch.object(tool_service, "get_tool_manager", return_value=fake_manager):
            result = await execute_tool(
                "basic_tool",
                {"foo": "bar"},
                user_id="user-5",
                role="user",
            )

        self.assertEqual(result, '{"content":"ok"}')
        fake_manager.run_tool_async.assert_awaited_once()
        call_kwargs = fake_manager.run_tool_async.await_args.kwargs
        self.assertEqual(call_kwargs["user_id"], "user-5")
        self.assertEqual(call_kwargs["foo"], "bar")


if __name__ == "__main__":
    unittest.main()
