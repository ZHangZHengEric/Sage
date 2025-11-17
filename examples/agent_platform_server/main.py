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
from config.settings import (
    init_startup_config,
    get_startup_config,
)
from service.mcp import validate_and_disable_mcp_servers
from core.client import init_clients, close_clients
from sagents.utils.logger import logger
import router
from service.job import JobService
from service.user import parse_access_token
from core.globals import initialize_db_data, close_tool_manager, initialize_tool_manager
from mcp_server.knwoledge_base import kdb_mcp

kdb_mcp_http = kdb_mcp.http_app(path="/mcp/kdb")


async def initialize_system():

    logger.info("正在初始化 Sage Platform Server...")
    await init_clients()
    # 4) 初始化数据库预置数据（DB 连接已在 client 初始化中完成）
    await initialize_db_data()
    # 5) 初始化工具管理器
    await initialize_tool_manager()
    # 7) 初始化 MCP 服务器
    await validate_and_disable_mcp_servers()


async def cleanup_system():
    """清理系统资源"""
    logger.info("正在清理 Sage Platform Server 资源...")
    # 1) 清理第三方客户端
    await close_clients()
    # 2) 清理工具管理器
    await close_tool_manager()


async def _job_scheduler(stop_event: asyncio.Event):
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


def start_job_scheduler() -> tuple[asyncio.Event, asyncio.Task]:
    stop_event = asyncio.Event()
    task = asyncio.create_task(_job_scheduler(stop_event))
    return stop_event, task


async def stop_job_scheduler(stop_event: asyncio.Event, task: asyncio.Task):
    stop_event.set()
    try:
        await task
    except Exception:
        pass


def create_lifespan_handler():
    """创建应用生命周期管理器"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with kdb_mcp_http.lifespan(app):
            """应用生命周期管理"""
            # 启动时初始化
            await initialize_system()
            stop_event, scheduler_task = start_job_scheduler()
            yield
            # 关闭时清理
            await stop_job_scheduler(stop_event, scheduler_task)
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
        routes=[*kdb_mcp_http.routes],
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

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        whitelist = {
            "/api/health",
            "/api/user/login",
            "/api/user/register",
            "/api/files/workspace",
            "/api/files/workspace/download",
            "/api/files/workspace/preview",
            "/api/files/logs",
            "/api/files/logs/download",
            "/api/files/logs/preview",
        }
        if path.startswith("/api") and path not in whitelist:
            auth = request.headers.get("Authorization", "")
            if not auth.lower().startswith("bearer "):
                error_response = await Response.error(
                    code=401, message="未授权", error_detail="missing bearer token"
                )
                return JSONResponse(
                    status_code=401, content=error_response.model_dump()
                )
            token = auth.split(" ", 1)[1].strip()
            try:
                claims = parse_access_token(token)
                request.state.user_claims = claims
            except Exception as e:
                if isinstance(e, SageHTTPException):
                    error_response = await Response.error(
                        code=e.status_code,
                        message=e.detail,
                        error_detail=e.error_detail,
                    )
                    return JSONResponse(
                        status_code=e.status_code, content=error_response.model_dump()
                    )
                error_response = await Response.error(
                    code=401, message="Token非法", error_detail=str(e)
                )
                return JSONResponse(
                    status_code=401, content=error_response.model_dump()
                )
        response = await call_next(request)
        return response

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
    app.include_router(router.user_router)

    return app


def start_server(app):
    """启动服务器"""
    cfg = get_startup_config()
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
                app, host="0.0.0.0", port=cfg.port, log_level="debug", reload=False
            )
    else:
        uvicorn.run(app, host="0.0.0.0", port=cfg.port, log_level="debug", reload=False)


def main():
    """主函数 - 启动Sage Stream Service"""
    try:
        # 1) 处理启动参数
        init_startup_config()
        # 创建FastAPI应用
        app = create_fastapi_app()
        # 启动服务器
        start_server(app)

    except Exception as e:
        logger.error(f"服务启动失败: {e}")
        raise


if __name__ == "__main__":
    main()
