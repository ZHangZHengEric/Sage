---
layout: default
title: HTTP API 参考
nav_order: 8.6
description: "基于当前代码库的后端 HTTP API 参考"
lang: zh
ref: http-api-reference
---

{% include lang_switcher.html %}

# HTTP API 参考

这页只写当前代码库里真实存在的后端 HTTP 接口，按“先总览、再细节、最后示例”的方式组织。

旧版运行时 Python API 文档请看 [API 参考](API_REFERENCE.md)。如果你要接当前服务端，这页才是准的。

## 快速约定

| 项 | 说明 |
| --- | --- |
| Base URL | 例如 `http://127.0.0.1:8000` |
| 主响应格式 | 大多数接口返回 `BaseResponse[T]` |
| 流式接口 | `/api/chat`、`/api/stream`、`/api/web-stream`、`/api/stream/resume/*`、`/api/stream/active_sessions` 不返回 `BaseResponse` |
| 文件下载 | `/api/agent/{agent_id}/file_workspace/download` 返回文件流 |
| OAuth2 协议接口 | `/oauth2/*` 与 `/api/oauth2/*` 返回 OAuth2 标准响应 |
| 登录态 | 当前产品接口大多依赖服务端 session；只拿到 `access_token` 不等于能直接访问所有产品接口 |

标准响应包裹：

```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "timestamp": 1710000000.123
}
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `code` | 业务状态码，通常 `200` 表示成功 |
| `message` | 结果说明 |
| `data` | 具体返回数据 |
| `timestamp` | 服务端时间戳 |

## 接口速览

### 认证与用户

当前支持的部署模式是 `trusted_proxy` 和 `oauth`。下面列出的本地用户名密码接口目前只为兼容保留，不属于推荐部署路径；除非代码重新启用本地认证，否则会返回未启用错误。

| Method | Path | 请求 | 返回 `data` | 用途 |
| --- | --- | --- | --- | --- |
| POST | `/api/auth/register/send-code` | `{"email"}` | `{"expires_in","retry_after"}` | 注册前发邮箱验证码 |
| POST | `/api/auth/register` | `RegisterRequest` | `{"user_id"}` | 本地账号注册 |
| POST | `/api/auth/login` | `LoginRequest` | `{"access_token","refresh_token","expires_in"}` | 本地账号登录 |
| GET | `/api/auth/session` | 无 | `UserInfoResponse` | 读取当前登录用户与初始化状态 |
| GET | `/api/auth/providers` | 无 | provider 列表 | 获取上游登录提供方 |
| GET | `/api/auth/upstream/login/{provider_id}` | Query: `next`,`redirect_uri` | 302 | 发起指定 OAuth/OIDC 登录 |
| GET | `/api/auth/upstream/login` | Query: `next`,`redirect_uri` | 302 | 发起默认 OAuth/OIDC 登录 |
| GET | `/api/auth/upstream/callback/{provider_id}` | Query: `code`,`state` | 302 | OAuth/OIDC 登录回调 |
| POST | `/api/auth/logout` | 无 | `{}` | 退出登录 |
| GET | `/api/user/options` | 无 | 用户选项列表 | 用户下拉选择器 |
| POST | `/api/user/change-password` | `{"old_password","new_password"}` | `{}` | 修改当前用户密码 |
| GET | `/api/user/list` | Query: `page`,`page_size` | `{"items":[],"total":n}` | 管理员查看用户列表 |
| POST | `/api/user/add` | `UserAddRequest` | `{"user_id"}` | 管理员创建用户 |
| POST | `/api/user/delete` | `{"user_id"}` | `{}` | 管理员删除用户 |
| GET | `/api/user/config` | 无 | `{"config":{}}` | 获取当前用户配置 |
| POST | `/api/user/config` | `{"config":{}}` | `{"config":{}}` | 更新当前用户配置 |

兼容旧路径：

- `/api/user/register/send-code`
- `/api/user/register`
- `/api/user/login`
- `/api/user/auth-providers`
- `/api/user/oauth/login/{provider_id}`
- `/api/user/oauth/login`
- `/api/user/oauth/callback/{provider_id}`
- `/api/user/logout`
- `/api/user/check_login`

这几条和 `/api/auth/*` 对应接口语义基本一致，主要是兼容保留。

### OAuth2 授权服务器

| Method | Path | 请求 | 返回 | 用途 |
| --- | --- | --- | --- | --- |
| GET | `/.well-known/oauth-authorization-server` | 无 | OAuth2 metadata | 元数据发现 |
| GET | `/api/oauth2/metadata` | 无 | OAuth2 metadata | 元数据别名 |
| GET | `/oauth2/metadata` | 无 | OAuth2 metadata | 元数据别名 |
| GET | `/api/oauth2/authorize` | Query: OAuth2 authorize 参数 | 302 或错误体 | 发起授权码流程 |
| GET | `/oauth2/authorize` | Query: OAuth2 authorize 参数 | 302 或错误体 | 发起授权码流程 |
| POST | `/api/oauth2/token` | `application/x-www-form-urlencoded` | OAuth2 token 响应 | code 换 token / refresh token |
| POST | `/oauth2/token` | `application/x-www-form-urlencoded` | OAuth2 token 响应 | code 换 token / refresh token |
| GET/POST | `/api/oauth2/userinfo` | Bearer Token | userinfo payload | 读取当前 token 对应用户信息 |
| GET/POST | `/oauth2/userinfo` | Bearer Token | userinfo payload | 读取当前 token 对应用户信息 |

### Chat 与流式

| Method | Path | 请求 | 返回 | 用途 |
| --- | --- | --- | --- | --- |
| POST | `/api/chat` | `ChatRequest` | `text/plain` 流 | 必须指定 `agent_id` 的聊天流 |
| POST | `/api/stream` | `StreamRequest` | `text/plain` 流 | 更通用的聊天流 |
| POST | `/api/web-stream` | `StreamRequest` | `text/plain` 流 | 支持重连与活跃会话管理的 Web 流 |
| GET | `/api/stream/resume/{session_id}` | Query: `last_index` | `text/plain` 流 | 断线重连 |
| GET | `/api/stream/active_sessions` | 无 | `text/event-stream` | 订阅当前活跃流会话 |

### 会话与历史

| Method | Path | 请求 | 返回 `data` | 用途 |
| --- | --- | --- | --- | --- |
| GET | `/api/conversations` | Query: `page`,`page_size`,`user_id`,`search`,`agent_id`,`sort_by` | 分页会话列表 | 会话侧边栏 / 搜索 |
| GET | `/api/conversations/{session_id}/messages` | 无 | 消息列表 | 读取会话消息 |
| GET | `/api/share/conversations/{session_id}/messages` | 无 | 消息列表 | 分享页读取消息 |
| POST | `/api/conversations/{session_id}/title` | `{"title"}` | 更新结果 | 修改会话标题 |
| DELETE | `/api/conversations/{session_id}` | 无 | `{"session_id"}` | 删除会话 |
| POST | `/api/sessions/{session_id}/interrupt` | `{"message"}` 可省略 | 中断结果 | 中断正在运行的会话 |
| POST | `/api/sessions/{session_id}/tasks_status` | 无 | 任务状态 | 查询会话任务进度 |

### Agent

| Method | Path | 请求 | 返回 `data` | 用途 |
| --- | --- | --- | --- | --- |
| GET | `/api/agent/list` | 无 | `AgentConfigDTO[]` | 获取当前用户可见 Agent |
| GET | `/api/agent/template/default_system_prompt` | Query: `language` | `{"content"}` | 获取默认提示词模板 |
| POST | `/api/agent/create` | `AgentConfigDTO` | `{"agent_id"}` | 创建 Agent |
| GET | `/api/agent/{agent_id}` | 无 | `AgentConfigDTO` | 获取 Agent 详情 |
| PUT | `/api/agent/{agent_id}` | `AgentConfigDTO` | `{"agent_id"}` | 更新 Agent |
| DELETE | `/api/agent/{agent_id}` | 无 | `{"agent_id"}` | 删除 Agent |
| POST | `/api/agent/auto-generate` | `{"agent_description","available_tools"}` | 自动生成结果 | 自然语言生成 Agent 草稿 |
| POST | `/api/agent/system-prompt/optimize` | `{"original_prompt","optimization_goal"}` | 优化结果 | 优化 system prompt |
| GET | `/api/agent/{agent_id}/auth` | 无 | 授权用户列表 | 读取 Agent 授权 |
| POST | `/api/agent/{agent_id}/auth` | `{"user_ids":[]}` | `{}` | 更新 Agent 授权 |
| POST | `/api/agent/{agent_id}/file_workspace` | Query: `session_id` | 工作区文件列表 | 获取工作区文件 |
| GET | `/api/agent/{agent_id}/file_workspace/download` | Query: `file_path`,`session_id?` | 文件流 | 下载工作区文件 |
| DELETE | `/api/agent/{agent_id}/file_workspace/delete` | Query: `file_path`,`session_id?` | 删除结果 | 删除工作区文件 |

### 知识库

| Method | Path | 请求 | 返回 `data` | 用途 |
| --- | --- | --- | --- | --- |
| POST | `/api/knowledge-base/add` | `KdbAddRequest` | `{"kdb_id","user_id"}` | 创建知识库 |
| POST | `/api/knowledge-base/update` | `KdbUpdateRequest` | `{"success","user_id"}` | 更新知识库 |
| GET | `/api/knowledge-base/info` | Query: `kdb_id` | `KdbInfoResponse` | 获取知识库详情 |
| POST | `/api/knowledge-base/retrieve` | `KdbRetrieveRequest` | `{"results":[],"user_id"}` | 检索知识库内容 |
| GET | `/api/knowledge-base/list` | Query: `query_name`,`type`,`page`,`page_size` | `KdbListResponse` | 知识库列表 |
| DELETE | `/api/knowledge-base/delete/{kdb_id}` | 无 | `{"success","user_id"}` | 删除知识库 |
| POST | `/api/knowledge-base/clear` | `{"kdb_id"}` | `{"success","user_id"}` | 清空知识库内容 |
| POST | `/api/knowledge-base/redo_all` | `{"kdb_id"}` | `{"success","user_id"}` | 重跑全部任务 |
| GET | `/api/knowledge-base/doc/list` | Query: `kdb_id`,`query_name`,`query_status`,`task_id`,`page_no`,`page_size` | `KdbDocListResponse` | 文档列表 |
| GET | `/api/knowledge-base/doc/info/{doc_id}` | 无 | `KdbDocInfoResponse \| null` | 文档详情 |
| POST | `/api/knowledge-base/doc/add_by_files` | `multipart/form-data` | `{"taskId","user_id"}` | 上传文档到知识库 |
| DELETE | `/api/knowledge-base/doc/delete/{doc_id}` | 无 | `{"success","user_id"}` | 删除文档 |
| PUT | `/api/knowledge-base/doc/redo/{doc_id}` | 无 | `{"success","user_id"}` | 重跑单文档 |
| GET | `/api/knowledge-base/doc/task_process` | Query: `kdb_id`,`task_id` | `KdbDocTaskProcessResponse` | 查询任务进度 |
| POST | `/api/knowledge-base/doc/task_redo` | `{"kdb_id","task_id"}` | `{"success","user_id"}` | 重跑单任务 |

### Tools、Skills、MCP

| Method | Path | 请求 | 返回 `data` | 用途 |
| --- | --- | --- | --- | --- |
| GET | `/api/tools` | Query: `type` | `{"tools":[]}` | 获取工具列表 |
| POST | `/api/tools/exec` | `{"tool_name","tool_params"}` | 工具执行结果 | 直接执行工具 |
| GET | `/api/skills` | Query: `agent_id`,`dimension` | `{"skills":[]}` | 获取技能列表 |
| GET | `/api/skills/agent-available` | Query: `agent_id` | `{"skills":[]}` | 获取某个 Agent 的可用技能 |
| POST | `/api/skills/upload` | `multipart/form-data` | `{"user_id"}` | 上传 ZIP 导入 Skill |
| POST | `/api/skills/import-url` | `{"url","is_system","is_agent","agent_id"}` | `{"user_id"}` | 从 URL 导入 Skill |
| DELETE | `/api/skills` | Query: `name`,`agent_id?` | 无或空对象 | 删除 Skill |
| GET | `/api/skills/content` | Query: `name` | `{"content"}` | 获取 `SKILL.md` 内容 |
| PUT | `/api/skills/content` | `{"name","content"}` | 无或空对象 | 更新 `SKILL.md` |
| POST | `/api/mcp/add` | `MCPServerRequest` | `{"server_name","status"}` | 新增 MCP Server |
| GET | `/api/mcp/list` | 无 | `{"servers":[]}` | 获取 MCP Server 列表 |
| DELETE | `/api/mcp/{server_name}` | 无 | `{"server_name"}` | 删除 MCP Server |
| POST | `/api/mcp/{server_name}/refresh` | 无 | `{"server_name","status"}` | 刷新 MCP Server |

### Provider、系统、存储、版本、可观测性

| Method | Path | 请求 | 返回 | 用途 |
| --- | --- | --- | --- | --- |
| POST | `/api/llm-provider/verify` | `LLMProviderCreate` | 验证结果 | 校验 Provider 是否可用 |
| POST | `/api/llm-provider/verify-multimodal` | `LLMProviderCreate` | 验证结果 | 校验多模态能力 |
| GET | `/api/llm-provider/list` | 无 | Provider 列表 | 获取 Provider |
| POST | `/api/llm-provider/create` | `LLMProviderCreate` | Provider | 创建 Provider |
| PUT | `/api/llm-provider/update/{provider_id}` | `LLMProviderUpdate` | Provider | 更新 Provider |
| DELETE | `/api/llm-provider/delete/{provider_id}` | 无 | 删除结果 | 删除 Provider |
| GET | `/api/system/info` | 无 | 系统公开配置 | 前端初始化 |
| POST | `/api/system/update_settings` | `{"allow_registration"}` | `{}` | 更新系统设置 |
| GET | `/api/health` | 无 | `{"status","timestamp","service"}` | 健康检查 |
| POST | `/api/oss/upload` | `multipart/form-data` | `{"url"}` | 上传文件到对象存储 |
| GET | `/api/system/version/check` | 无 | Tauri 更新响应 | 桌面端自动更新 |
| GET | `/api/system/version/latest` | 无 | 最新版本 | Web 下载页 |
| POST | `/api/system/version/import_github` | 无 | 版本记录 | 从 GitHub 导入最新版本 |
| POST | `/api/system/version` | `CreateVersionRequest` | 版本记录 | 手动创建版本 |
| GET | `/api/system/version` | 无 | 版本记录列表 | 获取所有版本 |
| DELETE | `/api/system/version/{version_str}` | 无 | `{"success":true}` | 删除版本 |
| GET | `/api/observability/jaeger/login` | Query: `next?` | 302 或错误 | 进入 Jaeger 前鉴权 |
| GET | `/api/observability/jaeger/auth` | 无 | 204/401/403 | 探测当前用户是否可访问 Jaeger |
| GET | `/api/observability/jaeger` | 无 | 307 | 重定向到 Jaeger 根地址 |
| ANY | `/api/observability/jaeger/{full_path}` | 保留原请求 | 307 | 重定向到 Jaeger 具体路径 |

## 关键请求与返回模型

### 注册与登录

注册：

```json
{
  "username": "alice",
  "password": "StrongPassword123",
  "email": "user@example.com",
  "phonenum": "13800000000",
  "verification_code": "123456"
}
```

登录：

```json
{
  "username_or_email": "alice",
  "password": "StrongPassword123"
}
```

登录成功返回：

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 3600
}
```

### ChatRequest

`/api/chat` 使用这个模型，必须有 `agent_id`：

```json
{
  "messages": [
    {
      "message_id": "optional",
      "role": "user",
      "content": "Hello"
    }
  ],
  "session_id": "sess_123",
  "user_id": "optional",
  "system_context": {},
  "agent_id": "agent_abc"
}
```

说明：

| 字段 | 含义 |
| --- | --- |
| `messages` | 消息列表 |
| `message_id` | 消息 ID，可选 |
| `role` | 角色，如 `user`、`assistant`、`system` |
| `content` | 字符串，或多模态数组 |
| `session_id` | 会话 ID，可复用历史会话 |
| `user_id` | 不传时服务端通常从 session 注入 |
| `system_context` | 结构化上下文 |
| `agent_id` | 必填，指定使用哪个 Agent |

### StreamRequest

`/api/stream` 与 `/api/web-stream` 在 `ChatRequest` 基础上支持更多运行时覆盖字段：

- `agent_name`
- `deep_thinking`
- `max_loop_count`
- `multi_agent`
- `agent_mode`
- `more_suggest`
- `available_workflows`
- `llm_model_config`
- `system_prefix`
- `available_tools`
- `available_skills`
- `available_knowledge_bases`
- `available_sub_agent_ids`
- `force_summary`
- `memory_type`
- `custom_sub_agents`
- `context_budget_config`
- `extra_mcp_config`

适用场景：
- 你要按单次请求临时覆盖 Agent 的运行参数

### AgentConfigDTO

```json
{
  "id": "optional",
  "user_id": "optional",
  "name": "Research Agent",
  "systemPrefix": "You are a careful research assistant.",
  "systemContext": {},
  "availableWorkflows": {},
  "availableTools": ["web_search"],
  "availableSubAgentIds": [],
  "availableSkills": ["market-research"],
  "availableKnowledgeBases": [],
  "memoryType": "session",
  "maxLoopCount": 10,
  "deepThinking": false,
  "llm_provider_id": "provider_xxx",
  "enableMultimodal": false,
  "multiAgent": false,
  "agentMode": "default",
  "description": "Handles market research"
}
```

### 知识库常用模型

创建知识库：

```json
{
  "name": "Product Docs",
  "type": "rag",
  "intro": "Internal product documents",
  "language": "en"
}
```

检索知识库：

```json
{
  "kdb_id": "kdb_xxx",
  "query": "How does login work?",
  "top_k": 10
}
```

重跑单任务：

```json
{
  "kdb_id": "kdb_xxx",
  "task_id": "task_xxx"
}
```

### LLMProviderCreate

```json
{
  "name": "OpenAI Compatible",
  "base_url": "https://api.example.com/v1",
  "api_keys": ["sk-xxxx"],
  "model": "gpt-4o",
  "max_tokens": 4096,
  "temperature": 0.7,
  "top_p": 1,
  "presence_penalty": 0,
  "max_model_len": 128000,
  "supports_multimodal": true,
  "is_default": true
}
```

约束：

- `api_keys` 必须且只能包含一个非空单行 key

### MCPServerRequest

```json
{
  "name": "docs-mcp",
  "protocol": "streamable_http",
  "streamable_http_url": "https://mcp.example.com",
  "sse_url": null,
  "api_key": "secret"
}
```

## 字段级说明

### `AgentConfigDTO` 字段表

| 字段 | 类型 | 含义 | 什么时候用 |
| --- | --- | --- | --- |
| `name` | string | Agent 名称 | 必填，创建和展示都要用 |
| `systemPrefix` | string | 系统提示词 | 定义 Agent 的角色和行为边界 |
| `systemContext` | object | 结构化上下文 | 需要给 Agent 注入固定上下文时 |
| `availableWorkflows` | object | 可用工作流映射 | Agent 需要工作流能力时 |
| `availableTools` | string[] | 允许使用的工具 | 控制 Agent 工具权限 |
| `availableSubAgentIds` | string[] | 可调度子 Agent 列表 | 需要多 Agent 协作时 |
| `availableSkills` | string[] | 可用 Skill 列表 | 希望 Agent 使用 Skill 时 |
| `availableKnowledgeBases` | string[] | 可用知识库 ID 列表 | 需要接知识库检索时 |
| `memoryType` | string | 记忆模式 | 通常用 `session` |
| `maxLoopCount` | integer | 推理/工具循环上限 | 控制最长运行步数 |
| `deepThinking` | boolean | 更深推理模式 | 复杂推理场景可开启 |
| `llm_provider_id` | string | 绑定的模型提供方 ID | 想明确指定 Provider 时 |
| `enableMultimodal` | boolean | 是否启用多模态 | 需要图像输入时 |
| `multiAgent` | boolean | 是否启用多 Agent | 多 Agent 协作时 |
| `agentMode` | string | Agent 模式 | 有模式切换需求时 |
| `description` | string | Agent 描述 | 管理页和自动生成场景 |

### `StreamRequest` 额外字段表

| 字段 | 类型 | 含义 | 什么时候用 |
| --- | --- | --- | --- |
| `agent_name` | string | 临时指定 Agent 名称 | 调试或临时覆盖展示名 |
| `deep_thinking` | boolean | 临时启用深度推理 | 单次请求更重推理 |
| `max_loop_count` | integer | 单次请求循环上限 | 控制成本或运行深度 |
| `multi_agent` | boolean | 单次请求启用多 Agent | 不改保存配置，只临时启用 |
| `agent_mode` | string | 单次请求 Agent 模式 | 模式切换 |
| `more_suggest` | boolean | 生成更多建议 | 前端想要更多候选建议时 |
| `available_workflows` | object | 临时工作流集合 | 调试或临时工作流注入 |
| `llm_model_config` | object | 临时模型配置 | 临时覆盖模型参数 |
| `system_prefix` | string | 临时 system prompt | 不改 Agent 配置，只改单次请求 |
| `available_tools` | string[] | 临时工具列表 | 缩小或扩大单次可用工具 |
| `available_skills` | string[] | 临时技能列表 | 缩小或扩大单次可用技能 |
| `available_knowledge_bases` | string[] | 临时知识库列表 | 单次请求只允许某些知识库 |
| `available_sub_agent_ids` | string[] | 临时子 Agent 列表 | 单次请求允许哪些子 Agent |
| `force_summary` | boolean | 强制总结 | 想在结束时强制输出总结 |
| `memory_type` | string | 单次记忆模式 | 临时切换记忆策略 |
| `custom_sub_agents` | array | 内联子 Agent 配置 | 不依赖已保存子 Agent |
| `context_budget_config` | object | 上下文预算配置 | 控制上下文裁剪和预算 |
| `extra_mcp_config` | object | 额外 MCP 配置 | 临时挂接 MCP server 参数 |

### 知识库文档查询字段

`GET /api/knowledge-base/doc/list`：

| 参数 | 类型 | 含义 |
| --- | --- | --- |
| `kdb_id` | string | 知识库 ID，必填 |
| `query_name` | string | 按文档名搜索 |
| `query_status` | int[] | 按任务状态过滤 |
| `task_id` | string | 按任务 ID 过滤 |
| `page_no` | integer | 页码，从 1 开始 |
| `page_size` | integer | 每页数量 |

`GET /api/knowledge-base/doc/task_process`：

| 参数 | 类型 | 含义 |
| --- | --- | --- |
| `kdb_id` | string | 知识库 ID |
| `task_id` | string | 任务 ID |

返回字段：

| 字段 | 含义 |
| --- | --- |
| `success` | 成功条数 |
| `fail` | 失败条数 |
| `inProgress` | 处理中条数 |
| `waiting` | 排队中条数 |
| `total` | 总条数 |
| `taskProcess` | 进度比例 |

### `LLMProviderCreate` 字段表

| 字段 | 类型 | 含义 | 备注 |
| --- | --- | --- | --- |
| `name` | string | Provider 名称 | 展示名 |
| `base_url` | string | OpenAI 兼容接口基地址 | 通常以 `/v1` 结尾 |
| `api_keys` | string[] | API Key 列表 | 当前只允许 1 个 key |
| `model` | string | 模型名 | 如 `gpt-4o` |
| `max_tokens` | integer | 最大输出 token | 可选 |
| `temperature` | float | 采样温度 | 可选 |
| `top_p` | float | top-p 采样参数 | 可选 |
| `presence_penalty` | float | 话题新颖度惩罚 | 可选 |
| `max_model_len` | integer | 模型上下文长度 | 可选 |
| `supports_multimodal` | boolean | 是否支持多模态 | 主要给 UI 和校验逻辑用 |
| `is_default` | boolean | 是否默认 Provider | 创建时当前实现最终会存成非默认 |

### `MCPServerRequest` 字段表

| 字段 | 类型 | 含义 | 备注 |
| --- | --- | --- | --- |
| `name` | string | MCP Server 名称 | 同名冲突要避免 |
| `protocol` | string | 协议类型 | 当前代码注释写的是 `streamable_http` 或 `sse` |
| `streamable_http_url` | string | Streamable HTTP 地址 | `protocol=streamable_http` 时用 |
| `sse_url` | string | SSE 地址 | `protocol=sse` 时用 |
| `api_key` | string | MCP Server 访问密钥 | 可选 |

## 常见错误响应

### 未登录

常见于：

- `GET /api/auth/session`
- `GET /api/user/options`
- `POST /api/user/change-password`
- `GET /api/user/config`

示例：

```json
{
  "code": 401,
  "message": "未登录",
  "data": null,
  "timestamp": 1710000000.123
}
```

### 权限不足

常见于：

- `GET /api/user/list`
- `POST /api/user/add`
- `POST /api/user/delete`
- `POST /api/system/update_settings`
- `GET /api/observability/jaeger/auth`

示例：

```json
{
  "code": 403,
  "message": "权限不足",
  "data": null,
  "timestamp": 1710000000.123
}
```

### 本地注册或本地登录未开启

常见于：

- `POST /api/auth/register/send-code`
- `POST /api/auth/register`
- `POST /api/auth/login`
- 对应 `/api/user/*` 兼容接口

示例：

```json
{
  "code": 400,
  "message": "当前服务未启用本地账号密码登录",
  "data": null,
  "timestamp": 1710000000.123
}
```
或
```json
{
  "code": 400,
  "message": "当前服务未启用本地账号注册",
  "data": null,
  "timestamp": 1710000000.123
}
```

### Provider 不存在或不可修改

常见于：

- `PUT /api/llm-provider/update/{provider_id}`
- `DELETE /api/llm-provider/delete/{provider_id}`

示例：

```json
{
  "code": 500,
  "message": "Provider not found",
  "data": null,
  "timestamp": 1710000000.123
}
```

或：

```json
{
  "code": 500,
  "message": "Cannot delete default provider",
  "data": null,
  "timestamp": 1710000000.123
}
```

说明：

- 这里返回的是业务错误包裹，不一定是你预期的 HTTP 404/403
- 这是当前代码的真实行为，不是理想化设计

### Tool 不存在或执行失败

常见于：

- `POST /api/tools/exec`

可能场景：

- `tool_name` 填错
- 工具管理器未初始化
- MCP 工具无权限
- 工具运行时异常

这类错误很多时候会走异常路径，实际响应可能不是统一的 `BaseResponse` 成功格式，前端接入时要按失败分支处理。

### 聊天请求参数无效

常见于：

- `POST /api/chat`
- `POST /api/stream`
- `POST /api/web-stream`

最典型场景：

- `messages` 为空

这类情况会抛业务异常，例如“消息列表不能为空”。

## 常用调用示例

### 1. 发送注册验证码

```bash
curl -X POST http://127.0.0.1:8000/api/auth/register/send-code \
  -H 'Content-Type: application/json' \
  -d '{"email":"user@example.com"}'
```

### 2. 登录并保存 cookie

```bash
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username_or_email":"alice","password":"StrongPassword123"}'
```

### 3. 读取当前登录态

```bash
curl -b cookies.txt http://127.0.0.1:8000/api/auth/session
```

### 4. 发起流式对话

```bash
curl -N -b cookies.txt -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "messages":[{"role":"user","content":"Summarize the repository structure."}],
    "session_id":"sess_123",
    "agent_id":"agent_abc"
  }'
```

### 5. 断线重连继续订阅

```bash
curl -N http://127.0.0.1:8000/api/stream/resume/sess_123?last_index=15
```

### 6. 创建 Agent

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/agent/create \
  -H 'Content-Type: application/json' \
  -d '{
    "name":"Research Agent",
    "systemPrefix":"You are a careful research assistant.",
    "availableTools":["web_search"],
    "availableSkills":["market-research"],
    "memoryType":"session",
    "maxLoopCount":10
  }'
```

### 7. 检索知识库

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/knowledge-base/retrieve \
  -H 'Content-Type: application/json' \
  -d '{
    "kdb_id":"kdb_xxx",
    "query":"How does login work?",
    "top_k":5
  }'
```

### 8. 上传知识库文档

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/knowledge-base/doc/add_by_files \
  -F 'kdb_id=kdb_xxx' \
  -F 'override=false' \
  -F 'files=@./README.md'
```

### 9. 执行工具

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/tools/exec \
  -H 'Content-Type: application/json' \
  -d '{
    "tool_name":"web_search",
    "tool_params":{"query":"Sage repository"}
  }'
```

### 10. 导入 Skill

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/skills/import-url \
  -H 'Content-Type: application/json' \
  -d '{
    "url":"https://example.com/skill.zip",
    "is_system":false,
    "is_agent":false,
    "agent_id":null
  }'
```

### 11. 上传对象存储文件

```bash
curl -X POST http://127.0.0.1:8000/api/oss/upload \
  -F 'file=@./example.png' \
  -F 'path=uploads/images'
```

### 12. 获取 OAuth2 元数据

```bash
curl http://127.0.0.1:8000/.well-known/oauth-authorization-server
```

### 13. 用授权码换 token

```bash
curl -X POST http://127.0.0.1:8000/oauth2/token \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'grant_type=authorization_code&code=AUTH_CODE&redirect_uri=https%3A%2F%2Fclient.example.com%2Fcallback&code_verifier=PKCE_VERIFIER'
```

## 备注

- 这页只保留当前代码里真实存在、且对接方真正需要知道的信息。
- 旧接口、推测行为、历史遗留说明都尽量压缩到最小。
- 如果后面继续补，会优先补“错误响应示例”和“字段级枚举说明”，不会再把页面写回成流水账。
