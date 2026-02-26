from typing import Dict, List, Optional
from openai import AsyncOpenAI
from sagents.llm.chat import OpenAIChat, ChatClientPool
from loguru import logger

_CLIENT_POOL: Optional[ChatClientPool] = None

async def init_chat_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = "https://api.openai.com/v1",
    model_name: Optional[str] = "gpt-4o",
) -> Optional[AsyncOpenAI]:
    """
    初始化全局 Chat 客户端实例 (Pool)
    支持多 Key 轮询 (逗号分隔 api_key)
    返回默认的 AsyncOpenAI 客户端以保持向后兼容
    """
    global _CLIENT_POOL
    
    if _CLIENT_POOL:
        await _CLIENT_POOL.close()
    
    _CLIENT_POOL = ChatClientPool()
    
    # 1. 收集默认配置
    if api_key:
        # 支持多Key（逗号分隔）
        keys = [k.strip() for k in api_key.split(",") if k.strip()]
        for k in keys:
             default_client = OpenAIChat(
                api_key=k,
                base_url=base_url,
                model_name=model_name
             )
             _CLIENT_POOL.add_client(default_client)
        
        if model_name:
            _CLIENT_POOL.set_default_model(model_name)
    
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
