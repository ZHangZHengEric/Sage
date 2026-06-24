import os
import unittest
from unittest.mock import patch

from mcp_servers.video_analysis.unified_video_analysis_server import (
    GeminiVideoProvider,
    QwenVideoProvider,
    analyze_video,
    get_available_providers,
    get_config_error,
    prepare_video_input,
)
from sagents.tool.tool_manager import ToolManager


class TestVideoAnalysisServer(unittest.TestCase):
    def test_provider_requires_api_key_and_model(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(get_available_providers(), [])

        with patch.dict(os.environ, {"QWEN_VIDEO_API_KEY": "k"}, clear=True):
            self.assertEqual(get_available_providers(), [])

        with patch.dict(
            os.environ,
            {"QWEN_VIDEO_API_KEY": "k", "QWEN_VIDEO_MODEL": "qwen3.5-omni-flash"},
            clear=True,
        ):
            providers = get_available_providers()
            self.assertEqual(len(providers), 1)
            self.assertIsInstance(providers[0], QwenVideoProvider)

    def test_preferred_provider_is_first(self):
        env = {
            "QWEN_VIDEO_API_KEY": "q",
            "QWEN_VIDEO_MODEL": "qwen3.5-omni-flash",
            "GEMINI_VIDEO_API_KEY": "g",
            "GEMINI_VIDEO_MODEL": "gemini-3.5-flash",
            "SAGE_VIDEO_ANALYSIS_PROVIDER": "gemini",
        }
        with patch.dict(os.environ, env, clear=True):
            providers = get_available_providers()
            self.assertIsInstance(providers[0], GeminiVideoProvider)

    def test_prepare_video_url_does_not_inline(self):
        video = prepare_video_input("https://example.com/demo.mp4")
        self.assertTrue(video.is_url)
        self.assertEqual(video.mime_type, "video/mp4")
        self.assertIsNone(video.data_url)

    def test_openai_schema_hides_only_prompt_and_video_path(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)
        tm.tools = {}
        tm.register_tool(
            analyze_video._mcp_tool_spec  # pyright: ignore[reportFunctionMemberAccess]
        )

        fn = next(
            tool["function"]
            for tool in tm.get_openai_tools(lang="zh", fallback_chain=["en"])
            if tool["function"]["name"] == "analyze_video"
        )

        self.assertEqual(
            set(fn["parameters"]["properties"].keys()),
            {"video_path", "prompt"},
        )
        self.assertEqual(set(fn["parameters"]["required"]), {"video_path"})
        self.assertIn("视频", fn["description"])
        self.assertIn("不要用于纯图片分析", fn["description"])
        self.assertIn("JSON", fn["description"])
        self.assertNotIn("环境变量", fn["description"])
        self.assertNotIn("Qwen", fn["description"])
        self.assertNotIn("Gemini", fn["description"])
        video_path_desc = fn["parameters"]["properties"]["video_path"]["description"]
        self.assertNotIn("inline", video_path_desc)
        self.assertNotIn("上限", video_path_desc)

    def test_builtin_mcp_discovery_registers_video_tool(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)
        tm.tools = {}

        tm.discover_builtin_mcp_tools_from_path("mcp_servers/video_analysis")

        self.assertIn("analyze_video", tm.tools)
        self.assertEqual(
            tm.tools["analyze_video"].server_name,
            "unified_video_analysis_server",
        )

    def test_config_error_mentions_required_video_env(self):
        message = get_config_error()
        self.assertIn("QWEN_VIDEO_API_KEY", message)
        self.assertIn("QWEN_VIDEO_MODEL", message)
        self.assertIn("GEMINI_VIDEO_API_KEY", message)
        self.assertIn("GEMINI_VIDEO_MODEL", message)


if __name__ == "__main__":
    unittest.main()
