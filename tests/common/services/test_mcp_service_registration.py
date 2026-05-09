import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from common.core.exceptions import SageHTTPException
from common.services import mcp_service


class TestMcpServiceRegistration(unittest.IsolatedAsyncioTestCase):
    async def test_update_external_mcp_uses_requested_name_and_removes_old(self):
        existing = SimpleNamespace(
            config={"protocol": "streamable_http", "streamable_http_url": "http://old/mcp"},
            user_id="owner",
        )
        dao = SimpleNamespace()
        dao.get_by_name = AsyncMock(side_effect=[existing, None])
        dao.save_mcp_server = AsyncMock()
        dao.delete_by_name = AsyncMock()

        tm = SimpleNamespace()
        tm.register_mcp_server = AsyncMock(return_value=[object()])
        tm.remove_tool_by_mcp = AsyncMock()

        with patch.object(mcp_service, "MCPServerDao", return_value=dao), patch.object(
            mcp_service, "get_tool_manager", return_value=tm
        ), patch.object(
            mcp_service, "_get_cfg", return_value=SimpleNamespace(app_mode="server")
        ):
            result = await mcp_service.update_mcp_server(
                server_name="old",
                name="new",
                protocol="streamable_http",
                streamable_http_url="http://new/mcp",
                user_id="owner",
                role="admin",
            )

        self.assertEqual(result, "new")
        tm.register_mcp_server.assert_awaited_once()
        self.assertEqual(tm.register_mcp_server.await_args.args[0], "new")
        self.assertTrue(tm.register_mcp_server.await_args.kwargs["force"])
        dao.save_mcp_server.assert_awaited_once()
        self.assertEqual(dao.save_mcp_server.await_args.kwargs["name"], "new")
        tm.remove_tool_by_mcp.assert_awaited_once_with("old")
        dao.delete_by_name.assert_awaited_once_with("old")

    async def test_add_anytool_saves_db_before_registering_tool_manager(self):
        events = []
        dao = SimpleNamespace()
        dao.get_by_name = AsyncMock(return_value=None)

        async def save_mcp_server(**kwargs):
            events.append("save")
            return SimpleNamespace(name=kwargs["name"], config=kwargs["config"], user_id=kwargs.get("user_id") or "")

        dao.save_mcp_server = AsyncMock(side_effect=save_mcp_server)
        dao.delete_by_name = AsyncMock()

        tm = SimpleNamespace()

        async def register_mcp_server(*args, **kwargs):
            events.append("register")
            self.assertIn("save", events)
            return [object()]

        tm.register_mcp_server = AsyncMock(side_effect=register_mcp_server)
        tm.remove_tool_by_mcp = AsyncMock()

        with patch.object(mcp_service, "MCPServerDao", return_value=dao), patch.object(
            mcp_service, "get_tool_manager", return_value=tm
        ), patch.object(
            mcp_service, "_get_cfg", return_value=SimpleNamespace(app_mode="server", port=18080)
        ):
            result = await mcp_service.add_mcp_server(
                name="AnyTool",
                protocol="streamable_http",
                kind="anytool",
                tools=[{"name": "echo", "parameters": {"type": "object"}}],
                user_id="",
            )

        self.assertEqual(result, mcp_service.DEFAULT_ANYTOOL_SERVER_NAME)
        self.assertEqual(events, ["save", "register"])
        self.assertTrue(tm.register_mcp_server.await_args.kwargs["force"])

    async def test_add_new_anytool_rolls_back_when_registration_fails(self):
        dao = SimpleNamespace()
        dao.get_by_name = AsyncMock(return_value=None)
        dao.save_mcp_server = AsyncMock()
        dao.delete_by_name = AsyncMock()

        tm = SimpleNamespace()
        tm.register_mcp_server = AsyncMock(return_value=False)
        tm.remove_tool_by_mcp = AsyncMock()

        with patch.object(mcp_service, "MCPServerDao", return_value=dao), patch.object(
            mcp_service, "get_tool_manager", return_value=tm
        ), patch.object(
            mcp_service, "_get_cfg", return_value=SimpleNamespace(app_mode="server", port=18080)
        ):
            with self.assertRaises(SageHTTPException):
                await mcp_service.add_mcp_server(
                    name="AnyTool",
                    protocol="streamable_http",
                    kind="anytool",
                    tools=[{"name": "echo", "parameters": {"type": "object"}}],
                    user_id="",
                )

        dao.save_mcp_server.assert_awaited_once()
        dao.delete_by_name.assert_awaited_once_with(mcp_service.DEFAULT_ANYTOOL_SERVER_NAME)
        tm.remove_tool_by_mcp.assert_awaited_once_with(mcp_service.DEFAULT_ANYTOOL_SERVER_NAME)


if __name__ == "__main__":
    unittest.main()
