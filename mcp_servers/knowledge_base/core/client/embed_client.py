"""
向量api客户端
"""

from __future__ import annotations

from typing import Optional, List
from openai import AsyncOpenAI
from config.settings import EMBED_API_KEY, EMBED_BASE_URL, EMBED_MODEL

EMBED_CLIENT: Optional[AsyncOpenAI] = None
CHUNK_SIZE = 50


async def init_embed_client() -> AsyncOpenAI:
    global EMBED_CLIENT
    if EMBED_CLIENT is not None:
        return EMBED_CLIENT

    if EMBED_BASE_URL:
        EMBED_CLIENT = AsyncOpenAI(api_key=EMBED_API_KEY, base_url=EMBED_BASE_URL)
    else:
        EMBED_CLIENT = AsyncOpenAI(api_key=EMBED_API_KEY)
    return EMBED_CLIENT


def get_embed_client() -> AsyncOpenAI:
    global EMBED_CLIENT
    if EMBED_CLIENT is None:
        return init_embed_client()
    return EMBED_CLIENT


async def embedding(
    inputs: List[str], model: Optional[str] = None
) -> List[List[float]]:
    client = get_embed_client()
    m = model or EMBED_MODEL
    results: List[List[float]] = []

    # 按50一组切片
    for i in range(0, len(inputs), CHUNK_SIZE):
        batch = inputs[i : i + CHUNK_SIZE]
        r = await client.embeddings.create(model=m, input=batch)
        results.extend(item.embedding for item in r.data)

    return results


async def close_embed_client() -> None:
    global EMBED_CLIENT, EMBED_MODEL, EMBED_BASE_URL, EMBED_API_KEY
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
    EMBED_BASE_URL = None
    EMBED_API_KEY = None
