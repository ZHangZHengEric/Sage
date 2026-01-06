from typing import Optional
from openai import AsyncOpenAI
from sagents.llm.chat import OpenAIChat
from sagents.utils.logger import logger

_CHAT_CLIENT: Optional[OpenAIChat] = None

async def init_chat_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = "https://api.openai.com/v1",
    model_name: Optional[str] = "gpt-4o",
) -> Optional[AsyncOpenAI]:
    """
    初始化全局 Chat 客户端实例
    返回原始的 AsyncOpenAI 客户端以保持向后兼容
    """
    global _CHAT_CLIENT
    if _CHAT_CLIENT is not None:
        return _CHAT_CLIENT.raw_client

    if not api_key or not model_name:
        logger.warning(
            f"LLM Chat 参数不足，未初始化 api_key={api_key}, base_url={base_url}, model_name={model_name}"
        )
        return None

    try:
        _CHAT_CLIENT = OpenAIChat(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name
        )
        return _CHAT_CLIENT.raw_client
    except Exception as e:
        logger.error(f"Chat 客户端初始化失败: {e}")
        return None

def get_chat_client() -> AsyncOpenAI:
    """
    获取全局 Chat 客户端实例 (原始 AsyncOpenAI)
    """
    global _CHAT_CLIENT
    if _CHAT_CLIENT is None:
        raise RuntimeError("Chat client not initialized")
    return _CHAT_CLIENT.raw_client

async def close_chat_client() -> None:
    """
    关闭全局 Chat 客户端
    """
    global _CHAT_CLIENT
    if _CHAT_CLIENT is not None:
        await _CHAT_CLIENT.close()
        _CHAT_CLIENT = None
