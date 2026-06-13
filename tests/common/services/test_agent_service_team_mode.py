from common.schemas.agent import convert_config_to_agent
from common.services.agent_service import _normalize_agent_mode, enforce_required_tools


def test_normalize_agent_mode_accepts_team():
    config = _normalize_agent_mode({"agentMode": "team"})

    assert config["agentMode"] == "team"


def test_team_mode_adds_delegate_tools_but_not_spawn():
    config = enforce_required_tools(
        {
            "agentMode": "team",
            "availableTools": [
                "file_read",
                "sys_spawn_agent",
                "sys_delegate_task",
            ],
        }
    )

    assert "sys_team_delegate_task" in config["availableTools"]
    assert "sys_spawn_agent" not in config["availableTools"]
    assert "sys_delegate_task" not in config["availableTools"]


def test_fibre_mode_does_not_require_finish_tool():
    config = enforce_required_tools(
        {
            "agentMode": "fibre",
            "availableTools": ["file_read"],
        }
    )

    assert "sys_spawn_agent" in config["availableTools"]
    assert "sys_delegate_task" in config["availableTools"]


def test_fibre_mode_removes_team_system_tools():
    config = enforce_required_tools(
        {
            "agentMode": "fibre",
            "availableTools": [
                "file_read",
                "sys_team_delegate_task",
            ],
        }
    )

    assert "sys_spawn_agent" in config["availableTools"]
    assert "sys_delegate_task" in config["availableTools"]
    assert "sys_team_delegate_task" not in config["availableTools"]


def test_simple_mode_removes_multi_agent_system_tools():
    config = enforce_required_tools(
        {
            "agentMode": "simple",
            "availableTools": [
                "file_read",
                "sys_spawn_agent",
                "sys_delegate_task",
                "sys_team_delegate_task",
            ],
        }
    )

    assert config["availableTools"] == ["file_read"]


def test_convert_config_to_agent_preserves_manual_empty_sub_agent_selection():
    agent = convert_config_to_agent(
        "leader",
        {
            "name": "Leader",
            "agentMode": "team",
            "subAgentSelectionMode": "manual",
            "availableSubAgentIds": [],
        },
    )

    assert agent.subAgentSelectionMode == "manual"
    assert agent.availableSubAgentIds == []
