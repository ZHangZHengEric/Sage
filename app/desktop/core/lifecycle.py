from loguru import logger

from .bootstrap import (
    close_skill_manager,
    close_tool_manager,
    initialize_db_connection,
    initialize_skill_manager,
    initialize_tool_manager,
    shutdown_clients,
    validate_and_disable_mcp_servers,
)
from .utils.async_utils import create_safe_task

async def initialize_system():
    logger.info("sage-desktop：开始初始化")
    await initialize_db_connection()
    await initialize_tool_manager()
    await initialize_skill_manager()
    logger.info("sage-desktop：初始化完成")


def post_initialize_task():
    """
    服务启动完成后执行一次的后置任务
    """
    logger.info("sage-desktop：启动的后置任务...")
    return create_safe_task(validate_and_disable_mcp_servers(), name="post_initialize")


async def cleanup_system():
    logger.info("sage-desktop：正在清理资源...")
    # 关闭第三方客户端
    await shutdown_clients()
    try:
        await close_skill_manager()
    finally:
        logger.info("sage-desktop：技能管理器 已关闭")
    try:
        await close_tool_manager()
    finally:
        logger.info("sage-desktop：工具管理器 已关闭")
