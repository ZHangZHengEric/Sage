---
layout: default
title: Tools, Skills and MCP
nav_order: 6
lang: en
ref: v2-MCP_SERVERS
---

{% include lang_switcher.html %}

# Tools, Skills and MCP

| Capability | Purpose |
| --- | --- |
| Built-in tools | File, process, planning, and other runtime operations exposed through the v2 catalog/executor. |
| Skills | Reusable instructions and resources, discovered and loaded through Skill providers. |
| MCP | External servers whose discovered tools join the host's tool catalog. |

## Desktop

Configure tools and Skills on the Agent, and add MCP connections in Settings. Enabled connections are discovered during catalog/runtime composition. Discovery failures are reported rather than silently ignored. `load_skill` activates selected resources; selecting a Skill alone does not mean its full content is already in model context.

## Server

Use model/Agent/Skill/MCP management in the web client. Skills support ZIP upload and per-Agent selection. MCP management uses `/api/mcp`; refresh a connection to rediscover tools. See [HTTP API](api/HTTP_API_REFERENCE.md).

Server accepts only `sse` and `streamable_http` MCP transports; it rejects tenant `stdio` commands. Desktop may use stdio. Skill catalog descriptions are complete, including multiline YAML; only loaded active Skill content has a separate token budget. The full catalog still counts toward the overall context budget.

## Embedded hosts

The minimal quick start intentionally has no file or shell tools. Official tools require an `OfficialToolRuntime` with explicit workspace and sandbox bindings. Host-provided tool execution must validate grants at the resource boundary. An in-memory manifest does not authorize access to arbitrary host files.

Use the [integration manual](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md) to select catalogs, executors, Skill sources, and policy providers. The `mcp_servers/` directory also contains integrations used by older applications; their presence does not enable them in v2 automatically.

## Authenticated remote MCP in v2

This guide describes the current `sagents/v2` and `app/v2` source paths, which require Python 3.12+. Use the instructions for your host; a v1 configuration or legacy Desktop installer does not establish support for these v2 entry points.

### Connection and credentials

For a Bearer-authenticated server, use these values in Desktop's Settings → MCP connection dialog or Server's MCP management:

| Setting | Example | Meaning |
| --- | --- | --- |
| Name | `remote` | A name for this connection. |
| Protocol | `streamable_http` | Streamable HTTP, rather than stdio or SSE. |
| URL | `https://mcp.example.com/mcp` | Replace with the server's actual endpoint. |
| API key / `api_key` | Your token, without `Bearer ` | The SDK session adds the `Authorization: Bearer ` prefix. This is the MCP service credential, not the model API key. |

Server uses `url` in `/api/mcp` requests; Desktop's connection payload uses `streamable_http_url`. Let each host's interface construct its own payload. The current bridge accepts an API key for Bearer authentication; this is not an arbitrary-header or OAuth configuration example.

For an embedded host, read the token explicitly from the process environment:

```python
import os
from sagents.v2.tool import McpServerConfig, McpToolPlugin

key = os.environ["REMOTE_MCP_API_KEY"]
if not key.strip():
    raise ValueError("REMOTE_MCP_API_KEY must not be empty")

mcp = McpToolPlugin((McpServerConfig(
    name="remote",
    protocol="streamable_http",
    url="https://mcp.example.com/mcp",
    api_key=key,
),))
```

This constructs the provider without contacting the server. Register it as both catalog and executor with your v2 builder's `with_tool_provider(mcp, mcp)` before building the application. See the integration manual for combining providers. `${REMOTE_MCP_API_KEY}` in an API-key field is a literal value, not automatic environment expansion. Keep tokens out of committed configuration, screenshots, and logs.

### Discover, authorize, call, and close

1. **Discover:** Enable the connection and inspect the tools actually returned by the catalog, including their Sage names and input schemas. Server's refresh action rediscovers tools. A saved connection or a successful tool listing does not prove that a tool call succeeds.
2. **Authorize:** For embedded Agents, include the discovered names in the Agent's `tools` allowlist. The host must also give the actor the required `tool.external_side_effect` scope. The MCP bridge marks every external tool as `WRITE` and `requires_approval=True`, even if its name or annotations suggest a read-only search. The default `CONFIGURED` policy asks for approval after scope checks; a host's selected strategy and approval memory can change that interaction. A service API key does not replace Sage authorization.
3. **Call:** Review the selected tool and arguments in the host's approval flow, then inspect its result. Distinguish discovery/authentication failures from a tool response with `isError`. A timeout, cancellation, or lost response can leave the remote effect unknown; check the remote result before considering a retry.
4. **Close:** The default bridge opens a short-lived SDK session for discovery or one call and closes its context afterward. Keep `await application.close()` in your embedded host's shutdown path. Disable or remove the connection to stop future use, and cancel an active Run separately; closing a local session does not revoke the service's API key or prove that remote work stopped.
