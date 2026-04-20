from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from sagents.llm.chat import ChatClientPool, OpenAIChat

_CLIENT_POOL: Optional[ChatClientPool] = None


async def init_chat_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = "https://api.openai.com/v1",
    model_name: Optional[str] = "gpt-4o",
) -> Optional["AsyncOpenAI"]:
    """初始化全局 Chat 客户端实例 (Pool)。"""
    global _CLIENT_POOL

    if _CLIENT_POOL:
        await _CLIENT_POOL.close()

    _CLIENT_POOL = ChatClientPool()

    if api_key:
        keys = [k.strip() for k in api_key.split(",") if k.strip()]
        for k in keys:
            default_client = OpenAIChat(
                api_key=k,
                base_url=base_url,
                model_name=model_name,
            )
            _CLIENT_POOL.add_client(default_client)

        if model_name:
            _CLIENT_POOL.set_default_model(model_name)

    default_client_wrapper = _CLIENT_POOL.get_client() if _CLIENT_POOL else None
    if not default_client_wrapper:
        logger.warning(
            f"LLM Chat 参数不足，未初始化 api_key={api_key}, base_url={base_url}, model_name={model_name}"
        )
        return None

    return default_client_wrapper.raw_client


def get_chat_client(model_name: Optional[str] = None) -> "AsyncOpenAI":
    """获取全局 Chat 客户端实例 (原始 AsyncOpenAI)。"""
    global _CLIENT_POOL

    if _CLIENT_POOL is None:
        raise RuntimeError("Chat client not initialized")

    client_wrapper = _CLIENT_POOL.get_client(model_name)
    if not client_wrapper:
        raise RuntimeError(f"No chat client available for model {model_name}")

    return client_wrapper.raw_client


async def close_chat_client() -> None:
    """关闭全局 Chat 客户端。"""
    global _CLIENT_POOL

    if _CLIENT_POOL:
        await _CLIENT_POOL.close()

    _CLIENT_POOL = None
