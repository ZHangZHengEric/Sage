from typing import Any, Dict, List, Optional

from common.models.agent import Agent
from common.schemas.agent import convert_config_to_agent
from sagents.utils.prompt_manager import PromptManager


def serialize_agent(agent: Agent) -> Dict[str, Any]:
    if not str(agent.name or "").strip():
        raise ValueError(f"Agent '{agent.agent_id}' is missing a display name")
    agent_resp = convert_config_to_agent(
        agent.agent_id,
        agent.config,
        user_id=agent.user_id,
        is_default=agent.is_default,
        agent_name=agent.name,
    )
    data = agent_resp.model_dump()
    data["created_at"] = agent.created_at.isoformat() if agent.created_at else None
    data["updated_at"] = agent.updated_at.isoformat() if agent.updated_at else None
    return data


def serialize_agents(agents: List[Agent]) -> List[Dict[str, Any]]:
    items = [serialize_agent(agent) for agent in agents]
    return items


def get_default_system_prompt_content(language: str = "zh", blank_draft: bool = False) -> str:
    content = PromptManager().get_prompt(
        "agent_intro_template",
        agent="common",
        language=language,
        default="",
    )
    if "{agent_name}" in content:
        content = content.format(agent_name="Sage")
    if blank_draft:
        return ""
    return content
