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

    def test_openai_schema_still_uses_strict_nullable_optional_params(self):
        tm = ToolManager(is_auto_discover=False, isolated=True)
        tm.tools = {}

        input_schema = {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "count": {"type": "integer", "default": 10},
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

        self.assertEqual(set(params["required"]), {"query", "count"})
        self.assertEqual(params["properties"]["count"]["anyOf"][0]["type"], "integer")
        self.assertEqual(params["properties"]["count"]["anyOf"][1]["type"], "null")


if __name__ == "__main__":
    unittest.main()
