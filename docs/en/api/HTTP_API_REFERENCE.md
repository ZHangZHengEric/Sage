---
layout: default
title: Server HTTP API
nav_order: 2
lang: en
ref: v2-api-HTTP_API_REFERENCE
parent: API
---

{% include lang_switcher.html %}

# Server HTTP API

This page describes **`app/server_v2`**, not the legacy server. Open the running server's `/docs` or `/openapi.json` for request schemas, response models, and status codes.

## Authentication

`POST /api/auth/login` accepts JSON `username` and `password`. It returns `data.access_token` and sets the `sage_server_v2` cookie. Protected routes accept the authenticated identity through the server's dependency layer. Admin routes require an administrator.

## Chat and replay

`POST /api/agent` accepts AG-UI `RunAgentInput` and returns `text/event-stream`. Specify the Agent for a new conversation through `forwardedProps.agentId`; the first Run binds the Agent to the thread. Send `Last-Event-ID` when reconnecting to an accepted Run. Replay comes from canonical Session events; it is not stored in Redis.

```json
{
  "threadId": "example-thread",
  "runId": "example-run",
  "state": {},
  "messages": [{"id": "message-1", "role": "user", "content": "Hello"}],
  "tools": [],
  "context": [],
  "forwardedProps": {"agentId": "your-agent-id"}
}
```

Replace IDs appropriately. A new logical request needs a new Run ID; reconnection must not create another logical task.

## Route inventory

The inventory below follows the registered router source. Jaeger routes are conditional on the corresponding host configuration. Use OpenAPI for full schemas rather than treating this list as a client SDK.

| Method | Path | Router |
| --- | --- | --- |
| `GET` | `/api/admin/users` | `admin` |
| `GET` | `/api/admin/threads` | `admin` |
| `GET` | `/api/admin/models` | `admin` |
| `GET` | `/api/admin/threads/{thread_id}/events` | `admin` |
| `POST` | `/api/agent` | `agent` |
| `GET` | `/api/tools` | `agents` |
| `GET` | `/api/agents` | `agents` |
| `POST` | `/api/agents` | `agents` |
| `GET` | `/api/agents/{agent_id}` | `agents` |
| `PUT` | `/api/agents/{agent_id}` | `agents` |
| `DELETE` | `/api/agents/{agent_id}` | `agents` |
| `POST` | `/api/auth/register` | `auth` |
| `POST` | `/api/auth/login` | `auth` |
| `GET` | `/api/auth/session` | `auth` |
| `POST` | `/api/auth/logout` | `auth` |
| `GET` | `/health` | `health` |
| `GET` | `/active` | `health` |
| `GET` | `/api/mcp` | `mcp` |
| `POST` | `/api/mcp` | `mcp` |
| `PUT` | `/api/mcp/{name}` | `mcp` |
| `DELETE` | `/api/mcp/{name}` | `mcp` |
| `POST` | `/api/mcp/{name}/refresh` | `mcp` |
| `GET` | `/api/models` | `models` |
| `POST` | `/api/models` | `models` |
| `DELETE` | `/api/models/{model_id}` | `models` |
| `GET` | `/api/observability/jaeger/login` | `observability` |
| `GET` | `/api/observability/jaeger/auth` | `observability` |
| `GET` | `/api/observability/jaeger` | `observability` |
| `GET/POST/PUT/PATCH/DELETE/OPTIONS/HEAD` | `/api/observability/jaeger/{full_path:path}` | `observability` |
| `GET` | `/api/agent-packages/schema` | `packages` |
| `GET` | `/api/agent-packages/capacity` | `packages` |
| `GET` | `/api/agent-packages/resources` | `packages` |
| `GET` | `/api/agent-packages/template` | `packages` |
| `GET` | `/api/agent-packages` | `packages` |
| `POST` | `/api/agent-packages/validate` | `packages` |
| `POST` | `/api/agent-packages` | `packages` |
| `GET` | `/api/agent-packages/runs` | `packages` |
| `POST` | `/api/agent-packages/runs` | `packages` |
| `GET` | `/api/agent-packages/runs/{operation}` | `packages` |
| `GET` | `/api/agent-packages/runs/{operation}/events` | `packages` |
| `POST` | `/api/agent-packages/runs/{operation}/control` | `packages` |
| `GET` | `/api/agent-packages/{ref}` | `packages` |
| `POST` | `/api/agent-packages/{ref}/activate` | `packages` |
| `POST` | `/api/agent-packages/{ref}/fork` | `packages` |
| `GET` | `/api/skills` | `skills` |
| `POST` | `/api/skills/upload` | `skills` |
| `POST` | `/api/skills` | `skills` |
| `GET` | `/api/skills/{skill_id}` | `skills` |
| `PUT` | `/api/skills/{skill_id}` | `skills` |
| `DELETE` | `/api/skills/{skill_id}` | `skills` |
| `GET` | `/api/agents/{agent_id}/skills` | `skills` |
| `PUT` | `/api/agents/{agent_id}/skills` | `skills` |
| `PUT` | `/api/workspace/skills/{name}` | `skills` |
| `GET` | `/api/threads` | `threads` |
| `GET` | `/api/threads/{thread_id}/events` | `threads` |
| `DELETE` | `/api/threads/{thread_id}` | `threads` |

Host infrastructure also exposes `GET /livez`, `GET /readyz`, and `GET /metrics` outside OpenAPI. Readiness probes the registered resources.

Success and error JSON carry `request_id`; the server also returns `X-Request-ID`. Streaming responses follow AG-UI event framing.

[Router source](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/api/routers/) · [Server setup](../applications/WEB.md)
