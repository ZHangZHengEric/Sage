# Keyless Parallel Search MCP with SAgents v2

[Parallel Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp)
provides `web_search` and `web_fetch` at `https://search.parallel.ai/mcp`.
The anonymous free tier needs no Parallel API key and has rate limits; it is
intended for exploration and light use.

From a Sage checkout, install with Python 3.12+ in a fresh environment:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m examples.sagents_v2_parallel_search "Python asyncio TaskGroup documentation"
python -m examples.sagents_v2_parallel_search "Python asyncio TaskGroup documentation" \
  --fetch-url https://docs.python.org/3/library/asyncio-task.html
```

The example discovers tools through `McpToolPlugin.list_tools`, selects their
Sage names (`mcp_parallel_web_search` and `mcp_parallel_web_fetch`), and calls
`McpToolPlugin.execute`. It prints Sage's `ToolExecutionResult` JSON, including
source URLs and excerpts, and exits with an error if the tool reports failure.
It uses Streamable HTTP, sends a Sage User-Agent, closes each SDK session, and
releases the plugin's per-run state on exit. Search and fetch share one generated
conversation identifier. It reads no saved settings, environment keys, or tokens.

This is an explicit host-side catalog/executor demo; it does not run a model or
an Agent. Running the command authorizes its search query and optional fetch URL.
Calling the executor directly does not invoke Sage's Agent policy/approval flow.
For an embedded Agent, register the plugin as both catalog and executor using
`builder.with_tool_provider(plugin, plugin)`, allowlist the discovered tool names,
and supply the actor scope and approval flow described in
[Tools, Skills and MCP](../docs/en/MCP_SERVERS.md#discover-authorize-call-and-close).
The example does not change any existing provider or saved connection.
