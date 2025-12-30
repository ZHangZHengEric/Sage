from fastapi import FastAPI
from core.middleware import register_middlewares
from core.exceptions import register_exception_handlers
import router
import mcp_server
from lifespan import app_lifespan

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
    router.register_routes(app)

    # 注册 MCP 路由
    mcp_server.register_routes(app)
    return app
