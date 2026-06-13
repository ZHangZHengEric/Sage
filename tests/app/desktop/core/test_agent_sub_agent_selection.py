from common.schemas.agent import AgentConfigDTO
from app.desktop.core.sub_agent_selection import normalize_sub_agent_selection


def test_team_manual_empty_selection_is_preserved():
    agent = AgentConfigDTO(
        id="leader",
        name="Team Leader",
        agentMode="team",
        subAgentSelectionMode="manual",
        availableSubAgentIds=[],
    )

    normalize_sub_agent_selection(agent, current_agent_id="leader")

    assert agent.subAgentSelectionMode == "manual"
    assert agent.availableSubAgentIds == []


def test_team_auto_all_selection_clears_explicit_ids():
    agent = AgentConfigDTO(
        id="leader",
        name="Team Leader",
        agentMode="team",
        subAgentSelectionMode="auto_all",
        availableSubAgentIds=["member"],
    )

    normalize_sub_agent_selection(agent, current_agent_id="leader")

    assert agent.subAgentSelectionMode == "auto_all"
    assert agent.availableSubAgentIds == []
