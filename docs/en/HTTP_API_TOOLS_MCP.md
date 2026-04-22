---
layout: default
title: Tools, skills, and MCP
parent: HTTP API Reference
nav_order: 5
description: "list/exec, skill dimensions, sync strategies, MCP CRUD/refresh"
lang: en
ref: http-api-tools
---

{% include lang_switcher.html %}

# Tools, skills, and MCP

Routers: `app/server/routers/tool.py`, `skill.py`, `mcp.py`. They line up with `availableTools` / `availableSkills` on agents and the runtime `ToolManager`.

## `/api/tools`

- `GET /api/tools?type=...` lists discoverable tools.
- `POST /api/tools/exec` is a direct execution path, useful for admin pages and tests. **Normal chat** still usually invokes tools through the agent session with injected context/permissions, even if the name and args match.

Failures may **not** always follow a clean `BaseResponse` success envelope—read the main doc’s error section.

## Skills and workspace sync (pick the right one)

| Scenario | Endpoint | Notes |
| --- | --- | --- |
| Copy one skill into one agent’s workspace (current user) | `POST /api/skills/sync-to-agent` (form `skill_name` + `agent_id`) | From the skill “marketplace” / user storage into a single workspace. |
| Propagate a set of skills to that agent for **all users** with workspaces | `POST /api/skills/sync-to-agent-workspaces` | Admin / bulk operation—mind permissions. |
| Materialize the agent’s configured skill set on disk for one user | `POST /api/skills/sync-workspace-skills` | `purge_extra=true` deletes *extra* files so the directory matches the config exactly. |

`GET /api/skills` supports `dimension` and optional `agent_id`. `GET /api/skills/agent-available?agent_id=` deduplicates and tags origin—good for pickers in the UI.

## `/api/mcp`

- `POST /api/mcp/add` with `MCPServerRequest` payload
- `GET /api/mcp/list`, `DELETE /api/mcp/{server_name}`, `POST /api/mcp/{server_name}/refresh`

Registering a server does not automatically make it callable in every chat: exposure still depends on the agent, permissions, and how MCP tools are merged for that session.

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
