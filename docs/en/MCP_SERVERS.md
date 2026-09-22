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

## Embedded hosts

The minimal quick start intentionally has no file or shell tools. Official tools require an `OfficialToolRuntime` with explicit workspace and sandbox bindings. Host-provided tool execution must validate grants at the resource boundary. An in-memory manifest does not authorize access to arbitrary host files.

Use the [integration manual](https://github.com/ZHangZHengEric/Sage/blob/main/sagents/v2/使用手册.md) to select catalogs, executors, Skill sources, and policy providers. The `mcp_servers/` directory also contains integrations used by older applications; their presence does not enable them in v2 automatically.
