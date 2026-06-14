from sagents.agent.fibre.tools import FibreTools
from sagents.agent.team.tools import TeamTools
from sagents.context.session_context import SessionContext
from sagents.tool import ToolManager, ToolProxy
from sagents.tool.tool_base import tool


class FileLikeTools:
    @tool()
    def file_read(self, path: str) -> str:
        return path


def _session_with_tools(tool_manager):
    return SessionContext(
        session_id="session",
        user_id="user",
        agent_id="agent",
        session_root_space="/tmp/sage-test-sessions",
        tool_manager=tool_manager,
    )


def test_restrict_tools_for_mode_preserves_all_tool_proxy_managers():
    system_manager = ToolManager(is_auto_discover=False, isolated=True)
    system_manager.register_tools_from_object(TeamTools())
    normal_manager = ToolManager(is_auto_discover=False, isolated=True)
    normal_manager.register_tools_from_object(FileLikeTools())

    proxy = ToolProxy([system_manager, normal_manager])
    session_context = _session_with_tools(proxy)

    session_context.restrict_tools_for_mode("simple")

    tool_names = set(session_context.tool_manager.list_all_tools_name())
    assert "file_read" in tool_names
    assert "sys_team_delegate_task" not in tool_names


def test_restrict_tools_for_team_keeps_only_team_delegate_system_tool():
    system_manager = ToolManager(is_auto_discover=False, isolated=True)
    system_manager.register_tools_from_object(FibreTools())
    system_manager.register_tools_from_object(TeamTools())
    normal_manager = ToolManager(is_auto_discover=False, isolated=True)
    normal_manager.register_tools_from_object(FileLikeTools())

    proxy = ToolProxy([system_manager, normal_manager])
    session_context = _session_with_tools(proxy)

    session_context.restrict_tools_for_mode("team")

    tool_names = set(session_context.tool_manager.list_all_tools_name())
    assert "file_read" in tool_names
    assert "sys_team_delegate_task" in tool_names
    assert "sys_spawn_agent" not in tool_names
    assert "sys_delegate_task" not in tool_names


def test_restrict_tools_for_fibre_drops_team_system_tools_only():
    system_manager = ToolManager(is_auto_discover=False, isolated=True)
    system_manager.register_tools_from_object(FibreTools())
    system_manager.register_tools_from_object(TeamTools())
    normal_manager = ToolManager(is_auto_discover=False, isolated=True)
    normal_manager.register_tools_from_object(FileLikeTools())

    proxy = ToolProxy([system_manager, normal_manager])
    session_context = _session_with_tools(proxy)

    session_context.restrict_tools_for_mode("fibre")

    tool_names = set(session_context.tool_manager.list_all_tools_name())
    assert "file_read" in tool_names
    assert "sys_spawn_agent" in tool_names
    assert "sys_delegate_task" in tool_names
    assert "sys_team_delegate_task" not in tool_names
