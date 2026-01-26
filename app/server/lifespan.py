from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from .core.config import get_startup_config
from .lifecycle import (
    close_clients,
    close_managers,
    initialize_clients,
    initialize_data,
    initialize_managers,
    initialize_mcp,
)
from .jobs.scheduler import init_scheduler, shutdown_scheduler
from .services.trace import close_trace_system, initialize_trace_system
from .utils.async_utils import create_safe_task

# =========================
# 初始化 / 清理逻辑
# =========================


async def initialize_system():
    logger.info("开始初始化 Sage Server...")

    # 初始化第三方客户端（mysql / minio / llm / embed 等）
    await initialize_clients()

    # 初始化 Trace 系统
    await initialize_trace_system()

    # 初始化数据库预置数据
    await initialize_data()

    await initialize_managers()
    logger.info("初始化 Sage Server完毕")


async def post_initialize():
    """
    服务启动完成后执行一次的后置任务
    """
    logger.info("开始 Sage Server 启动后的后置任务...")

    # 初始化 MCP（注册 tools / 同步远端能力等）
    await initialize_mcp()


async def cleanup_system():
    logger.info("正在清理 Sage Server 资源...")

    # 关闭 Trace 系统 (需在 DB 关闭前)
    await close_trace_system()

    # 关闭第三方客户端
    await close_clients()
    await close_managers()


# =========================
# FastAPI Lifespan
# =========================


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    
    # 1) 核心系统初始化（必须先完成）
    await initialize_system()

    cfg = get_startup_config()

    # 3) 启动调度器
    if cfg and cfg.es_url:
        try:
            init_scheduler()
        except Exception:
            logger.error("Scheduler 初始化失败")
            raise
    else:
        logger.info("未配置 Elasticsearch (es_url)，跳过 Scheduler 初始化")

    # 4) 启动后置任务（受控后台执行）
    post_init_task = create_safe_task(
        post_initialize(),
        name="post_initialize",
    )

    try:
        yield
    finally:
        # 5) 等待后置任务完成（避免 shutdown 竞态）
        await post_init_task

        # 6) 关闭调度器
        await shutdown_scheduler()

        # 7) 清理系统资源
        await cleanup_system()
