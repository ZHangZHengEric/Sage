from __future__ import annotations

from .embed_client import init_embed_client, close_embed_client
from .llm_client import init_llm_client, close_llm_client

from .es_client import init_es_client, close_es_client


async def init_clients() -> None:

    await init_es_client()
    await init_embed_client()
    await init_llm_client()


async def close_clients() -> None:

    try:
        await close_es_client()
    except Exception:
        pass
    try:
        await close_llm_client()
    except Exception:
        pass
    try:
        await close_embed_client()
    except Exception:
        pass
