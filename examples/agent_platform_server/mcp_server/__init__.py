from .knwoledge_base import kdb_mcp
from contextlib import AsyncExitStack, asynccontextmanager


def get_mcp_http_apps():
    return [kdb_mcp.http_app(path="/mcp/kdb")]


def get_mcp_routes():
    routes = []
    for app in get_mcp_http_apps():
        routes.extend(app.routes)
    return routes


@asynccontextmanager
async def mcp_lifespan(app):
    apps = get_mcp_http_apps()
    async with AsyncExitStack() as stack:
        for http_app in apps:
            await stack.enter_async_context(http_app.lifespan(app))
        yield


__all__ = [
    "get_mcp_http_apps",
    "get_mcp_routes",
    "mcp_lifespan",
]
