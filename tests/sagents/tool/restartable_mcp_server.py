import asyncio
import sys
from typing import Literal

from fastmcp import FastMCP


mcp = FastMCP("restartable-test-server")


@mcp.tool
async def echo(value: str) -> str:
    return value


@mcp.tool
async def delayed_echo(value: str, delay_seconds: float = 0.05) -> str:
    await asyncio.sleep(delay_seconds)
    return value


if __name__ == "__main__":
    transport: Literal["http", "sse"] = (
        "sse" if len(sys.argv) > 2 and sys.argv[2] == "sse" else "http"
    )
    mcp.run(
        transport=transport,
        host="127.0.0.1",
        port=int(sys.argv[1]),
        show_banner=False,
        log_level="warning",
    )
