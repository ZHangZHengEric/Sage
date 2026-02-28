"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
"""
import os
import sys
# 1. Setup paths
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../../"))
sys.path.insert(0, project_root)
sys.path.insert(0, os.path.join(project_root, "app"))

import sys
from pathlib import Path

from dotenv import load_dotenv

# 指定加载的 .env 文件（保持不动）
load_dotenv(".env")


from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from .core.exceptions import register_exception_handlers
from .core.middleware import register_middlewares
from .core.config import init_startup_config
from .lifecycle import (
    cleanup_system,
    initialize_system,
    post_initialize_task,
)
from .routers import register_routes as register_chat_routes
from .utils.log import init_logging


@asynccontextmanager
async def app_lifespan(app: FastAPI):

    # 1) 核心系统初始化（必须先完成）
    await initialize_system()

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
        title="Sage Desktop",
        description="基于 Sage 框架的智能体桌面端服务",
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


def start_server(port: int = 8080):
    """
    启动 Uvicorn Server

    """
    un_cfg = uvicorn.Config(
        app=create_fastapi_app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        reload=False,
        factory=True,
    )
    server = uvicorn.Server(config=un_cfg)
    server.run()


def main():
    try:
        user_home = Path.home()
        sage_home = user_home / ".sage"
        sage_home.mkdir(parents=True, exist_ok=True)

        logs_dir = sage_home / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

        cfg = init_startup_config()
        port = 8080
        print(f"Starting Sage Desktop Server on port {port}...")
        init_logging(log_name="sage-desktop", log_level="INFO", log_path=logs_dir)
        start_server(port)  
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
