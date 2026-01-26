from typing import Optional

from sagents.llm.embedding import OpenAIEmbedding
from sagents.utils.logger import logger

_EMBED_CLIENT: Optional[OpenAIEmbedding] = None

async def init_embed_client(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model_name: Optional[str] = "text-embedding-3-large",
    dims: int = 1024,
) -> Optional[OpenAIEmbedding]:
    """
    初始化全局 Embedding 客户端实例
    """
    global _EMBED_CLIENT
    if _EMBED_CLIENT is not None:
        return _EMBED_CLIENT

    if not api_key:
        logger.warning("Embedding 参数不足，未初始化")
        return None

    try:
        _EMBED_CLIENT = OpenAIEmbedding(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name,
            dims=dims
        )
        return _EMBED_CLIENT
    except Exception as e:
        logger.error(f"Embedding 客户端初始化失败: {e}")
        return None

def get_embed_client() -> OpenAIEmbedding:
    """
    获取全局 Embedding 客户端实例
    """
    global _EMBED_CLIENT
    if _EMBED_CLIENT is None:
        raise RuntimeError("Embedding client not initialized")
    return _EMBED_CLIENT

async def close_embed_client() -> None:
    """
    关闭全局 Embedding 客户端
    """
    global _EMBED_CLIENT
    if _EMBED_CLIENT is not None:
        await _EMBED_CLIENT.close()
        _EMBED_CLIENT = None
