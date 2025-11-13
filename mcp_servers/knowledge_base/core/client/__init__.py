from __future__ import annotations

from .embed_client import init_embed_client, close_embed_client
from .llm_client import init_llm_client, close_llm_client
from .db_client import init_db_client, get_global_db
from .minio_client import init_minio_client, close_minio_client
from .es_client import init_es_client, close_es_client


async def init_clients() -> None:
    await init_db_client()
    await init_minio_client()
    await init_es_client()
    await init_embed_client()
    await init_llm_client()


async def close_clients() -> None:
    try:
        sm = await get_global_db()
        await sm.close()
    except Exception:
        pass
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
    try:
        await close_minio_client()
    except Exception:
        pass
