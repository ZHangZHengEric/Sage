from __future__ import annotations
from typing import Optional
from core.config import StartupConfig
from openai import AsyncOpenAI
from loguru import logger

MODEL_CLIENT: Optional[AsyncOpenAI] = None
MODEL_NAME: Optional[str] = None


async def init_chat_client(
    cfg: Optional[StartupConfig] = None,
) -> Optional[AsyncOpenAI]:
    """
    初始化 LLM 聊天客户端
    """
    global MODEL_CLIENT, MODEL_NAME
    if MODEL_CLIENT is not None:
        return MODEL_CLIENT

    if cfg is None:
        raise RuntimeError("StartupConfig is required to initialize chat client")

    api_key = cfg.default_llm_api_key
    base_url = cfg.default_llm_api_base_url
    model_name = cfg.default_llm_model_name

    if not api_key or not model_name:
        logger.warning(
            f"LLM Chat 参数不足，未初始化 api_key={api_key}, base_url={base_url}, model_name={model_name}"
        )
        return None

    MODEL_CLIENT = AsyncOpenAI(api_key=api_key, base_url=base_url)
    MODEL_CLIENT.model = model_name
    MODEL_NAME = model_name
    logger.info(f"LLM Chat 客户端初始化成功: {model_name}")
    return MODEL_CLIENT


def get_chat_client() -> AsyncOpenAI:
    """
    获取已初始化的 LLM 客户端
    """
    global MODEL_CLIENT
    if MODEL_CLIENT is None:
        raise RuntimeError("Chat client not initialized")
    return MODEL_CLIENT


async def close_chat_client() -> None:
    """
    关闭 LLM 客户端
    """
    global MODEL_CLIENT, MODEL_NAME
    try:
        if MODEL_CLIENT is not None:
            fn = getattr(MODEL_CLIENT, "aclose", None) or getattr(
                MODEL_CLIENT, "close", None
            )
            if fn:
                res = fn()
                if hasattr(res, "__await__"):
                    await res
            logger.info("LLM Chat 客户端已关闭")
    except Exception as e:
        logger.error(f"关闭 LLM Chat 客户端失败: {e}")
    finally:
        MODEL_CLIENT = None
        MODEL_NAME = None
