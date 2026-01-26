from fastapi import FastAPI

from .core.exceptions import register_exception_handlers
from .core.middleware import register_middlewares
from .lifespan import app_lifespan
from .routers import register_routes as register_chat_routes


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
