import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sagents.tool.tool_manager import ToolManager


class TestImProviderImportCost(unittest.TestCase):
    def test_importing_im_server_does_not_load_lark_oapi(self):
        repo_root = Path(__file__).resolve().parents[2]
        script = """
import sys
import mcp_servers.im_server.im_server  # noqa: F401
from mcp_servers.im_server.im_providers import get_im_provider
from mcp_servers.im_server.providers.feishu import FeishuProvider

assert get_im_provider
assert FeishuProvider
assert "lark_oapi" not in sys.modules
assert "lark_oapi.api.im.v1" not in sys.modules
assert "mcp_servers.im_server.providers.feishu.websocket" not in sys.modules
assert "mcp_servers.im_server.providers.dingtalk.stream" not in sys.modules
assert "dingtalk_stream" not in sys.modules
"""
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_feishu_websocket_client_is_lazy_exported(self):
        from mcp_servers.im_server.providers.feishu import FeishuWebSocketClient

        self.assertTrue(callable(FeishuWebSocketClient))

    def test_discovery_skips_provider_implementation_modules(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)
        imported = []

        def fake_import(module_name):
            imported.append(module_name)

        mcp_servers_path = Path(__file__).resolve().parents[2] / "mcp_servers"
        with patch("importlib.import_module", side_effect=fake_import):
            tm._discover_import_path(
                path=str(mcp_servers_path),
                root_package="mcp_servers",
            )

        self.assertTrue(imported)
        self.assertFalse(
            any(".providers." in name or name.endswith(".providers") for name in imported)
        )
        self.assertTrue(any(name.endswith(".im_server.im_server") for name in imported))

    def test_server_discovery_skips_all_im_server_modules(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)
        imported = []

        def fake_import(module_name):
            imported.append(module_name)

        mcp_servers_path = Path(__file__).resolve().parents[2] / "mcp_servers"
        with (
            patch.dict(os.environ, {"SAGE_INTERNAL_SERVER_PROCESS": "1"}),
            patch("importlib.import_module", side_effect=fake_import),
        ):
            tm.discover_builtin_mcp_tools_from_path(str(mcp_servers_path))

        self.assertTrue(imported)
        self.assertFalse(
            any(
                name == "mcp_servers.im_server"
                or name.startswith("mcp_servers.im_server.")
                for name in imported
            )
        )
        self.assertTrue(any(name.startswith("mcp_servers.search.") for name in imported))

    def test_server_discovery_does_not_register_preloaded_im_tools(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)

        def im_tool():
            return None

        def search_tool():
            return None

        im_tool._mcp_tool_spec = type("Spec", (), {"name": "send_message_through_im"})()
        search_tool._mcp_tool_spec = type("Spec", (), {"name": "web_search"})()

        discovered = {
            "mcp_servers.im_server.im_server": [im_tool],
            "mcp_servers.search.unified_search_server": [search_tool],
        }
        with (
            patch.dict(os.environ, {"SAGE_INTERNAL_SERVER_PROCESS": "1"}),
            patch(
                "sagents.tool.tool_manager._DISCOVERED_MCP_TOOLS",
                discovered,
            ),
            patch.object(tm, "_discover_import_path"),
        ):
            tm.discover_builtin_mcp_tools_from_path("mcp_servers")

        self.assertIn("web_search", tm.tools)
        self.assertNotIn("send_message_through_im", tm.tools)


if __name__ == "__main__":
    unittest.main()
