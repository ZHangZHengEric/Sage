from common.schemas.agent import AgentConfigDTO


def normalize_sub_agent_selection(
    agent: AgentConfigDTO,
    *,
    current_agent_id: str | None = None,
) -> None:
    agent_mode = agent.agentMode or "simple"
    if agent_mode not in {"fibre", "team"}:
        agent.subAgentSelectionMode = None
        if agent.availableSubAgentIds is None:
            agent.availableSubAgentIds = []
        return

    if agent.subAgentSelectionMode not in {"auto_all", "manual"}:
        existing_ids = [
            sub_agent_id
            for sub_agent_id in (agent.availableSubAgentIds or [])
            if sub_agent_id and sub_agent_id != current_agent_id
        ]
        agent.subAgentSelectionMode = "manual" if existing_ids else "auto_all"

    if agent.subAgentSelectionMode == "auto_all":
        agent.availableSubAgentIds = []
    else:
        unique_ids: list[str] = []
        seen = set()
        for sub_agent_id in agent.availableSubAgentIds or []:
            normalized_id = str(sub_agent_id or "").strip()
            if (
                not normalized_id
                or normalized_id == current_agent_id
                or normalized_id in seen
            ):
                continue
            seen.add(normalized_id)
            unique_ids.append(normalized_id)
        agent.availableSubAgentIds = unique_ids
