import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI

from sagents.utils.logger import logger

from core.lifecycle import (
    close_clients,
    initialize_clients,
    initialize_data,
    initialize_mcp,
)
from jobs.scheduler import init_scheduler, shutdown_scheduler
from mcp_routers import mcp_lifespan

# =========================
# 初始化 / 清理逻辑
# =========================


async def initialize_system():
    logger.info("正在初始化 Sage Platform Server...")

    # 初始化第三方客户端（mysql / minio / llm / embed 等）
    await initialize_clients()

    # 初始化数据库预置数据
    await initialize_data()


async def post_initialize():
    """
    服务启动完成后执行一次的后置任务
    """
    logger.info("正在执行 Sage Platform Server 启动后的后置任务...")

    # 初始化 MCP（注册 tools / 同步远端能力等）
    await initialize_mcp()


async def cleanup_system():
    logger.info("正在清理 Sage Platform Server 资源...")

    # 关闭第三方客户端
    await close_clients()



# =========================
# 安全的后台任务包装
# =========================


def create_safe_task(coro, name: str):
    async def runner():
        try:
            await coro
        except Exception:
            logger.error(f"后台任务执行失败: {name}")

    return asyncio.create_task(runner(), name=name)


# =========================
# FastAPI Lifespan
# =========================


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    
    # 1) 核心系统初始化（必须先完成）
    await initialize_system()

    # 2) MCP 生命周期（依赖 core 已初始化）
    async with mcp_lifespan(app):

        # 3) 启动调度器
        try:
            init_scheduler()
        except Exception:
            logger.error("Scheduler 初始化失败")
            raise

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
