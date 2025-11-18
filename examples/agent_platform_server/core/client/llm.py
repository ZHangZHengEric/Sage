from __future__ import annotations

from typing import Optional, List
from openai import AsyncOpenAI
from config.settings import StartupConfig
from sagents.utils.logger import logger

MODEL_CLIENT: Optional[AsyncOpenAI] = None
MODEL_NAME: Optional[str] = None

EMBED_CLIENT: Optional[AsyncOpenAI] = None
EMBED_MODEL: Optional[str] = None
EMBEDDING_DIMS: int = 1024
CHUNK_SIZE = 10


async def init_chat_client(cfg: Optional[StartupConfig] = None) -> AsyncOpenAI:
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
    return MODEL_CLIENT


def get_chat_client() -> AsyncOpenAI:
    global MODEL_CLIENT
    if MODEL_CLIENT is None:
        raise RuntimeError("Model client not initialized")
    return MODEL_CLIENT


async def close_chat_client() -> None:
    global MODEL_CLIENT, MODEL_NAME
    try:
        if MODEL_CLIENT is not None:
            fn = getattr(MODEL_CLIENT, "close", None)
            if fn is not None:
                fn()
    except Exception:
        pass
    MODEL_CLIENT = None
    MODEL_NAME = None


async def init_embed_client(cfg: Optional[StartupConfig] = None) -> AsyncOpenAI:
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
    return EMBED_CLIENT


def get_embed_client() -> AsyncOpenAI:
    global EMBED_CLIENT
    if EMBED_CLIENT is None:
        raise RuntimeError("Embedding client not initialized")
    return EMBED_CLIENT


async def embedding(
    inputs: List[str], model: Optional[str] = None
) -> List[List[float]]:
    client = get_embed_client()
    m = model or EMBED_MODEL or "text-embedding-3-large"
    results: List[List[float]] = []
    for i in range(0, len(inputs or []), CHUNK_SIZE):
        batch = inputs[i: i + CHUNK_SIZE]
        r = await client.embeddings.create(
            model=m, input=batch, dimensions=EMBEDDING_DIMS
        )
        results.extend(item.embedding for item in r.data)
    return results


async def close_embed_client() -> None:
    global EMBED_CLIENT, EMBED_MODEL, EMBEDDING_DIMS
    try:
        if EMBED_CLIENT is not None:
            fn = getattr(EMBED_CLIENT, "aclose", None) or getattr(
                EMBED_CLIENT, "close", None
            )
            if fn is not None:
                res = fn()
                if hasattr(res, "__await__"):
                    await res
    except Exception:
        pass
    EMBED_CLIENT = None
    EMBED_MODEL = None
    EMBEDDING_DIMS = 1024
