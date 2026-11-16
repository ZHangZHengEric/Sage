"""Keyless search/fetch through Sage's v2 MCP catalog and executor with Keenable.

Run from the repository root: python -m examples.v2.keenable_search
This is an explicit host-side tool call demo, without a model or agent loop.
Set KEENABLE_API_KEY to use the keyed endpoint instead of the public one.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, cast
from uuid import uuid4

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import SecretStr

from sagents.v2.contracts.principals import ActorRef, PrincipalType, RequestContext
from sagents.v2.tool import McpServerConfig, McpToolPlugin, ToolCall

PUBLIC_ENDPOINT = "https://api.keenable.ai/mcp-public"
KEYED_ENDPOINT = "https://api.keenable.ai/mcp"
API_KEY_HEADER = "X-API-Key"
USER_AGENT = "Sage/1.1.0 (Keenable Search MCP example)"
SEARCH_TOOL = "mcp_keenable_search_web_pages"
FETCH_TOOL = "mcp_keenable_fetch_page_content"


@asynccontextmanager
async def keenable_session(config: McpServerConfig):
    """Use the SDK transport with a project identity and the optional key."""
    headers = {"User-Agent": USER_AGENT}
    if config.api_key is not None:
        headers[API_KEY_HEADER] = config.api_key.get_secret_value()
    async with streamablehttp_client(
        cast('str', config.url),
        headers=headers,
        timeout=config.timeout_seconds,
        sse_read_timeout=config.timeout_seconds,
    ) as (read, write, _), ClientSession(read, write) as session:
        await asyncio.wait_for(session.initialize(), config.timeout_seconds)
        yield session


def create_plugin(api_key: str | None = None) -> McpToolPlugin:
    """Public endpoint without a key; keyed endpoint when one is supplied."""
    key = SecretStr(api_key) if api_key else None
    return McpToolPlugin(
        (McpServerConfig(
            name="keenable", protocol="streamable_http",
            url=KEYED_ENDPOINT if key else PUBLIC_ENDPOINT, api_key=key,
        ),),
        session_factory=keenable_session,
    )


def _with_session(definition: Any, arguments: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Pass session_id only when the advertised tool schema declares it."""
    properties = (definition.input_schema or {}).get("properties") or {}
    if "session_id" in properties:
        return {**arguments, "session_id": session_id}
    return arguments


async def run(query: str, fetch_url: str | None = None, api_key: str | None = None) -> None:
    plugin = create_plugin(api_key)
    run_id = str(uuid4())
    # Tool-level grouping id from Keenable's schema; unrelated to MCP transport sessions.
    session_id = str(uuid4())
    context = RequestContext(actor=ActorRef(
        principal_id="keenable-example", principal_type=PrincipalType.USER,
    ))
    try:
        tools = {tool.name: tool for tool in await plugin.list_tools(run_id=run_id)}
        requests = [(SEARCH_TOOL, {"query": query})]
        if fetch_url:
            requests.append((FETCH_TOOL, {"url": fetch_url}))
        for name, arguments in requests:
            if name not in tools:
                raise RuntimeError(f"Keenable did not advertise {name}")
            result = await plugin.execute(ToolCall(
                tool_call_id=str(uuid4()), tool_name=name,
                arguments=_with_session(tools[name], arguments, session_id),
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
    parser.add_argument("--fetch-url", help="Also read this HTTP(S) URL as markdown")
    args = parser.parse_args()
    asyncio.run(run(args.query, args.fetch_url, os.environ.get("KEENABLE_API_KEY") or None))


if __name__ == "__main__":
    main()
