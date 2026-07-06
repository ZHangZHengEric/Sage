import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from common.services import tool_service
from common.services.tool_service import execute_tool
from sagents.agent.agent_base import AgentBase
from sagents.tool.mcp_proxy import McpProxy
from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_proxy import ToolProxy
from sagents.tool.tool_schema import (
    McpToolSpec,
    SageMcpToolSpec,
    StreamableHttpServerParameters,
    ToolSpec,
    convert_spec_to_openai_format,
)


async def echo_kwargs(**kwargs):
    return kwargs


async def echo_no_args():
    return {"called": True}


class _TestAgent(AgentBase):
    async def run_stream(self, session_context):
        if False:
            yield []


class TestToolContextInjection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tool_manager = ToolManager(is_auto_discover=False, isolated=True)
        self.tool_manager.tools = {}

    async def test_standard_tool_uses_session_and_user_id_from_system_context(self):
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
        session_context = SimpleNamespace(
            system_context={"session_id": "session-1", "user_id": "user-1"},
            user_id="user-1",
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="echo_tool",
                session_id="runtime-session",
                user_id="runtime-user",
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

    async def test_built_in_mcp_tool_uses_session_and_user_id_from_system_context(
        self,
    ):
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
        session_context = SimpleNamespace(
            system_context={"session_id": "session-2", "user_id": "user-2"},
            user_id="user-2",
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="builtin_echo",
                session_id="runtime-session",
                user_id="runtime-user",
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

    async def test_standard_tool_uses_system_context_identity_when_present(self):
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
        session_context = SimpleNamespace(
            system_context={
                "session_id": "context-session",
                "user_id": "context-user",
            },
            user_id="context-user",
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="echo_tool",
                session_id="real-session",
                user_id="real-user",
                foo="bar",
            )

        payload = json.loads(result)
        self.assertEqual(
            payload["content"],
            {
                "foo": "bar",
                "session_id": "context-session",
                "user_id": "context-user",
            },
        )

    async def test_standard_tool_system_context_overrides_model_argument(self):
        tool = ToolSpec(
            name="echo_tool",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={"foo": {"type": "string"}},
            required=["foo"],
        )
        self.tool_manager.tools[tool.name] = tool
        session_context = SimpleNamespace(
            system_context={
                "foo": "context-value",
                "session_id": "context-session",
                "user_id": "context-user",
            },
            user_id="context-user",
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="echo_tool",
                session_id="session-ctx",
                foo="model-value",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], {"foo": "context-value"})

    async def test_standard_tool_uses_trusted_command_policy_from_system_context(self):
        tool = ToolSpec(
            name="echo_policy_tool",
            description="echo policy",
            description_i18n={},
            func=echo_kwargs,
            parameters={
                "command_policy": {"type": "object"},
            },
            required=[],
        )
        self.tool_manager.tools[tool.name] = tool
        trusted_policy = {
            "rules": [{"match": {"argv": ["git", "status"]}, "action": "allow"}],
            "default_action": "ask",
        }
        model_policy = {
            "rules": [{"match": {"argv_prefix": ["git", "push"]}, "action": "allow"}],
            "default_action": "allow",
        }
        session_context = SimpleNamespace(
            system_context={"command_policy": trusted_policy},
            user_id="user-1",
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="echo_policy_tool",
                session_id="runtime-session",
                command_policy=model_policy,
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], {"command_policy": trusted_policy})

    async def test_standard_tool_system_context_can_fill_required_argument(self):
        tool = ToolSpec(
            name="echo_tool",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={"foo": {"type": "string"}},
            required=["foo"],
        )
        self.tool_manager.tools[tool.name] = tool
        session_context = SimpleNamespace(
            system_context={"foo": "context-value"}, user_id=None
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="echo_tool",
                session_id="session-ctx",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], {"foo": "context-value"})

    async def test_standard_tool_system_context_none_does_not_override_model_argument(
        self,
    ):
        tool = ToolSpec(
            name="echo_tool",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={"foo": {"type": "string"}},
            required=["foo"],
        )
        self.tool_manager.tools[tool.name] = tool
        session_context = SimpleNamespace(system_context={"foo": None}, user_id=None)

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="echo_tool",
                session_id="session-ctx",
                foo="model-value",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], {"foo": "model-value"})

    async def test_standard_tool_does_not_leak_undeclared_system_context_keys(self):
        tool = ToolSpec(
            name="echo_tool",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={"foo": {"type": "string"}},
            required=["foo"],
        )
        self.tool_manager.tools[tool.name] = tool
        session_context = SimpleNamespace(
            system_context={
                "foo": "context-value",
                "secret": "must-not-leak",
                "session_id": "context-session",
            },
            user_id=None,
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="echo_tool",
                session_id="runtime-session",
                foo="model-value",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], {"foo": "context-value"})

    async def test_standard_tool_without_parameters_ignores_all_context(self):
        tool = ToolSpec(
            name="no_arg_tool",
            description="echo",
            description_i18n={},
            func=echo_no_args,
            parameters={},
            required=[],
        )
        self.tool_manager.tools[tool.name] = tool
        session_context = SimpleNamespace(
            system_context={
                "foo": "context-value",
                "session_id": "context-session",
                "user_id": "context-user",
            },
            user_id="context-user",
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="no_arg_tool",
                session_id="runtime-session",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], {"called": True})

    async def test_declared_session_id_is_missing_without_system_context(self):
        tool = ToolSpec(
            name="echo_tool",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={
                "foo": {"type": "string"},
                "session_id": {"type": "string"},
            },
            required=["foo", "session_id"],
        )
        self.tool_manager.tools[tool.name] = tool
        session_context = SimpleNamespace(system_context={}, user_id=None)

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="echo_tool",
                session_id="runtime-session",
                foo="bar",
            )

        payload = json.loads(result)
        self.assertFalse(payload["success"])
        self.assertIn("session_id", payload["error"])

    async def test_agent_tool_call_drops_model_forged_identity_and_uses_system_context(
        self,
    ):
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
        session_context = SimpleNamespace(
            system_context={
                "session_id": "context-session",
                "user_id": "context-user",
            },
            user_id="context-user",
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            chunks = []
            async for chunk in _TestAgent()._execute_tool(
                tool_call={
                    "id": "tool-call-1",
                    "function": {
                        "name": "echo_tool",
                        "arguments": json.dumps(
                            {
                                "foo": "bar",
                                "session_id": "forged-session",
                                "user_id": "forged-user",
                            }
                        ),
                    },
                },
                tool_manager=self.tool_manager,
                messages_input=[],
                session_id="runtime-session",
                session_context=session_context,  # pyright: ignore[reportArgumentType]
            ):
                chunks.extend(chunk)

        content = json.loads(chunks[-1].content)  # pyright: ignore[arg-type]
        self.assertEqual(
            content,
            {
                "foo": "bar",
                "session_id": "context-session",
                "user_id": "context-user",
            },
        )

    async def test_built_in_mcp_tool_system_context_overrides_and_identity_is_trusted(
        self,
    ):
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
        session_context = SimpleNamespace(
            system_context={
                "foo": "context-value",
                "session_id": "context-session",
                "user_id": "context-user",
            },
            user_id="context-user",
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="builtin_echo",
                session_id="real-session",
                user_id="real-user",
                foo="model-value",
            )

        payload = json.loads(result)
        self.assertEqual(
            payload["content"],
            {
                "foo": "context-value",
                "session_id": "context-session",
                "user_id": "context-user",
            },
        )

    async def test_remote_mcp_tool_system_context_overrides_model_argument(self):
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
        session_context = SimpleNamespace(
            system_context={
                "foo": "context-value",
                "session_id": "context-session",
                "user_id": "context-user",
            },
            user_id="context-user",
        )

        with (
            patch(
                "sagents.tool.tool_manager._resolve_session_context",
                return_value=session_context,
            ),
            patch.object(
                McpProxy,
                "_execute_streamable_http_mcp_tool",
                new_callable=AsyncMock,
                return_value={"content": [{"text": "ok"}]},
            ) as mock_execute,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="remote_echo",
                session_id="real-session",
                user_id="real-user",
                foo="model-value",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], "ok")
        call_kwargs = mock_execute.await_args.kwargs  # pyright: ignore[reportOptionalMemberAccess]
        self.assertEqual(call_kwargs["foo"], "context-value")
        self.assertEqual(call_kwargs["session_id"], "context-session")
        self.assertEqual(call_kwargs["user_id"], "context-user")

    async def test_tool_proxy_applies_system_context_overrides(self):
        tool = ToolSpec(
            name="echo_tool",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={"foo": {"type": "string"}},
            required=["foo"],
        )
        self.tool_manager.tools[tool.name] = tool
        proxy = ToolProxy(self.tool_manager)
        session_context = SimpleNamespace(
            system_context={"foo": "context-value"}, user_id=None
        )

        with patch(
            "sagents.tool.tool_manager._resolve_session_context",
            return_value=session_context,
        ):
            result = await proxy.run_tool_async(
                tool_name="echo_tool",
                session_id="session-ctx",
                foo="model-value",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], {"foo": "context-value"})

    async def test_remote_mcp_does_not_leak_undeclared_system_context_keys(self):
        tool = McpToolSpec(
            name="remote_echo",
            description="echo",
            description_i18n={},
            func=None,
            parameters={"foo": {"type": "string"}},
            required=["foo"],
            server_name="remote",
            server_params=StreamableHttpServerParameters(url="http://example.invalid"),
        )
        self.tool_manager.tools[tool.name] = tool
        session_context = SimpleNamespace(
            system_context={
                "foo": "context-value",
                "secret": "must-not-leak",
                "session_id": "context-session",
            },
            user_id=None,
        )

        with (
            patch(
                "sagents.tool.tool_manager._resolve_session_context",
                return_value=session_context,
            ),
            patch.object(
                McpProxy,
                "_execute_streamable_http_mcp_tool",
                new_callable=AsyncMock,
                return_value={"content": [{"text": "ok"}]},
            ) as mock_execute,
        ):
            result = await self.tool_manager.run_tool_async(
                tool_name="remote_echo",
                session_id="runtime-session",
                foo="model-value",
            )

        payload = json.loads(result)
        self.assertEqual(payload["content"], "ok")
        call_kwargs = mock_execute.await_args.kwargs  # pyright: ignore[reportOptionalMemberAccess]
        self.assertEqual(call_kwargs["foo"], "context-value")
        self.assertNotIn("secret", call_kwargs)
        self.assertNotIn("session_id", call_kwargs)

    async def test_mcp_tool_manager_does_not_use_runtime_identity_as_tool_args(self):
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
        call_kwargs = mock_run_mcp_tool.await_args.kwargs  # pyright: ignore[reportOptionalMemberAccess]
        self.assertEqual(call_kwargs["runtime_user_id"], "user-3")
        self.assertEqual(call_kwargs["foo"], "bar")
        self.assertNotIn("session_id", call_kwargs)
        self.assertNotIn("user_id", call_kwargs)

    async def test_mcp_proxy_preserves_session_and_user_id_from_kwargs(self):
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
        call_kwargs = mock_execute.await_args.kwargs  # pyright: ignore[reportOptionalMemberAccess]
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

    def test_defaulted_params_are_optional_in_openai_schema(self):
        tool = McpToolSpec(
            name="remote_echo",
            description="echo",
            description_i18n={},
            func=None,
            parameters={
                "foo": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
                "format": {"type": "string"},
            },
            required=["foo"],
            server_name="remote",
            server_params=StreamableHttpServerParameters(url="http://example.invalid"),
        )

        openai_tool = convert_spec_to_openai_format(tool)
        params = openai_tool["function"]["parameters"]

        self.assertEqual(set(params["required"]), {"foo", "format"})
        self.assertEqual(params["properties"]["limit"]["default"], 5)
        self.assertNotIn("anyOf", params["properties"]["limit"])
        self.assertFalse(openai_tool["function"]["strict"])

    def test_internal_tool_schema_uses_same_default_rule(self):
        tool = ToolSpec(
            name="local_echo",
            description="echo",
            description_i18n={},
            func=echo_kwargs,
            parameters={
                "foo": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
                "format": {"type": "string"},
                "session_id": {"type": "string"},
            },
            required=["foo"],
        )

        openai_tool = convert_spec_to_openai_format(tool)
        params = openai_tool["function"]["parameters"]

        self.assertEqual(set(params["properties"].keys()), {"foo", "limit", "format"})
        self.assertEqual(set(params["required"]), {"foo", "format"})
        self.assertFalse(openai_tool["function"]["strict"])

    async def test_tool_service_passes_user_id_to_tool_manager(self):
        fake_manager = type("FakeManager", (), {})()
        fake_manager.tools = {"basic_tool": object()}  # pyright: ignore[reportAttributeAccessIssue]
        fake_manager.get_tool_info = lambda name: {"type": "basic"}  # pyright: ignore[reportAttributeAccessIssue]
        fake_manager.run_tool_async = AsyncMock(return_value='{"content":"ok"}')  # pyright: ignore[reportAttributeAccessIssue]

        with patch.object(tool_service, "get_tool_manager", return_value=fake_manager):
            result = await execute_tool(
                "basic_tool",
                {"foo": "bar", "session_id": "fake-session", "user_id": "fake-user"},
                user_id="user-5",
                role="user",
            )

        self.assertEqual(result["raw_text"], '{"content":"ok"}')
        self.assertEqual(result["parsed"], {"content": "ok"})
        self.assertEqual(result["content"], {"content": "ok"})
        fake_manager.run_tool_async.assert_awaited_once()  # pyright: ignore[reportAttributeAccessIssue]
        call_kwargs = fake_manager.run_tool_async.await_args.kwargs  # pyright: ignore[reportAttributeAccessIssue,reportOptionalMemberAccess]
        self.assertEqual(call_kwargs["user_id"], "user-5")
        self.assertEqual(call_kwargs["foo"], "bar")
        self.assertEqual(call_kwargs["session_id"], "")


if __name__ == "__main__":
    unittest.main()
