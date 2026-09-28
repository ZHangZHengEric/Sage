"""Run an independent AnyTool MCP server: python -m mcp_servers.anytool CONFIG.json."""
import argparse
import asyncio
import json
from pathlib import Path

from mcp.server.stdio import stdio_server

from .anytool_server import build_anytool_server


async def serve(config):
    server = build_anytool_server(config.get("name", "AnyTool"), config)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    asyncio.run(serve(json.loads(args.config.read_text())))


if __name__ == "__main__":
    main()
