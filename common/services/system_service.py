import time
from typing import Any, Dict, Optional

from common.models.agent import AgentConfigDao
from common.models.llm_provider import LLMProviderDao
from common.models.system import SystemInfoDao
from common.services import conversation_service
from common.services.oauth.upstream import get_auth_public_config


async def get_system_info_data(
    *,
    user_id: Optional[str] = None,
    include_auth_config: bool = False,
    include_desktop_flags: bool = False,
) -> Dict[str, Any]:
    sys_dao = SystemInfoDao()
    allow_reg = await sys_dao.get_by_key("allow_registration")
    data: Dict[str, Any] = {
        "allow_registration": allow_reg != "false",
    }

    if include_auth_config:
        data.update(get_auth_public_config())

    if include_desktop_flags:
        llm_dao = LLMProviderDao()
        agent_dao = AgentConfigDao()
        providers = await llm_dao.get_list(user_id=user_id)
        agents = await agent_dao.get_list(user_id=user_id)
        data.update(
            {
                "has_model_provider": len(providers) > 0,
                "has_agent": len(agents) > 0,
            }
        )

    return data


def get_health_data(service: str = "SagePlatform") -> Dict[str, Any]:
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "service": service,
    }


async def get_agent_usage_stats_data(
    *,
    days: int,
    user_id: Optional[str] = None,
    agent_id: Optional[str] = None,
) -> Dict[str, int]:
    return await conversation_service.get_agent_usage_stats(
        days=days,
        user_id=user_id,
        agent_id=agent_id,
    )


async def update_allow_registration(allow_registration: bool) -> None:
    sys_dao = SystemInfoDao()
    await sys_dao.set_value("allow_registration", "true" if allow_registration else "false")
