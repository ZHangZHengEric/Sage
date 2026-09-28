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

This page describes **`app/v2/server`**, not the legacy server. Open the running server's `/docs` or `/openapi.json` for request schemas, response models, and status codes.

## Authentication

`POST /api/auth/login` accepts JSON `username` and `password`. It returns `data.access_token` and sets the `sage_server_v2` cookie. Protected routes accept the authenticated identity through the server's dependency layer. Admin routes require an administrator.

## A2A and API keys

`/api/keys` manages Agent-bound machine credentials; keep the returned secret securely. Inbound `/a2a/v1` and the Agent Card routes require the `a2a` extra (included in `server-v2`) and a Bearer API Key, not a user JWT. Cards and task reads require `a2a:read`; sending and cancellation require `a2a:invoke`. Cards are authenticated because one origin serves multiple users. Manage outbound peers through `/api/a2a-agents`; outbound calls do not require the inbound SDK extra.

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

The inventory below follows the registered router source. Jaeger routes depend on host configuration; inbound A2A routes depend on the SDK extra. Use OpenAPI for full schemas rather than treating this list as a client SDK.

| Method | Path | Router |
| --- | --- | --- |
| `GET` | `/.well-known/agent-card.json` | `a2a` |
| `POST` | `/a2a/v1` | `a2a` |
| `GET` | `/a2a/v1/card` | `a2a` |
| `GET` | `/api/a2a-agents` | `a2a_agents` |
| `POST` | `/api/a2a-agents` | `a2a_agents` |
| `DELETE` | `/api/a2a-agents/{name}` | `a2a_agents` |
| `PUT` | `/api/a2a-agents/{name}` | `a2a_agents` |
| `POST` | `/api/a2a-agents/{name}/refresh` | `a2a_agents` |
| `GET` | `/api/admin/models` | `admin` |
| `GET` | `/api/admin/threads` | `admin` |
| `GET` | `/api/admin/threads/{thread_id}/events` | `admin` |
| `GET` | `/api/admin/users` | `admin` |
| `POST` | `/api/agent` | `agent` |
| `GET` | `/api/agents` | `agents` |
| `POST` | `/api/agents` | `agents` |
| `DELETE` | `/api/agents/{agent_id}` | `agents` |
| `GET` | `/api/agents/{agent_id}` | `agents` |
| `PUT` | `/api/agents/{agent_id}` | `agents` |
| `GET` | `/api/tools` | `agents` |
| `GET` | `/api/keys` | `api_keys` |
| `POST` | `/api/keys` | `api_keys` |
| `DELETE` | `/api/keys/{key_id}` | `api_keys` |
| `POST` | `/api/auth/login` | `auth` |
| `POST` | `/api/auth/logout` | `auth` |
| `POST` | `/api/auth/register` | `auth` |
| `GET` | `/api/auth/session` | `auth` |
| `GET` | `/active` | `health` |
| `GET` | `/health` | `health` |
| `GET` | `/api/mcp` | `mcp` |
| `POST` | `/api/mcp` | `mcp` |
| `DELETE` | `/api/mcp/{name}` | `mcp` |
| `PUT` | `/api/mcp/{name}` | `mcp` |
| `POST` | `/api/mcp/{name}/refresh` | `mcp` |
| `GET` | `/api/models` | `models` |
| `POST` | `/api/models` | `models` |
| `DELETE` | `/api/models/{model_id}` | `models` |
| `GET` | `/api/observability/jaeger` | `observability` |
| `GET` | `/api/observability/jaeger/auth` | `observability` |
| `GET` | `/api/observability/jaeger/login` | `observability` |
| `GET/POST/PUT/PATCH/DELETE/OPTIONS/HEAD` | `/api/observability/jaeger/{full_path:path}` | `observability` |
| `GET` | `/api/agent-packages` | `packages` |
| `POST` | `/api/agent-packages` | `packages` |
| `GET` | `/api/agent-packages/capacity` | `packages` |
| `GET` | `/api/agent-packages/resources` | `packages` |
| `GET` | `/api/agent-packages/runs` | `packages` |
| `POST` | `/api/agent-packages/runs` | `packages` |
| `GET` | `/api/agent-packages/runs/{operation}` | `packages` |
| `POST` | `/api/agent-packages/runs/{operation}/control` | `packages` |
| `GET` | `/api/agent-packages/runs/{operation}/events` | `packages` |
| `GET` | `/api/agent-packages/schema` | `packages` |
| `GET` | `/api/agent-packages/template` | `packages` |
| `POST` | `/api/agent-packages/validate` | `packages` |
| `GET` | `/api/agent-packages/{ref}` | `packages` |
| `POST` | `/api/agent-packages/{ref}/activate` | `packages` |
| `POST` | `/api/agent-packages/{ref}/fork` | `packages` |
| `GET` | `/api/agents/{agent_id}/skills` | `skills` |
| `PUT` | `/api/agents/{agent_id}/skills` | `skills` |
| `GET` | `/api/skills` | `skills` |
| `POST` | `/api/skills` | `skills` |
| `POST` | `/api/skills/upload` | `skills` |
| `DELETE` | `/api/skills/{skill_id}` | `skills` |
| `GET` | `/api/skills/{skill_id}` | `skills` |
| `PUT` | `/api/skills/{skill_id}` | `skills` |
| `PUT` | `/api/workspace/skills/{name}` | `skills` |
| `GET` | `/api/threads` | `threads` |
| `DELETE` | `/api/threads/{thread_id}` | `threads` |
| `GET` | `/api/threads/{thread_id}/events` | `threads` |
| `POST` | `/api/threads/{thread_id}/resume` | `threads` |

Host infrastructure also exposes `GET /livez`, `GET /readyz`, and `GET /metrics` outside OpenAPI. Readiness probes the host database and application state.

Success and error JSON carry `request_id`; the server also returns `X-Request-ID`. Streaming responses follow AG-UI event framing.

[Router source](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/routers/) · [Server setup](../applications/WEB.md)
