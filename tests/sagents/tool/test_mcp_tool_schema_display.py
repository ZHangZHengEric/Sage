import unittest

from sagents.tool.tool_manager import ToolManager
from sagents.tool.tool_schema import McpToolSpec, StreamableHttpServerParameters


class TestMcpToolSchemaDisplay(unittest.TestCase):
    def test_mcp_display_schema_keeps_original_required_and_types(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)
        tm.tools = {}

        input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                },
                "count": {
                    "type": "integer",
                    "default": 10,
                    "description": "Number of results.",
                },
            },
            "required": ["query"],
        }
        tool = McpToolSpec(
            name="web_search",
            description="Search the web",
            description_i18n={},
            func=None,
            parameters=input_schema["properties"],
            required=input_schema["required"],
            server_name="search",
            server_params=StreamableHttpServerParameters(url="http://example.invalid/mcp"),
            input_schema=input_schema,
        )
        tm.tools[tool.name] = tool

        display_tool = tm.list_tools_with_type()[0]

        self.assertEqual(display_tool["required"], ["query"])
        self.assertEqual(display_tool["parameters"]["count"]["type"], "integer")
        self.assertNotIn("anyOf", display_tool["parameters"]["count"])
        self.assertEqual(display_tool["input_schema"]["required"], ["query"])

    def test_openai_schema_uses_default_to_keep_params_optional(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)
        tm.tools = {}

        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer", "default": 10},
                "source": {"type": "string"},
                "session_id": {"type": "string"},
                "user_id": {"type": "string"},
            },
            "required": ["query"],
        }
        tool = McpToolSpec(
            name="web_search",
            description="Search the web",
            description_i18n={},
            func=None,
            parameters=input_schema["properties"],
            required=input_schema["required"],
            server_name="search",
            server_params=StreamableHttpServerParameters(url="http://example.invalid/mcp"),
            input_schema=input_schema,
        )
        tm.tools[tool.name] = tool

        params = tm.get_openai_tools()[0]["function"]["parameters"]

        self.assertEqual(set(params["properties"].keys()), {"query", "count", "source"})
        self.assertEqual(set(params["required"]), {"query", "source"})
        self.assertEqual(params["properties"]["count"]["type"], "integer")
        self.assertNotIn("anyOf", params["properties"]["count"])
        self.assertFalse(tm.get_openai_tools()[0]["function"]["strict"])

    def test_display_schema_uses_requested_language_for_descriptions(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)
        tm.tools = {}

        input_schema = {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                    "description_i18n": {
                        "zh": "搜索关键词。",
                        "en": "Search query.",
                    },
                },
            },
            "required": ["query"],
        }
        tool = McpToolSpec(
            name="web_search",
            description="Search the web",
            description_i18n={
                "zh": "搜索网页",
                "en": "Search the web",
            },
            func=None,
            parameters=input_schema["properties"],
            required=input_schema["required"],
            server_name="search",
            server_params=StreamableHttpServerParameters(url="http://example.invalid/mcp"),
            input_schema=input_schema,
        )
        tm.tools[tool.name] = tool

        display_tool = tm.list_tools_with_type(lang="zh", fallback_chain=["en"])[0]

        self.assertEqual(display_tool["description"], "搜索网页")
        self.assertEqual(display_tool["parameters"]["query"]["description"], "搜索关键词。")
        self.assertEqual(display_tool["input_schema"]["properties"]["query"]["description"], "搜索关键词。")
        self.assertEqual(display_tool["input_schema"]["required"], ["query"])


if __name__ == "__main__":
    unittest.main()
