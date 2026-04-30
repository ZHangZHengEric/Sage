import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.server.routers.mcp import mcp_router
from app.server.routers.tool import tool_router
from common.services.tool_service import _normalize_tool_result
from mcp_servers.anytool.anytool_server import _build_tool_schema
from mcp_servers.anytool.anytool_runtime import generate_anytool_result
from mcp_servers.anytool.anytool_http import resolve_anytool_server_name


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(tool_router)
    app.include_router(mcp_router)
    return app


class TestToolRoutes(unittest.TestCase):
    def test_anytool_server_name_resolution_prefers_last_path_segment(self):
        self.assertEqual(resolve_anytool_server_name("/api/mcp/anytool/AnyTool"), "AnyTool")
        self.assertEqual(resolve_anytool_server_name("/AnyTool"), "AnyTool")
        self.assertEqual(resolve_anytool_server_name(""), "AnyTool")

    def test_normalize_tool_result_formats_nested_json_content(self):
        normalized = _normalize_tool_result({"content": "{\"value\": 1}"})

        self.assertEqual(normalized["parsed"], {"value": 1})
        self.assertIn('"value": 1', normalized["formatted_text"])
        self.assertEqual(normalized["content"], {"value": 1})

    def test_anytool_schema_adds_hidden_context_params(self):
        tool = _build_tool_schema(
            {
                "name": "customer_send_message_whatsapp",
                "description": "Send WhatsApp message",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["phone", "message"],
                    "additionalProperties": False,
                },
            }
        )

        properties = tool.inputSchema["properties"]
        self.assertIn("phone", properties)
        self.assertIn("message", properties)
        self.assertIn("session_id", properties)
        self.assertIn("user_id", properties)
        self.assertEqual(tool.inputSchema["required"], ["phone", "message"])
        self.assertFalse(tool.inputSchema["additionalProperties"])

    def test_exec_tool_route_uses_shared_tool_execution_api(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "common.services.tool_service.execute_tool",
                new_callable=AsyncMock,
                return_value={"content": {"ok": True}},
            ) as mock_execute:
                response = client.post(
                    "/api/tools/exec",
                    json={"tool_name": "demo_tool", "tool_params": {"query": "acme"}},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"], {"content": {"ok": True}})
        mock_execute.assert_awaited_once()
        self.assertEqual(mock_execute.await_args.args[0], "demo_tool")
        self.assertEqual(mock_execute.await_args.args[1], {"query": "acme"})
        self.assertEqual(mock_execute.await_args.kwargs["user_id"], "")
        self.assertEqual(mock_execute.await_args.kwargs["role"], "user")

    def test_exec_tool_route_accepts_arguments_alias(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "common.services.tool_service.execute_tool",
                new_callable=AsyncMock,
                return_value={"content": {"ok": True}},
            ) as mock_execute:
                response = client.post(
                    "/api/tools/exec",
                    json={"tool_name": "demo_tool", "arguments": {"query": "alias"}},
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["data"], {"content": {"ok": True}})
        mock_execute.assert_awaited_once()
        self.assertEqual(mock_execute.await_args.args[0], "demo_tool")
        self.assertEqual(mock_execute.await_args.args[1], {"query": "alias"})

    def test_anytool_draft_preview_route_uses_preview_service(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "common.services.mcp_service.preview_anytool_draft",
                new_callable=AsyncMock,
                return_value={"raw_text": "{\"value\":1}", "parsed": {"value": 1}},
            ) as mock_preview:
                response = client.post(
                    "/api/mcp/anytool/preview-draft",
                    json={
                        "server_name": "draft_server",
                        "tool_definition": {
                            "name": "search_customer",
                            "description": "Search customers",
                            "parameters": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                            },
                            "returns": {
                                "type": "object",
                                "properties": {"value": {"type": "integer"}},
                            },
                        },
                        "arguments": {"query": "acme"},
                        "simulator": {"model": "gpt-test"},
                    },
                )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(
            payload["data"], {"raw_text": "{\"value\":1}", "parsed": {"value": 1}}
        )
        mock_preview.assert_awaited_once()
        self.assertEqual(mock_preview.await_args.kwargs["server_name"], "draft_server")
        self.assertEqual(mock_preview.await_args.kwargs["arguments"], {"query": "acme"})
        self.assertEqual(mock_preview.await_args.kwargs["simulator"], {"model": "gpt-test"})
        self.assertEqual(
            mock_preview.await_args.kwargs["tool_definition"]["name"], "search_customer"
        )

    def test_anytool_draft_preview_rejects_whitespace_tool_name(self):
        app = _build_app()

        with TestClient(app) as client:
            response = client.post(
                "/api/mcp/anytool/preview-draft",
                json={
                    "server_name": "draft_server",
                    "tool_definition": {
                        "name": "search customer",
                        "description": "Search customers",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                        "returns": {
                            "type": "object",
                            "properties": {"value": {"type": "integer"}},
                        },
                    },
                    "arguments": {"query": "acme"},
                    "simulator": {"model": "gpt-test"},
                },
            )

        self.assertEqual(response.status_code, 400)

    def test_anytool_tool_upsert_rejects_whitespace_tool_name(self):
        app = _build_app()

        with TestClient(app) as client:
            with patch(
                "common.services.mcp_service.ensure_default_anytool_server",
                new_callable=AsyncMock,
            ) as mock_ensure, patch(
                "common.services.mcp_service.MCPServerDao"
            ) as mock_dao_cls:
                mock_server = SimpleNamespace(
                    config={
                        "kind": "anytool",
                        "protocol": "streamable_http",
                        "streamable_http_url": "http://127.0.0.1:18080/api/mcp/anytool/AnyTool",
                        "tools": [],
                    },
                    user_id="",
                )
                mock_dao = mock_dao_cls.return_value
                mock_dao.get_by_name = AsyncMock(return_value=mock_server)
                mock_ensure.return_value = mock_server

                response = client.post(
                    "/api/mcp/anytool/tool",
                    json={
                        "server_name": "AnyTool",
                        "tool_definition": {
                            "name": "search customer",
                            "description": "Search customers",
                            "parameters": {
                                "type": "object",
                                "properties": {"query": {"type": "string"}},
                            },
                            "returns": {
                                "type": "object",
                                "properties": {"value": {"type": "integer"}},
                            },
                        },
                    },
                )

        self.assertEqual(response.status_code, 400)


class TestAnyToolRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_preview_prefers_first_provider_over_default_and_simulator(self):
        fake_first = SimpleNamespace(
            api_key="first-key",
            base_url="https://first.example/v1",
            model="first-model",
            is_default=False,
        )
        fake_default = SimpleNamespace(
            api_key="default-key",
            base_url="https://default.example/v1",
            model="default-model",
            is_default=True,
        )

        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}')
                )
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=fake_response))
            )
        )

        with patch("mcp_servers.anytool.anytool_runtime._get_cfg") as mock_get_cfg, patch(
            "mcp_servers.anytool.anytool_runtime.LLMProviderDao"
        ) as mock_dao_cls, patch(
            "mcp_servers.anytool.anytool_runtime.create_model_client",
            return_value=fake_client,
        ) as mock_create_client:
            mock_get_cfg.return_value = SimpleNamespace(app_mode="server")
            mock_dao = mock_dao_cls.return_value
            mock_dao.get_list = AsyncMock(return_value=[fake_first, fake_default])

            result = await generate_anytool_result(
                server_name="draft",
                tool_def={
                    "name": "search_customer",
                    "description": "Search customers",
                    "parameters": {"type": "object", "properties": {}},
                    "returns": {"type": "object", "properties": {}},
                },
                arguments={"query": "acme"},
                server_config={
                    "kind": "anytool",
                    "protocol": "streamable_http",
                    "tools": [],
                    "simulator": {
                        "api_key": "sim-key",
                        "base_url": "https://sim.example/v1",
                        "model": "sim-model",
                    },
                },
                user_id="user-1",
                prefer_first_provider=True,
            )

        self.assertEqual(result["model"], "first-model")
        mock_create_client.assert_called_once()
        self.assertEqual(fake_client.chat.completions.create.await_count, 1)

    async def test_actual_execution_prefers_session_provider_when_available(self):
        fake_session_provider = SimpleNamespace(
            api_key="session-key",
            base_url="https://session.example/v1",
            model="session-model",
            is_default=False,
        )
        fake_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}')
                )
            ]
        )
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=AsyncMock(return_value=fake_response))
            )
        )

        with patch("mcp_servers.anytool.anytool_runtime._get_cfg") as mock_get_cfg, patch(
            "mcp_servers.anytool.anytool_runtime.ConversationDao"
        ) as mock_conversation_dao_cls, patch(
            "mcp_servers.anytool.anytool_runtime.AgentConfigDao"
        ) as mock_agent_dao_cls, patch(
            "mcp_servers.anytool.anytool_runtime.LLMProviderDao"
        ) as mock_provider_dao_cls, patch(
            "mcp_servers.anytool.anytool_runtime.create_model_client",
            return_value=fake_client,
        ):
            mock_get_cfg.return_value = SimpleNamespace(app_mode="server")
            mock_conversation_dao = mock_conversation_dao_cls.return_value
            mock_conversation_dao.get_by_session_id = AsyncMock(
                return_value=SimpleNamespace(agent_id="agent-1")
            )
            mock_agent_dao = mock_agent_dao_cls.return_value
            mock_agent_dao.get_by_id = AsyncMock(
                return_value=SimpleNamespace(config={"llm_provider_id": "provider-1"})
            )
            mock_provider_dao = mock_provider_dao_cls.return_value
            mock_provider_dao.get_by_id = AsyncMock(return_value=fake_session_provider)

            result = await generate_anytool_result(
                server_name="AnyTool",
                tool_def={
                    "name": "search_customer",
                    "description": "Search customers",
                    "parameters": {"type": "object", "properties": {}},
                    "returns": {"type": "object", "properties": {}},
                },
                arguments={"query": "acme", "session_id": "session-1"},
                server_config={
                    "kind": "anytool",
                    "protocol": "streamable_http",
                    "tools": [],
                },
                user_id="user-1",
                session_id="session-1",
            )

        self.assertEqual(result["model"], "session-model")


if __name__ == "__main__":
    unittest.main()
