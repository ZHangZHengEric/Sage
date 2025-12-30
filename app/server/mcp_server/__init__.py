from contextlib import asynccontextmanager

from starlette.routing import BaseRoute

from .knwoledge_base import kdb_mcp
from fastapi import FastAPI

mcp_http_app = kdb_mcp.http_app(path="/mcp/kdb")

@asynccontextmanager
async def mcp_lifespan(app):
    async with mcp_http_app.lifespan(app):
        yield

__all__ = [
    "mcp_lifespan",
]


def register_routes(app: FastAPI, *, prefix: str = "") -> None:
    """
    将 MCP HTTP App 挂载到主 FastAPI 应用

    - 不复制 route 实例
    - 不污染主 app 路由表
    - 支持多 app / 多 worker / reload
    """

    if any(getattr(route, "app", None) is mcp_http_app for route in app.router.routes):
        return  # 已注册，防重复

    app.mount(prefix or "/", mcp_http_app)
