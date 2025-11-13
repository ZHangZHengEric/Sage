"""
Sage Stream Service

基于 Sage 框架的智能体流式服务
提供简洁的 HTTP API 和 Server-Sent Events (SSE) 实时通信
"""

from contextlib import asynccontextmanager
import asyncio
import os
from pathlib import Path
import sys
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from dotenv import load_dotenv

# 指定加载的 .env 文件
load_dotenv(".env")

# 项目路径配置
project_root = Path(os.path.realpath(__file__)).parent.parent.parent
sys.path.insert(0, str(project_root))

from common.exceptions import SageHTTPException
from common.render import Response
from config.settings import StartupConfig, build_startup_config
import core.globals as global_vars
from service.mcp import validate_and_disable_mcp_servers
from core.minio_client import init_minio_client
from sagents.utils.logger import logger
import router
from service.job import JobService


async def initialize_system():
    cfg = global_vars.get_startup_config()
    logger.info("正在初始化 Sage Platform Server...")
    # 1) 初始化工作目录
    os.makedirs(cfg.logs_dir, exist_ok=True)
    os.makedirs(cfg.workspace, exist_ok=True)
    # 3) 设置全局变量
    global_vars.set_startup_config(cfg)
    await init_minio_client()
    # 4) 初始化全局数据库
    await global_vars.initialize_global_db()
    # 5) 初始化工具管理器
    await global_vars.initialize_tool_manager()
    # 6) 初始化默认模型客户端
    await global_vars.initialize_default_model_client()
    # 7) 初始化 MCP 服务器
    await validate_and_disable_mcp_servers()


async def cleanup_system():
    """清理系统资源"""
    logger.info("正在清理 Sage Platform Server 资源...")
    # 1) 清理数据库连接
    # 2) 清理工具管理器
    await global_vars.close_tool_manager()
    # 3) 清理默认模型客户端
    await global_vars.close_default_model_client()
    # 4) 清理全局数据库管理器
    await global_vars.close_global_db()


def create_lifespan_handler():
    """创建应用生命周期管理器"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """应用生命周期管理"""
        # 启动时初始化
        await initialize_system()
        stop_event = asyncio.Event()
        async def _job_scheduler():
            svc = JobService()
            while not stop_event.is_set():
                try:
                    await svc.build_waiting_doc()
                    await svc.build_failed_doc()
                except Exception as e:
                    logger.error(f"定时任务执行失败: {e}")
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=5)
                except asyncio.TimeoutError:
                    continue
        scheduler_task = asyncio.create_task(_job_scheduler())
        yield
        # 关闭时清理
        stop_event.set()
        try:
            await scheduler_task
        except Exception:
            pass
        await cleanup_system()

    return lifespan


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器"""

    async def sage_http_exception_handler(request: Request, exc: SageHTTPException):
        error_response = await Response.error(
            code=exc.status_code,
            message=exc.detail,
            error_detail=exc.error_detail,
        )
        return JSONResponse(
            status_code=exc.status_code, content=error_response.model_dump()
        )

    async def http_exception_handler(request: Request, exc: HTTPException):
        error_response = await Response.error(
            code=exc.status_code,
            message=exc.detail,
            error_detail=getattr(exc, "error_detail", ""),
        )
        return JSONResponse(
            status_code=exc.status_code, content=error_response.model_dump()
        )

    async def general_exception_handler(request: Request, exc: Exception):
        logger.error(f"未处理的异常: {str(exc)}，请求路径: {request.url}")
        import traceback

        logger.error(traceback.format_exc())

        error_response = await Response.error(
            code=500,
            message="内部服务器错误",
            error_detail=str(exc),
        )
        return JSONResponse(status_code=500, content=error_response.model_dump())

    # 通过 app.add_exception_handler 注册，避免依赖装饰器与作用域问题
    app.add_exception_handler(SageHTTPException, sage_http_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)


def create_fastapi_app():
    """创建并配置FastAPI应用"""
    # 创建FastAPI应用
    app = FastAPI(
        title="Sage Stream Service",
        description="基于 Sage 框架的智能体流式服务",
        version="1.0.0",
        lifespan=create_lifespan_handler(),
    )

    # 注册中间件与异常处理器
    """注册全局中间件（目前仅包含 CORS）"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # 健康检查接口
    @app.get("/api/health")
    async def health_check():

        return await Response.succ(
            message="服务运行正常",
            data={
                "status": "healthy",
                "timestamp": time.time(),
                "service": "SageStreamService",
            },
        )

    # 添加路由
    app.include_router(router.mcp_router)
    app.include_router(router.agent_router)
    app.include_router(router.stream_router)
    app.include_router(router.conversation_router)
    app.include_router(router.tool_router)
    app.include_router(router.file_server_router)
    app.include_router(router.kdb_router)

    return app


def start_server(cfg: StartupConfig, app):
    """启动服务器"""

    # 守护进程模式
    if cfg.daemon:
        import daemon
        import daemon.pidfile

        context = daemon.DaemonContext(
            working_directory=os.getcwd(),
            umask=0o002,
            pidfile=daemon.pidfile.TimeoutPIDLockFile(cfg.pid_file),
        )

        with context:
            uvicorn.run(
                app, host=cfg.host, port=cfg.port, log_level="debug", reload=False
            )
    else:
        uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="debug", reload=False)


def main():
    """主函数 - 启动Sage Stream Service"""
    try:
        # 1) 处理启动参数
        cfg = build_startup_config()
        global_vars.set_startup_config(cfg)

        # 创建FastAPI应用
        app = create_fastapi_app()

        # 启动服务器
        start_server(cfg, app)

    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        raise


if __name__ == "__main__":
    main()
