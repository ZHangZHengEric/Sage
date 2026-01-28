from loguru import logger

from .bootstrap import (
    close_observability,
    close_skill_manager,
    close_tool_manager,
    initialize_clients,
    initialize_db_data,
    initialize_observability,
    initialize_scheduler,
    initialize_skill_manager,
    initialize_tool_manager,
    shutdown_clients,
    shutdown_scheduler,
    validate_and_disable_mcp_servers,
)
from .core.config import StartupConfig
from .utils.async_utils import create_safe_task


async def initialize_system(cfg: StartupConfig):
    logger.info("开始初始化 Sage Server...")

    # 初始化第三方客户端（mysql / minio / llm / embed 等）
    await initialize_clients(cfg)
    # 初始化 观测链路上报
    await initialize_observability(cfg)
    # 初始化数据库预置数据（DB 连接已在 client 初始化中完成）
    await initialize_db_data(cfg)

    """初始化工具与技能管理器"""
    await initialize_tool_manager()
    await initialize_skill_manager()

    """初始化定时任务 Scheduler"""
    await initialize_scheduler(cfg)

    logger.info("初始化 Sage Server完毕")


def post_initialize_task():
    """
    服务启动完成后执行一次的后置任务
    """
    logger.info("开始 Sage Server 启动后的后置任务...")
    return create_safe_task(validate_and_disable_mcp_servers(), name="post_initialize")


async def cleanup_system():
    logger.info("正在清理 Sage Server 资源...")
    await shutdown_scheduler()
    # 关闭 观测链路上报 (需在 DB 关闭前)
    await close_observability()
    # 关闭第三方客户端
    await shutdown_clients()
    try:
        await close_skill_manager()
    finally:
        logger.info("技能管理器 已关闭")
    try:
        await close_tool_manager()
    finally:
        logger.info("工具管理器 已关闭")
