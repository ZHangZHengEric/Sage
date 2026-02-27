"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
"""

import sys

from dotenv import load_dotenv

# 指定加载的 .env 文件（保持不动）
load_dotenv(".env")


from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .core import config
from .core.config import get_startup_config
from .core.exceptions import register_exception_handlers
from .core.middleware import register_middlewares
from .lifecycle import (
    cleanup_system,
    initialize_system,
    post_initialize_task,
)
from .routers import register_routes as register_chat_routes
from .utils.log import init_logging


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    cfg = get_startup_config()

    # 1) 核心系统初始化（必须先完成）
    await initialize_system(cfg)

    # 2) 异步后置初始化任务（可选）
    post_init_task = post_initialize_task()
    try:
        # 3) 启动 HTTP 服务
        yield
    finally:
        # 5) 等待后置任务完成（避免 shutdown 竞态）
        await post_init_task

        # 7) 清理系统资源
        await cleanup_system()


def create_fastapi_app() -> FastAPI:
    """创建并配置 FastAPI 应用"""

    # 创建 FastAPI 应用
    app = FastAPI(
        title="Sage Platform Service",
        description="基于 Sage 框架的智能体平台服务",
        version="1.0.0",
        lifespan=app_lifespan,
    )

    # 注册中间件
    register_middlewares(app)

    # 注册异常处理器
    register_exception_handlers(app)

    # 注册 HTTP API 路由
    register_chat_routes(app)

    @app.get("/active")
    def active():
        return "Service is available."

    return app


def start_server(cfg: config.StartupConfig):
    """
    启动 Uvicorn Server

    """
    un_cfg = uvicorn.Config(
        app=create_fastapi_app,
        host=getattr(cfg, "host", "0.0.0.0"),
        port=cfg.port,
        log_config=None,
        reload=getattr(cfg, "reload", False),
        factory=True,
    )
    server = uvicorn.Server(config=un_cfg)
    server.run()


def main():
    try:
        cfg = config.init_startup_config()
        init_logging(log_name="sage-server", log_level=getattr(cfg, "log_level", "INFO"))
        start_server(cfg)
        return 0
    except KeyboardInterrupt:
        print("服务收到中断信号，正在退出...")
        return 0
    except SystemExit:
        return 0
    except Exception:
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
