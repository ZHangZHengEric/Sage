import asyncio

from loguru import logger

from .bootstrap import (
    close_observability,
    close_skill_manager,
    close_tool_manager,
    initialize_db_connection,
    initialize_global_clients,
    initialize_observability,
    initialize_scheduler,
    initialize_skill_manager,
    initialize_tool_manager,
    initialize_session_manager,
    shutdown_clients,
    shutdown_scheduler,
    validate_and_disable_mcp_servers,
)
from common.core.config import StartupConfig
from common.utils.async_utils import create_safe_task


async def _require_initialized(name: str, initializer_result):
    result = await initializer_result
    if result is None:
        raise RuntimeError(f"{name} initialization failed")
    return result


async def initialize_system(cfg: StartupConfig):
    logger.info("Sage开始初始化")

    # 1. 优先初始化数据库和数据
    await _require_initialized("db connection", initialize_db_connection(cfg))
    
    # 2. 初始化观测链路上报 (Initialize Observability - needs DB)
    await initialize_observability(cfg)

    # 5. 初始化其他第三方客户端
    await initialize_global_clients(cfg)

    """初始化工具与技能管理器"""
    await _require_initialized("tool manager", initialize_tool_manager())
    await _require_initialized("skill manager", initialize_skill_manager(cfg))

    """初始化全局 SessionManager"""
    await _require_initialized("session manager", initialize_session_manager(cfg))

    """初始化定时任务 Scheduler"""
    await initialize_scheduler(cfg)

    logger.info("Sage初始化完成")


def post_initialize_task():
    """
    服务启动完成后执行一次的后置任务
    """
    return create_safe_task(_post_initialize(), name="post_initialize")


async def _post_initialize():
    await validate_and_disable_mcp_servers()
    create_safe_task(_ensure_default_anytool_server_ready(), name="ensure_default_anytool_server")
    await _start_task_scheduler()


async def _ensure_default_anytool_server_ready():
    from common.services.mcp_service import ensure_default_anytool_server

    for attempt in range(3):
        try:
            await asyncio.sleep(2 if attempt == 0 else 3)
            await ensure_default_anytool_server(register_tool_manager=True)
            logger.info("默认 AnyTool MCP server 已激活")
            return
        except Exception as exc:
            logger.warning(f"默认 AnyTool MCP server 激活失败（第 {attempt + 1} 次）: {exc}")


async def _start_task_scheduler():
    try:
        await asyncio.sleep(5)
        from mcp_servers.task_scheduler.task_scheduler_server import ensure_scheduler_started

        started = ensure_scheduler_started()
        logger.info(f"Sage：TaskScheduler {'已启动' if started else '已存在'}")
    except Exception as exc:
        logger.warning(f"Sage：TaskScheduler 启动失败: {exc}")


async def cleanup_system():
    logger.info("Sage正在清理资源...")
    await shutdown_scheduler()
    # 关闭 观测链路上报 (需在 DB 关闭前)
    await close_observability()
    # 关闭第三方客户端
    await shutdown_clients()
    try:
        await close_skill_manager()
    finally:
        logger.info("Sage技能管理器 已关闭")
    try:
        await close_tool_manager()
    finally:
        logger.info("Sage工具管理器 已关闭")
