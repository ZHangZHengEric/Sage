from config.settings import get_startup_config
from .minio import init_minio_client, close_minio_client
from .llm import (
    init_embed_client,
    close_embed_client,
    init_chat_client,
    close_chat_client,
)
from .es import init_es_client, close_es_client
from .db import init_db_client, close_db_client
from sagents.utils.logger import logger


async def init_clients():
    cfg = get_startup_config()
    if not cfg:
        logger.warning("启动配置缺失，跳过所有客户端初始化")
        return

    try:
        minio_client = await init_minio_client(cfg)
        if minio_client is not None:
            logger.info("MinIO 客户端已初始化")
    except Exception as e:
        logger.error(f"MinIO 初始化失败: {e}")

    try:
        chat_client = await init_chat_client(cfg)
        if chat_client is not None:
            logger.info("LLM Chat 客户端已初始化")
    except Exception as e:
        logger.error(f"LLM Chat 初始化失败: {e}")

    try:
        embed_client = await init_embed_client(cfg)
        if embed_client is not None:
            logger.info("Embedding 客户端已初始化")
    except Exception as e:
        logger.error(f"Embedding 初始化失败: {e}")

    try:
        es_client = await init_es_client(cfg)
        if es_client is not None:
            logger.info("Elasticsearch 客户端已初始化")
    except Exception as e:
        logger.error(f"Elasticsearch 初始化失败: {e}")

    try:
        db_client = await init_db_client(cfg)
        if db_client is not None:
            logger.info(f"数据库客户端已初始化 ({cfg.db_type})")
    except Exception as e:
        logger.error(f"数据库客户端初始化失败: {e}")


async def close_clients():
    try:
        await close_minio_client()
    finally:
        logger.info("MinIO 客户端已关闭")
    try:
        await close_chat_client()
    finally:
        logger.info("LLM Chat 客户端已关闭")
    try:
        await close_embed_client()
    finally:
        logger.info("Embedding 客户端已关闭")
    try:
        await close_es_client()
    finally:
        logger.info("Elasticsearch 客户端已关闭")
    try:
        await close_db_client()
    finally:
        logger.info("数据库客户端已关闭")
