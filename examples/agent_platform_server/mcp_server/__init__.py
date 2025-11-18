from .knwoledge_base import kdb_mcp
from contextlib import asynccontextmanager
from starlette.routing import BaseRoute


mcp_http_app = kdb_mcp.http_app(path="/mcp/kdb")


def get_mcp_routes() -> list[BaseRoute]:
    return list(mcp_http_app.routes)


@asynccontextmanager
async def mcp_lifespan(app):
    async with mcp_http_app.lifespan(app):
        yield

__all__ = [
    "get_mcp_routes",
    "mcp_lifespan",
]
