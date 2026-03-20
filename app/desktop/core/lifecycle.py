import os
from pathlib import Path

from loguru import logger

from .bootstrap import (
    close_skill_manager,
    close_tool_manager,
    copy_wiki_docs,
    initialize_db_connection,
    initialize_im_service,
    initialize_skill_manager,
    initialize_tool_manager,
    initialize_session_manager,
    shutdown_clients,
    validate_and_disable_mcp_servers,
)
from .services.chat.stream_manager import StreamManager
from .utils.async_utils import create_safe_task


def _setup_memory_root_path():
    """设置 MEMORY_ROOT_PATH 环境变量为 ~/.sage/memory"""
    user_home = Path.home()
    sage_home = user_home / ".sage"
    memory_path = sage_home / "memory"
    memory_path.mkdir(parents=True, exist_ok=True)
    os.environ["MEMORY_ROOT_PATH"] = str(memory_path)
    logger.info(f"MEMORY_ROOT_PATH 已设置为: {memory_path}")


async def initialize_system():
    logger.info("sage-desktop：开始初始化")
    _setup_memory_root_path()
    await initialize_db_connection()
    await initialize_tool_manager()
    await initialize_skill_manager()
    await copy_wiki_docs()  # 复制 wiki 文档到用户目录
    await initialize_session_manager()
    await initialize_im_service()
    StreamManager.get_instance()
    logger.info("sage-desktop：StreamManager 已预初始化")
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
