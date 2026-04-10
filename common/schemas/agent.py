"""Agent-related DTOs shared in common."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from common.schemas.base import BaseResponse


class AgentAbilitiesRequest(BaseModel):
    """请求生成 Agent 能力卡片的参数模型"""

    agent_id: str
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    language: Optional[str] = "zh"


class AgentAbilityItem(BaseModel):
    """单条能力卡片信息"""

    id: str
    title: str
    description: str
    promptText: str


class AgentAbilitiesData(BaseModel):
    """能力卡片列表数据容器"""

    items: List[AgentAbilityItem]


class AuthorizationRequest(BaseModel):
    user_ids: List[str]


class AgentConfigDTO(BaseModel):
    id: Optional[str] = None
    user_id: Optional[str] = None
    name: str
    systemPrefix: Optional[str] = None
    systemContext: Optional[Dict[str, Any]] = None
    availableWorkflows: Optional[Dict[str, List[str]]] = None
    availableTools: Optional[List[str]] = None
    availableSubAgentIds: Optional[List[str]] = None
    subAgentSelectionMode: Optional[str] = None
    availableSkills: Optional[List[str]] = None
    availableKnowledgeBases: Optional[List[str]] = None
    memoryType: Optional[str] = None
    maxLoopCount: Optional[int] = 10
    deepThinking: Optional[bool] = False
    llm_provider_id: Optional[str] = None
    enableMultimodal: Optional[bool] = False
    multiAgent: Optional[bool] = False
    agentMode: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    im_channels: Optional[Dict[str, Dict[str, Any]]] = None


class AutoGenAgentRequest(BaseModel):
    agent_description: str
    available_tools: Optional[List[str]] = None


class SystemPromptOptimizeRequest(BaseModel):
    original_prompt: str
    optimization_goal: Optional[str] = None


class AsyncTaskResponse(BaseModel):
    task_id: str
    task_type: str
    status: str
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: float
    updated_at: float


def convert_config_to_agent(
    agent_id: str,
    config: Dict[str, Any],
    user_id: Optional[str] = None,
    is_default: bool = False,
    agent_name: Optional[str] = None,
) -> AgentConfigDTO:
    return AgentConfigDTO(
        id=agent_id,
        user_id=user_id,
        name=agent_name or config.get("name") or f"Agent {agent_id}",
        systemPrefix=config.get("systemPrefix") or config.get("system_prefix"),
        systemContext=config.get("systemContext") or config.get("system_context"),
        availableWorkflows=config.get("availableWorkflows")
        or config.get("available_workflows"),
        availableTools=config.get("availableTools") or config.get("available_tools"),
        availableSubAgentIds=config.get("availableSubAgentIds")
        or config.get("available_sub_agent_ids"),
        subAgentSelectionMode=config.get("subAgentSelectionMode")
        or config.get("sub_agent_selection_mode"),
        availableSkills=config.get("availableSkills") or config.get("available_skills"),
        availableKnowledgeBases=config.get("availableKnowledgeBases")
        or config.get("available_knowledge_bases"),
        memoryType=config.get("memoryType") or config.get("memory_type"),
        maxLoopCount=config.get("maxLoopCount") or config.get("max_loop_count", 10),
        deepThinking=config.get("deepThinking") or config.get("deep_thinking", False),
        enableMultimodal=config.get("enableMultimodal")
        or config.get("enable_multimodal", False),
        multiAgent=config.get("multiAgent") or config.get("multi_agent", False),
        agentMode=config.get("agentMode") or config.get("agent_mode"),
        description=config.get("description"),
        is_default=is_default,
        created_at=config.get("created_at"),
        updated_at=config.get("updated_at"),
        llm_provider_id=config.get("llm_provider_id"),
    )


def convert_agent_to_config(agent: AgentConfigDTO) -> Dict[str, Any]:
    config = {
        "name": agent.name,
        "systemPrefix": agent.systemPrefix,
        "systemContext": agent.systemContext,
        "availableWorkflows": agent.availableWorkflows,
        "availableTools": agent.availableTools,
        "availableSubAgentIds": agent.availableSubAgentIds,
        "subAgentSelectionMode": agent.subAgentSelectionMode,
        "availableSkills": agent.availableSkills,
        "availableKnowledgeBases": agent.availableKnowledgeBases,
        "memoryType": agent.memoryType,
        "maxLoopCount": agent.maxLoopCount,
        "deepThinking": agent.deepThinking,
        "enableMultimodal": agent.enableMultimodal,
        "multiAgent": agent.multiAgent,
        "agentMode": agent.agentMode,
        "description": agent.description,
        "is_default": agent.is_default,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "llm_provider_id": agent.llm_provider_id,
    }
    return {k: v for k, v in config.items() if v is not None}


AgentAbilitiesResponse = BaseResponse[AgentAbilitiesData]


__all__ = [
    "AuthorizationRequest",
    "AgentConfigDTO",
    "AutoGenAgentRequest",
    "SystemPromptOptimizeRequest",
    "AsyncTaskResponse",
    "convert_config_to_agent",
    "convert_agent_to_config",
    "AgentAbilitiesRequest",
    "AgentAbilityItem",
    "AgentAbilitiesData",
    "AgentAbilitiesResponse",
]
