"""Desktop 端 Agent 能力接口的请求/响应模型"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .base import BaseResponse


class AgentAbilitiesRequest(BaseModel):
    """请求生成 Agent 能力卡片的参数模型"""

    agent_id: str
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None


class AgentAbilityItem(BaseModel):
    """单条能力卡片信息"""

    id: str
    title: str
    description: str
    promptText: str


class AgentAbilitiesData(BaseModel):
    """能力卡片列表数据容器"""

    items: List[AgentAbilityItem]


AgentAbilitiesResponse = BaseResponse[AgentAbilitiesData]


__all__ = [
    "AgentAbilitiesRequest",
    "AgentAbilityItem",
    "AgentAbilitiesData",
    "AgentAbilitiesResponse",
]
