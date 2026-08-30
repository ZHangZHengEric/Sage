from common.schemas.agent import convert_agent_to_config, convert_config_to_agent
from common.services.agent_service import _normalize_agent_mode, enforce_required_tools


def test_normalize_agent_mode_accepts_team():
    config = _normalize_agent_mode({"agentMode": "team"})

    assert config["agentMode"] == "team"


def test_normalize_agent_mode_retires_multi_to_simple():
    config = _normalize_agent_mode({"agentMode": "multi"})

    assert config["agentMode"] == "simple"


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


def test_simple_mode_removes_delegation_system_tools():
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


def test_agent_config_read_normalizes_multi_and_drops_legacy_flag():
    agent = convert_config_to_agent(
        "legacy",
        {"name": "Legacy", "agentMode": "multi", "multiAgent": True},
    )

    assert agent.agentMode == "simple"
    assert "multiAgent" not in convert_agent_to_config(agent)


def test_agent_config_read_migrates_synchronous_questionnaire_tool():
    agent = convert_config_to_agent(
        "legacy",
        {
            "name": "Legacy",
            "availableTools": ["file_read", "questionnaire", "questionnaire_async"],
        },
    )

    assert agent.availableTools == ["file_read", "questionnaire_async"]


def test_agent_config_round_trip_preserves_thinking_level():
    agent = convert_config_to_agent(
        "reasoner",
        {
            "name": "Reasoner",
            "deepThinking": True,
            "thinkingLevel": "high",
        },
    )

    assert agent.thinkingLevel == "high"
    assert convert_agent_to_config(agent)["thinkingLevel"] == "high"


def test_agent_config_round_trip_preserves_xhigh_thinking_level():
    agent = convert_config_to_agent(
        "reasoner",
        {
            "name": "Reasoner",
            "deepThinking": True,
            "thinkingLevel": "xhigh",
        },
    )

    assert agent.thinkingLevel == "xhigh"
    assert convert_agent_to_config(agent)["thinkingLevel"] == "xhigh"


def test_agent_config_defaults_thinking_level_to_medium():
    agent = convert_config_to_agent("reasoner", {"name": "Reasoner"})

    assert agent.thinkingLevel == "medium"
