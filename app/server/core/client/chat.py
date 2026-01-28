import itertools
from typing import Dict, List, Optional

from openai import AsyncOpenAI
from sagents.llm.chat import OpenAIChat
from  loguru import logger

_CHAT_CLIENT: Optional[OpenAIChat] = None
_CHAT_CLIENTS: List[OpenAIChat] = []
_CLIENT_ITERATOR = None

async def init_chat_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = "https://api.openai.com/v1",
    model_name: Optional[str] = "gpt-4o",
    extra_configs: Optional[List[Dict[str, str]]] = None,
) -> Optional[AsyncOpenAI]:
    """
    初始化全局 Chat 客户端实例
    支持多 Key 轮询 (通过 extra_configs)，支持每个 Key 独立的 base_url 和 model_name
    extra_configs: 包含 {"api_key": "...", "base_url": "...", "model_name": "..."} 的列表
    返回原始的 AsyncOpenAI 客户端以保持向后兼容 (返回第一个)
    """
    global _CHAT_CLIENT, _CHAT_CLIENTS, _CLIENT_ITERATOR
    
    # 如果已经初始化且参数没有变化（这里简单判断如果不强制重新初始化），直接返回
    # 但为了支持重新初始化，我们先清理
    if _CHAT_CLIENTS:
        for client in _CHAT_CLIENTS:
             await client.close()
        _CHAT_CLIENTS = []
        _CLIENT_ITERATOR = None
    
    if _CHAT_CLIENT is not None:
        await _CHAT_CLIENT.close()
        _CHAT_CLIENT = None

    # 准备配置列表
    configs = []

    # 1. 收集默认配置
    if api_key:
        configs.append({
            "api_key": api_key,
            "base_url": base_url,
            "model_name": model_name
        })

    # 2. 收集额外配置
    if extra_configs:
        for cfg in extra_configs:
            k = cfg.get("api_key")
            if not k:
                continue
            configs.append({
                "api_key": k,
                "base_url": cfg.get("base_url") or base_url, # 如果没配置，回退到默认
                "model_name": cfg.get("model_name") or model_name
            })

    if not configs:
        logger.warning(
            f"LLM Chat 参数不足，未初始化 api_key={api_key}, base_url={base_url}, model_name={model_name}"
        )
        return None

    try:
        for cfg in configs:
            client = OpenAIChat(
                api_key=cfg["api_key"],
                base_url=cfg["base_url"],
                model_name=cfg["model_name"]
            )
            _CHAT_CLIENTS.append(client)
        
        if not _CHAT_CLIENTS:
            logger.warning("未成功初始化任何 Chat 客户端")
            return None
            
        # 设置主客户端为第一个，保持兼容
        _CHAT_CLIENT = _CHAT_CLIENTS[0]
        
        # 初始化轮询迭代器
        _CLIENT_ITERATOR = itertools.cycle(_CHAT_CLIENTS)
        
        return _CHAT_CLIENT.raw_client
    except Exception as e:
        logger.error(f"Chat 客户端初始化失败: {e}")
        return None

def get_chat_client() -> AsyncOpenAI:
    """
    获取全局 Chat 客户端实例 (原始 AsyncOpenAI)
    通过轮询方式获取
    """
    global _CHAT_CLIENT, _CLIENT_ITERATOR
    
    if _CLIENT_ITERATOR:
        try:
            client = next(_CLIENT_ITERATOR)
            return client.raw_client
        except StopIteration:
            # Should not happen with cycle unless list is empty
            pass

    if _CHAT_CLIENT is None:
        raise RuntimeError("Chat client not initialized")
    return _CHAT_CLIENT.raw_client

async def close_chat_client() -> None:
    """
    关闭全局 Chat 客户端
    """
    global _CHAT_CLIENT, _CHAT_CLIENTS, _CLIENT_ITERATOR
    
    for client in _CHAT_CLIENTS:
        await client.close()
    _CHAT_CLIENTS = []
    
    if _CHAT_CLIENT is not None:
        # Avoid double closing if it was in the list
        # But OpenAIChat.close() might be safe to call twice or we check
        # Since we cleared _CHAT_CLIENTS and closed them, _CHAT_CLIENT (which is ref to one of them) is already closed.
        # But strictly speaking, we should just set it to None
        pass
        
    _CHAT_CLIENT = None
    _CLIENT_ITERATOR = None
