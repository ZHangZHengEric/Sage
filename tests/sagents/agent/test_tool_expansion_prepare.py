from types import SimpleNamespace

from sagents.agent.simple_agent import SimpleAgent
from sagents.tool.tool_base import tool
from sagents.tool.tool_manager import ToolManager


class _DummyModel:
    pass


class _StubTools:
    @tool()
    def alpha_tool(self):
        """alpha"""
        return "alpha"

    @tool()
    def beta_tool(self):
        """beta"""
        return "beta"

    @tool()
    def tool_expand_tools(self, tool_names: list[str] = None):  # pyright: ignore[reportArgumentType]
        """expand"""
        return tool_names or []


def _tool_manager():
    manager = ToolManager(isolated=True, is_auto_discover=False)
    manager.register_tools_from_object(_StubTools())
    return manager


def _session_context():
    return SimpleNamespace(
        get_language=lambda: "en",
        effective_skill_manager=None,
    )


def _names(tools_json):
    return [tool_config["function"]["name"] for tool_config in tools_json]


def test_simple_agent_exposes_expansion_when_suggestion_narrows_allowed_tools():
    tools_json = SimpleAgent(_DummyModel(), {})._prepare_tools(
        _tool_manager(),
        ["alpha_tool"],
        _session_context(),  # pyright: ignore[reportArgumentType]
    )

    assert _names(tools_json) == ["alpha_tool", "tool_expand_tools"]


def test_simple_agent_does_not_expose_expansion_when_suggestion_is_not_narrowed():
    tools_json = SimpleAgent(_DummyModel(), {})._prepare_tools(
        _tool_manager(),
        ["alpha_tool", "beta_tool"],
        _session_context(),  # pyright: ignore[reportArgumentType]
    )

    assert _names(tools_json) == ["alpha_tool", "beta_tool"]
