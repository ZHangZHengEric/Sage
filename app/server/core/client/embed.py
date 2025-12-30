from __future__ import annotations
from typing import List, Optional
from core.config import StartupConfig
from openai import AsyncOpenAI
from sagents.utils.logger import logger

EMBED_CLIENT: Optional[AsyncOpenAI] = None
EMBED_MODEL: Optional[str] = None
EMBEDDING_DIMS: int = 1024
CHUNK_SIZE = 10


async def init_embed_client(
    cfg: Optional[StartupConfig] = None,
) -> Optional[AsyncOpenAI]:
    """
    初始化向量 Embedding 客户端
    """
    global EMBED_CLIENT, EMBED_MODEL, EMBEDDING_DIMS
    if EMBED_CLIENT is not None:
        return EMBED_CLIENT

    if cfg is None:
        raise RuntimeError("StartupConfig is required to initialize embedding client")

    api_key = cfg.embed_api_key or cfg.default_llm_api_key
    base_url = cfg.embed_base_url or cfg.default_llm_api_base_url
    EMBED_MODEL = (
        cfg.embed_model or cfg.default_llm_model_name or "text-embedding-3-large"
    )
    EMBEDDING_DIMS = int(cfg.embed_dims or 1024)

    if not api_key:
        logger.warning("Embedding 参数不足，未初始化")
        return None

    if base_url:
        EMBED_CLIENT = AsyncOpenAI(api_key=api_key, base_url=base_url)
    else:
        EMBED_CLIENT = AsyncOpenAI(api_key=api_key)

    logger.info(f"Embedding 客户端初始化成功: {EMBED_MODEL}, dims={EMBEDDING_DIMS}")
    return EMBED_CLIENT


def get_embed_client() -> AsyncOpenAI:
    """
    获取已初始化的 Embedding 客户端
    """
    global EMBED_CLIENT
    if EMBED_CLIENT is None:
        raise RuntimeError("Embedding client not initialized")
    return EMBED_CLIENT


async def embedding(
    inputs: List[str], model: Optional[str] = None
) -> List[List[float]]:
    """
    批量生成向量
    """
    client = get_embed_client()
    m = model or EMBED_MODEL or "text-embedding-3-large"
    results: List[List[float]] = []

    for i in range(0, len(inputs or []), CHUNK_SIZE):
        batch = inputs[i : i + CHUNK_SIZE]
        r = await client.embeddings.create(
            model=m, input=batch, dimensions=EMBEDDING_DIMS
        )
        results.extend(item.embedding for item in r.data)

    return results


async def close_embed_client() -> None:
    """
    关闭 Embedding 客户端
    """
    global EMBED_CLIENT, EMBED_MODEL, EMBEDDING_DIMS
    try:
        if EMBED_CLIENT is not None:
            fn = getattr(EMBED_CLIENT, "aclose", None) or getattr(
                EMBED_CLIENT, "close", None
            )
            if fn:
                res = fn()
                if hasattr(res, "__await__"):
                    await res
            logger.info("Embedding 客户端已关闭")
    except Exception as e:
        logger.error(f"关闭 Embedding 客户端失败: {e}")
    finally:
        EMBED_CLIENT = None
        EMBED_MODEL = None
        EMBEDDING_DIMS = 1024
