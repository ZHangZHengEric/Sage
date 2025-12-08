"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
"""

import core
import mcp_server
import config
import router
import common
from sagents.utils.logger import logger
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys
import uvicorn
import asyncio
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from dotenv import load_dotenv

# 指定加载的 .env 文件
load_dotenv(".env")

# 项目路径配置
project_root = Path(os.path.realpath(__file__)).parent.parent.parent
sys.path.insert(0, str(project_root))


_mcp_routes = mcp_server.get_mcp_routes()

scheduler: AsyncIOScheduler | None = None


async def initialize_system():

    logger.info("正在初始化 Sage Platform Server...")
    # 1) 初始化第三方客户端 mysql, minio, llm, embed
    await core.initialize_clients()
    # 4) 初始化数据库预置数据
    await core.initialize_data()


async def post_initialize():
    """服务启动后执行一次的后置任务"""
    logger.info("正在执行 Sage Platform Server 启动后的后置任务...")
    # 1) 初始化mcp
    await core.initialize_mcp()


async def cleanup_system():
    """清理系统资源"""
    logger.info("正在清理 Sage Platform Server 资源...")
    # 1) 清理第三方客户端 mysql, minio, llm, embed
    await core.close_clients()
    # 3) 清理数据库数据
    await core.cleanup_data()


async def build_jobs():
    from service.job import JobService

    svc = JobService()
    await svc.build_waiting_doc()
    await svc.build_failed_doc()


def init_scheduler():
    """初始化 scheduler（单例）"""
    global scheduler
    if scheduler is None:
        scheduler = AsyncIOScheduler()
    """注册所有定时任务"""
    scheduler.add_job(
        build_jobs,
        trigger="interval",
        seconds=5,
        id="build_jobs",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
        misfire_grace_time=10,
    )
    scheduler.start()
    logger.info("定时任务 Scheduler 已启动")


async def shutdown_scheduler():
    global scheduler
    if scheduler:
        try:
            await scheduler.shutdown(wait=False)
            logger.info("定时任务 Scheduler 已关闭")
        except Exception as e:
            logger.error(f"关闭 scheduler 失败: {e}")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    async with mcp_server.mcp_lifespan(app):
        await initialize_system()
        init_scheduler()
        try:
            async def _run_post_init():
                await asyncio.sleep(0)
                await post_initialize()

            asyncio.create_task(_run_post_init())
            yield
        finally:
            await shutdown_scheduler()
            await cleanup_system()


def create_fastapi_app():
    """创建并配置FastAPI应用"""
    # 创建FastAPI应用
    app = FastAPI(
        title="Sage Stream Service",
        description="基于 Sage 框架的智能体流式服务",
        version="1.0.0",
        lifespan=app_lifespan,
        routes=_mcp_routes,
    )
    # 注册中间件
    common.register_middlewares(app)
    # 注册异常处理器
    common.register_exception_handlers(app)
    # 添加路由
    router.register_routes(app)

    return app


def start_server(cfg: config.StartupConfig):
    un_cfg = uvicorn.Config(
        create_fastapi_app,
        host="0.0.0.0",
        port=cfg.port,
        log_level="debug",
        reload=False,
        factory=True,

    )
    if cfg.daemon:
        import daemon
        import daemon.pidfile

        context = daemon.DaemonContext(
            working_directory=os.getcwd(),
            umask=0o002,
            pidfile=daemon.pidfile.TimeoutPIDLockFile(cfg.pid_file),
        )
        with context:
            server = uvicorn.Server(un_cfg)
            server.run()
    else:
        server = uvicorn.Server(un_cfg)
        server.run()


def main():
    try:
        cfg = config.init_startup_config()
        start_server(cfg)
        return 0
    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
