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

本页面向 **`app/v2/server`**，不是旧版服务端。请求结构、响应模型和状态码以运行服务的 `/docs` 或 `/openapi.json` 为准。

## 身份认证

`POST /api/auth/login` 接收 JSON `username`、`password`，返回 `data.access_token` 并设置 `sage_server_v2` cookie。受保护路由由服务端依赖层解析认证身份，管理员路由要求管理员权限。

## A2A 与 API Key

`/api/keys` 管理绑定 Agent 的机器凭据，请妥善保管返回的密钥。入站 `/a2a/v1` 和 Agent Card 路由要求安装 `a2a` extra（已包含在 `server` 中），使用 Bearer API Key，而非用户 JWT。Card 和任务读取要求 `a2a:read`，发送与取消要求 `a2a:invoke`。同一来源服务多个用户，因此 Card 也需要鉴权。出站 peer 通过 `/api/a2a-agents` 管理，出站调用不要求安装入站 SDK extra。

## 对话与回放

`POST /api/agent` 接收 AG-UI `RunAgentInput`，返回 `text/event-stream`。新对话通过 `forwardedProps.agentId` 选择 Agent，首次 Run 会固定该 thread 的 Agent。重连已接受的 Run 时发送 `Last-Event-ID`。回放读取权威 Session 事件，不使用 Redis 保存另一份事件流。

`session_id` 是统一的会话身份：传入时原样使用，省略时由 Sage 生成。`threadId` 是兼容别名，两者同时传入时必须一致。SSE 生命周期帧和结果响应返回最终使用的 `session_id`，后续请求复用该值。归属绑定 tenant、Agent 和 Session；全局 ID 已被其他归属占用时拒绝请求。旧哈希会话通过兼容映射访问，并返回原持久化 ID。

```json
{
  "session_id": "example-thread",
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

智能体列表页使用 `GET /api/agents/summary` 获取当前用户的摘要；管理员使用 `GET /api/admin/agents` 一次获取全部用户的摘要和归属。摘要包含 `id`、`name`、`description`、`model_id`、`model_name`、`tool_count`、`skill_count`，管理员结果另外包含 `user_id`、`username`。完整配置仍通过智能体详情接口读取。

## 外部运行与工作区

外部接口使用绑定目标的 `Authorization: Bearer <API Key>`，并要求 `SAGE-TENANT-ID` 请求头。读取要求 `a2a:read`，写入与执行要求 `a2a:invoke`，交互回复要求 `a2a:approve`。服务端核对密钥绑定、目标归属与权限；租户、会话或运行 ID 本身不是凭据。

`PUT /api/agents/{agent_id}/workspace/files` 导入 `{directory, files}`，文件内容使用 base64；只创建缺失文件，相同内容可重复导入，冲突返回 409。上限为 256 个文件、单文件 4 MiB、总计 16 MiB。删除通过同一路径的 DELETE 操作，受工作区空闲状态与路径检查约束。

`POST /api/agents/{agent_id}/runs?workspace_path=...` 接收 AG-UI 请求，并可用 `runtimeContext` 为本次运行提供上下文，不改写共享配置。运行读取、回复、取消和文件下载都以准确的 `thread_id`、`run_id` 定位，并核对归属；交互回复还需匹配交互 ID 和预期修订号。

文件下载读取运行绑定的工作目录快照，上限 32 MiB、512 项；旧运行目录已被同会话的新运行替代时返回 409，打包期间文件变化可能返回 503。调用方应核对产物与运行身份；Sage 不解释下游业务清单或执行客户项目构建。

## 指导与 Skills 同步

`PUT /api/agents/{agent_id}/guidance` 的 ZIP 上传模式使用 multipart `prompt` 与 `files`，接受 1–32 个完整 Skill ZIP，逐项校验并返回结果。该上传分支不要求用户身份，因此只能暴露给受信任的调用方；不要将它与受 Bearer Key 保护的外部 Run 接口混淆。

`sync_bound=true` 用于同步既有绑定，要求已登录的配置所有者，不能同时传入 prompt 或 ZIP。同步保留模型、工具与执行策略；配置与资源实际生效方式以对应 HTTP schema 和宿主实现为准。

[机器凭据校验](../../../app/v2/server/identity/external.py) · [运行与工作区路由](../../../app/v2/server/routers/conversations.py) · [同步路由](../../../app/v2/server/routers/agents.py)

## 路由清单

以下清单对应当前注册的路由源码。Jaeger 路由按宿主配置启用，入站 A2A 路由取决于 SDK extra。完整 schema 请使用 OpenAPI，此清单不替代客户端 SDK。

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
| `GET` | `/api/admin/a2a-agents` | `admin` |
| `GET` | `/api/admin/agents` | `admin` |
| `GET` | `/api/admin/mcp` | `admin` |
| `GET` | `/api/admin/models` | `admin` |
| `GET` | `/api/admin/skills` | `admin` |
| `GET` | `/api/admin/threads` | `admin` |
| `GET` | `/api/admin/threads/{thread_id}` | `admin` |
| `GET` | `/api/admin/threads/{thread_id}/events` | `admin` |
| `GET` | `/api/admin/users` | `admin` |
| `GET` | `/api/agents` | `agents` |
| `POST` | `/api/agents` | `agents` |
| `GET` | `/api/agents/editor-resources` | `agents` |
| `GET` | `/api/agents/summary` | `agents` |
| `DELETE` | `/api/agents/{agent_id}` | `agents` |
| `GET` | `/api/agents/{agent_id}` | `agents` |
| `PUT` | `/api/agents/{agent_id}` | `agents` |
| `PUT` | `/api/agents/{agent_id}/guidance` | `agents` |
| `GET` | `/api/agents/{agent_id}/skills` | `agents` |
| `PUT` | `/api/agents/{agent_id}/skills` | `agents` |
| `GET` | `/api/plugins` | `agents` |
| `GET` | `/api/plugins/server` | `agents` |
| `PUT` | `/api/plugins/server` | `agents` |
| `GET` | `/api/tools` | `agents` |
| `GET` | `/api/tools/options` | `agents` |
| `GET` | `/api/keys` | `api_keys` |
| `POST` | `/api/keys` | `api_keys` |
| `DELETE` | `/api/keys/{key_id}` | `api_keys` |
| `GET` | `/api/auth/execution-policy` | `auth` |
| `PUT` | `/api/auth/execution-policy` | `auth` |
| `POST` | `/api/auth/login` | `auth` |
| `POST` | `/api/auth/logout` | `auth` |
| `POST` | `/api/auth/register` | `auth` |
| `GET` | `/api/auth/session` | `auth` |
| `POST` | `/api/agent` | `conversations` |
| `POST` | `/api/agent-package` | `conversations` |
| `POST` | `/api/agents/{agent_id}/runs` | `conversations` |
| `GET` | `/api/agents/{agent_id}/runs/{thread_id}/{run_id}` | `conversations` |
| `POST` | `/api/agents/{agent_id}/runs/{thread_id}/{run_id}/cancel` | `conversations` |
| `GET` | `/api/agents/{agent_id}/runs/{thread_id}/{run_id}/files` | `conversations` |
| `POST` | `/api/agents/{agent_id}/runs/{thread_id}/{run_id}/reply` | `conversations` |
| `DELETE` | `/api/agents/{agent_id}/sessions/{session_id}` | `conversations` |
| `DELETE` | `/api/agents/{agent_id}/workspace/files` | `conversations` |
| `PUT` | `/api/agents/{agent_id}/workspace/files` | `conversations` |
| `GET` | `/api/approvals` | `conversations` |
| `POST` | `/api/approvals/{run_id}/decisions` | `conversations` |
| `GET` | `/api/threads` | `conversations` |
| `DELETE` | `/api/threads/{thread_id}` | `conversations` |
| `GET` | `/api/threads/{thread_id}` | `conversations` |
| `POST` | `/api/threads/{thread_id}/cancel` | `conversations` |
| `GET` | `/api/threads/{thread_id}/download` | `conversations` |
| `GET` | `/api/threads/{thread_id}/events` | `conversations` |
| `GET` | `/api/threads/{thread_id}/package` | `conversations` |
| `GET` | `/api/threads/{thread_id}/result` | `conversations` |
| `POST` | `/api/threads/{thread_id}/resume` | `conversations` |
| `POST` | `/api/threads/{thread_id}/steer` | `conversations` |
| `GET` | `/api/workspace/download` | `files` |
| `DELETE` | `/api/workspace/files` | `files` |
| `GET` | `/api/workspace/files` | `files` |
| `GET` | `/active` | `health` |
| `GET` | `/health` | `health` |
| `GET` | `/api/im/connections` | `im` |
| `POST` | `/api/im/connections` | `im` |
| `DELETE` | `/api/im/connections/{cid}` | `im` |
| `GET` | `/api/im/connections/{cid}` | `im` |
| `PATCH` | `/api/im/connections/{cid}` | `im` |
| `GET` | `/api/im/connections/{cid}/deliveries` | `im` |
| `POST` | `/api/im/connections/{cid}/pairings` | `im` |
| `GET` | `/api/im/connections/{cid}/status` | `im` |
| `POST` | `/api/im/connections/{cid}/test` | `im` |
| `DELETE` | `/api/im/deliveries/{delivery_id}` | `im` |
| `POST` | `/api/im/deliveries/{delivery_id}/retries` | `im` |
| `GET` | `/api/im/plugins` | `im` |
| `POST` | `/api/im/webhooks/{cid}` | `im` |
| `GET` | `/api/mcp` | `mcp` |
| `POST` | `/api/mcp` | `mcp` |
| `DELETE` | `/api/mcp/{name}` | `mcp` |
| `PUT` | `/api/mcp/{name}` | `mcp` |
| `POST` | `/api/mcp/{name}/refresh` | `mcp` |
| `GET` | `/api/models` | `models` |
| `POST` | `/api/models` | `models` |
| `POST` | `/api/models/probe` | `models` |
| `DELETE` | `/api/models/{model_id}` | `models` |
| `GET` | `/api/models/{model_id}` | `models` |
| `GET` | `/api/observability/console` | `observability` |
| `GET` | `/api/observability/jaeger` | `observability` |
| `GET` | `/api/observability/jaeger/auth` | `observability` |
| `GET` | `/api/observability/jaeger/login` | `observability` |
| `GET/POST/PUT/PATCH/DELETE/OPTIONS/HEAD` | `/api/observability/jaeger/{full_path:path}` | `observability` |
| `GET` | `/api/observability/performance` | `observability` |
| `GET` | `/api/observability/services` | `observability` |
| `GET` | `/api/observability/trace-spans` | `observability` |
| `GET` | `/api/observability/trace-spans/{span_id}` | `observability` |
| `GET` | `/api/observability/traces/summary` | `observability` |
| `GET` | `/api/observability/traces/{trace_id}/spans` | `observability` |
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
| `POST` | `/api/skill-import-previews` | `skills` |
| `POST` | `/api/skill-imports` | `skills` |
| `GET` | `/api/skills` | `skills` |
| `POST` | `/api/skills` | `skills` |
| `POST` | `/api/skills/upload` | `skills` |
| `DELETE` | `/api/skills/{skill_id}` | `skills` |
| `GET` | `/api/skills/{skill_id}` | `skills` |
| `PUT` | `/api/skills/{skill_id}` | `skills` |
| `GET` | `/api/skills/{skill_id}/files` | `skills` |
| `GET` | `/api/skills/{skill_id}/files/{path:path}` | `skills` |
| `PUT` | `/api/workspace/skills/{name}` | `skills` |

宿主基础设施还提供 `GET /livez`、`GET /readyz` 和 `GET /metrics`，这些不展示在 OpenAPI 中。就绪检查会探测宿主数据库和应用状态。

成功与失败的 JSON 都包含 `request_id`，服务端同时返回 `X-Request-ID`。流式响应使用 AG-UI 事件格式。

[路由源码](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/routers/) · [服务端启动](../applications/WEB.md)

### 工具目录详情

`GET /api/tools` 每项除了 `name`、`category`、`source`、`default` 和 `approval_key`，还返回 `description`、`input_schema`、`side_effect_level`、`requires_approval`。这些字段直接来自当前可发现的 `ToolDefinition`，用于只读目录和详情；读取目录不会执行工具。`default` 表示新智能体初始工具集，批准声明也不替代智能体当前的授权和执行策略。
