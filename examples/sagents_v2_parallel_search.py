"""Keyless search/fetch through Sage's v2 MCP catalog and executor.

Run from the repository root: python -m examples.sagents_v2_parallel_search
This is an explicit host-side tool call demo, without a model or agent loop.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.tool import McpServerConfig, McpToolPlugin, ToolCall

ENDPOINT = "https://search.parallel.ai/mcp"
USER_AGENT = "Sage/1.1.0 (Parallel Search MCP example)"


@asynccontextmanager
async def parallel_session(config: McpServerConfig):
    """Use the SDK transport with a project identity and no credentials."""
    async with streamablehttp_client(
        config.url,
        headers={"User-Agent": USER_AGENT},
        timeout=config.timeout_seconds,
        sse_read_timeout=config.timeout_seconds,
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), config.timeout_seconds)
            yield session


def create_plugin() -> McpToolPlugin:
    return McpToolPlugin(
        (McpServerConfig(
            name="parallel", protocol="streamable_http", url=ENDPOINT,
        ),),
        session_factory=parallel_session,
    )


async def run(query: str, fetch_url: str | None = None) -> None:
    plugin = create_plugin()
    run_id = str(uuid4())
    session_id = str(uuid4())
    context = RequestContext(actor=ActorRef(
        principal_id="parallel-example", principal_type=PrincipalType.USER,
    ))
    try:
        tools = {tool.name: tool for tool in await plugin.list_tools(run_id=run_id)}
        requests = [("mcp_parallel_web_search", {
            "objective": query, "search_queries": [query], "session_id": session_id,
        })]
        if fetch_url:
            requests.append(("mcp_parallel_web_fetch", {
                "urls": [fetch_url], "session_id": session_id,
            }))
        for name, arguments in requests:
            if name not in tools:
                raise RuntimeError(f"Parallel did not advertise {name}")
            result = await plugin.execute(ToolCall(
                tool_call_id=str(uuid4()), tool_name=name, arguments=arguments,
                operation_id=str(uuid4()), idempotency_key=str(uuid4()),
                owner_run_id=run_id,
            ), context)
            print(result.model_dump_json(indent=2))
            if result.error:
                raise RuntimeError(result.error.message)
    finally:
        await plugin.release_run(run_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", default="Python asyncio TaskGroup documentation")
    parser.add_argument("--fetch-url", help="Also extract excerpts from this HTTP(S) URL")
    args = parser.parse_args()
    asyncio.run(run(args.query, args.fetch_url))


if __name__ == "__main__":
    main()
