from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


from app.v1.common.core import config
from app.v1.common.models.agent import AgentConfigDao
from app.v1.common.models.conversation import ConversationDao
from app.v1.common.models.llm_provider import LLMProviderDao
from app.v1.common.services.chat_utils import create_model_client


def _get_cfg() -> config.StartupConfig:
    cfg = config.get_startup_config()
    if not cfg:
        raise RuntimeError("Startup config not initialized")
    return cfg


async def _resolve_session_provider(session_id: str) -> Optional[Any]:
    if not session_id:
        return None

    conversation = await ConversationDao().get_by_session_id(session_id)
    if not conversation or not conversation.agent_id:
        return None

    agent = await AgentConfigDao().get_by_id(conversation.agent_id)
    agent_config = agent.config if agent and isinstance(agent.config, dict) else {}
    provider_id = agent_config.get("llm_provider_id")
    if not provider_id:
        return None

    provider = await LLMProviderDao().get_by_id(provider_id)
    if not provider:
        return None
    if not provider.api_key or not provider.model:
        return None
    return provider


async def _resolve_first_provider(user_id: Optional[str]) -> Optional[Any]:
    dao = LLMProviderDao()
    providers = await dao.get_list(user_id=user_id or None)
    if not providers:
        return None
    provider = providers[0]
    if not provider.api_key or not provider.model:
        return None
    return provider


async def _resolve_model_client(
    user_id: Optional[str],
    server_config: Dict[str, Any],
    *,
    session_id: Optional[str] = None,
    prefer_first_provider: bool = False,
) -> Tuple[Any, str]:
    simulator = server_config.get("simulator") or {}
    cfg = _get_cfg()
    if cfg.app_mode == "server":
        provider = None
        if session_id and not prefer_first_provider:
            provider = await _resolve_session_provider(session_id)
        if provider is None:
            provider = await _resolve_first_provider(user_id)
        if provider is None and not prefer_first_provider:
            dao = LLMProviderDao()
            providers = await dao.get_list(user_id=user_id or None)
            provider = next(
                (item for item in providers if item.is_default),
                providers[0] if providers else None,
            )
        if not provider:
            if isinstance(simulator, dict):
                api_key = simulator.get("api_key")
                base_url = simulator.get("base_url")
                model = simulator.get("model")
                if api_key and base_url and model:
                    return create_model_client(
                        {
                            "api_key": api_key,
                            "base_url": base_url,
                            "model": model,
                        }
                    ), model
            raise RuntimeError("当前用户未配置可用的模型提供商")
        return create_model_client(
            {
                "api_key": provider.api_key,
                "base_url": provider.base_url,
                "model": provider.model,
            }
        ), provider.model

    if session_id and not prefer_first_provider:
        provider = await _resolve_session_provider(session_id)
        if provider:
            return create_model_client(
                {
                    "api_key": provider.api_key,
                    "base_url": provider.base_url,
                    "model": provider.model,
                }
            ), provider.model

    provider = await _resolve_first_provider(user_id)
    if provider:
        return create_model_client(
            {
                "api_key": provider.api_key,
                "base_url": provider.base_url,
                "model": provider.model,
            }
        ), provider.model

    model_name = cfg.default_llm_model_name
    if not cfg.default_llm_api_key:
        raise RuntimeError("未配置默认模型 API Key")
    return create_model_client(
        {
            "api_key": cfg.default_llm_api_key,
            "base_url": cfg.default_llm_api_base_url,
            "model": model_name,
        }
    ), model_name


async def generate_anytool_result(**kwargs):
    from mcp_servers.anytool.anytool_runtime import generate_anytool_result as generate
    return await generate(model_resolver=_resolve_model_client, **kwargs)
