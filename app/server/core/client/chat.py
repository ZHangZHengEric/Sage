from typing import Dict, List, Optional
from openai import AsyncOpenAI
from sagents.llm.chat import OpenAIChat, ChatClientPool
from loguru import logger

_CLIENT_POOL: Optional[ChatClientPool] = None

async def init_chat_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = "https://api.openai.com/v1",
    model_name: Optional[str] = "gpt-4o",
    extra_configs: Optional[Dict[str, List[Dict[str, str]]]] = None,
) -> Optional[AsyncOpenAI]:
    """
    初始化全局 Chat 客户端实例 (Pool)
    支持多 Key 轮询 (通过 extra_configs)，支持每个 Key 独立的 base_url 和 model_name
    extra_configs: 包含 {"model_name": [{"api_key": "...", "base_url": "..."}]} 的字典
    返回默认的 AsyncOpenAI 客户端以保持向后兼容
    """
    global _CLIENT_POOL
    
    if _CLIENT_POOL:
        await _CLIENT_POOL.close()
    
    _CLIENT_POOL = ChatClientPool()
    
    # 1. 收集默认配置
    if api_key:
        default_client = OpenAIChat(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name
        )
        _CLIENT_POOL.add_client(default_client)
        if model_name:
            _CLIENT_POOL.set_default_model(model_name)

    # 2. 收集额外配置
    if extra_configs:
        for m_name, configs in extra_configs.items():
            if not isinstance(configs, list):
                logger.warning(f"Config for model {m_name} is not a list, skipping")
                continue
            
            for cfg in configs:
                k = cfg.get("api_key")
                if not k:
                    continue
                
                # 如果配置中没有指定 model_name，使用 map 的 key
                cfg_model = cfg.get("model_name") or m_name
                
                client = OpenAIChat(
                    api_key=k,
                    base_url=cfg.get("base_url") or base_url, # 如果没配置，回退到默认
                    model_name=cfg_model
                )
                _CLIENT_POOL.add_client(client)
    
    # 尝试获取一个默认客户端
    default_client_wrapper = _CLIENT_POOL.get_client()
    if not default_client_wrapper:
        logger.warning(
            f"LLM Chat 参数不足，未初始化 api_key={api_key}, base_url={base_url}, model_name={model_name}"
        )
        return None

    return default_client_wrapper.raw_client

def get_chat_client(model_name: Optional[str] = None) -> AsyncOpenAI:
    """
    获取全局 Chat 客户端实例 (原始 AsyncOpenAI)
    通过轮询方式获取
    :param model_name: 指定模型名称，如果为 None 则使用默认模型
    """
    global _CLIENT_POOL
    
    if _CLIENT_POOL is None:
        raise RuntimeError("Chat client not initialized")
    
    client_wrapper = _CLIENT_POOL.get_client(model_name)
    if not client_wrapper:
         # 如果找不到且没有默认，抛出异常
         raise RuntimeError(f"No chat client available for model {model_name}")

    return client_wrapper.raw_client

async def close_chat_client() -> None:
    """
    关闭全局 Chat 客户端
    """
    global _CLIENT_POOL
    
    if _CLIENT_POOL:
        await _CLIENT_POOL.close()
    
    _CLIENT_POOL = None
