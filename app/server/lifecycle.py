from loguru import logger

from .bootstrap import (
    initialize_db_data,
    initialize_db_tables,
    initialize_skill_manager,
    initialize_tool_manager,
    close_skill_manager,
    close_tool_manager,
    validate_and_disable_mcp_servers,
)
from .core import config
from .core.client.chat import close_chat_client, init_chat_client
from .core.client.db import close_db_client, init_db_client
from .core.client.embed import close_embed_client, init_embed_client
from .core.client.es import close_es_client, init_es_client
from .core.client.minio import close_minio_client, init_minio_client


async def initialize_clients():
    cfg = config.get_startup_config()
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
        chat_client = await init_chat_client(
            api_key=cfg.default_llm_api_key,
            base_url=cfg.default_llm_api_base_url,
            model_name=cfg.default_llm_model_name,
            extra_configs=cfg.extra_llm_configs,
        )
        if chat_client is not None:
            logger.info("LLM Chat 客户端已初始化")
    except Exception as e:
        logger.error(f"LLM Chat 初始化失败: {e}")

    try:
        api_key = cfg.embed_api_key or cfg.default_llm_api_key
        base_url = cfg.embed_base_url or cfg.default_llm_api_base_url
        model = cfg.embed_model or cfg.default_llm_model_name or "text-embedding-3-large"
        dims = int(cfg.embed_dims or 1024)

        embed_client = await init_embed_client(
            api_key=api_key,
            base_url=base_url,
            model_name=model,
            dims=dims
        )
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


async def initialize_data():
    """初始化数据库数据"""
    await initialize_db_tables()
    # 1) 初始化数据库预置数据（DB 连接已在 client 初始化中完成）
    await initialize_db_data()


async def initialize_managers():
    """初始化工具与技能管理器"""
    await initialize_tool_manager()
    await initialize_skill_manager()


async def close_managers():
    await close_skill_manager()
    await close_tool_manager()


async def initialize_mcp():
    """初始化 MCP 服务器"""
    await validate_and_disable_mcp_servers()
