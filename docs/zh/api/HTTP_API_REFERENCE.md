---
layout: default
title: Server HTTP API
nav_order: 2
lang: zh
ref: v2-api-HTTP_API_REFERENCE
parent: API
---

{% include lang_switcher.html %}

# Server HTTP API

本页面向 **`app/server_v2`**，不是旧版服务端。请求结构、响应模型和状态码以运行服务的 `/docs` 或 `/openapi.json` 为准。

## 身份认证

`POST /api/auth/login` 接收 JSON `username`、`password`，返回 `data.access_token` 并设置 `sage_server_v2` cookie。受保护路由由服务端依赖层解析认证身份，管理员路由要求管理员权限。

## 对话与回放

`POST /api/agent` 接收 AG-UI `RunAgentInput`，返回 `text/event-stream`。新对话通过 `forwardedProps.agentId` 选择 Agent，首次 Run 会固定该 thread 的 Agent。重连已接受的 Run 时发送 `Last-Event-ID`。回放读取权威 Session 事件，不使用 Redis 保存另一份事件流。

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

按实际情况替换 ID。新的逻辑请求使用新的 Run ID，重连不应创建另一个逻辑任务。

## 路由清单

以下清单对应当前注册的路由源码。Jaeger 路由按宿主配置启用。完整 schema 请使用 OpenAPI，此清单不替代客户端 SDK。

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

宿主基础设施还提供 `GET /livez`、`GET /readyz` 和 `GET /metrics`，这些不展示在 OpenAPI 中。Readiness 会检查已注册资源。

成功与失败的 JSON 都包含 `request_id`，服务端同时返回 `X-Request-ID`。流式响应使用 AG-UI 事件格式。

[路由源码](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/api/routers/) · [服务端启动](../applications/WEB.md)
