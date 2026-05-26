from types import SimpleNamespace
import asyncio

from sagents.context.messages.message import MessageType
from sagents.agent.simple_agent import SimpleAgent
from sagents.agent.task_executor_agent import TaskExecutorAgent
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
    tm = ToolManager(isolated=True, is_auto_discover=False)
    tm.register_tools_from_object(_StubTools())
    return tm


def _session_context():
    return SimpleNamespace(
        get_language=lambda: "en",
        effective_skill_manager=None,
    )


def _names(tools_json):
    return [tool["function"]["name"] for tool in tools_json]


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


def test_task_executor_exposes_expansion_when_suggestion_narrows_allowed_tools():
    tools_json = TaskExecutorAgent(_DummyModel(), {})._prepare_tools(
        _tool_manager(),
        ["alpha_tool"],
        _session_context(),  # pyright: ignore[reportArgumentType]
    )

    assert _names(tools_json) == ["alpha_tool", "tool_expand_tools"]


def test_task_executor_rejects_tool_not_in_current_llm_tools(monkeypatch):
    agent = TaskExecutorAgent(_DummyModel(), {})
    monkeypatch.setattr(
        agent, "_get_live_session_context", lambda session_id: _session_context()
    )

    async def _fake_llm_streaming(*args, **kwargs):
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                index=0,
                                type="function",
                                function=SimpleNamespace(
                                    name="beta_tool",
                                    arguments='{"x": 1}',
                                ),
                            )
                        ],
                        content=None,
                    )
                )
            ]
        )

    monkeypatch.setattr(agent, "_call_llm_streaming", _fake_llm_streaming)
    out = []
    tools_json = [
        tool
        for tool in _tool_manager().get_openai_tools()
        if tool["function"]["name"] in {"alpha_tool", "tool_expand_tools"}
    ]

    async def _collect_with_filtered_tools():
        async for chunks in agent._call_llm_and_process_response(
            messages_input=[],
            tools_json=tools_json,
            tool_manager=_tool_manager(),
            session_id="s1",
        ):
            out.extend(chunks)

    asyncio.run(_collect_with_filtered_tools())

    errors = [
        item
        for item in out
        if item.message_type == MessageType.AGENT_EXECUTION_ERROR.value
    ]
    assert len(errors) == 1
    assert "tool_expand_tools" in errors[0].content
    assert "beta_tool" in errors[0].content
