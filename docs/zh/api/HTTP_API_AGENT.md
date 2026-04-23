---
layout: default
title: Agent 补充能力
parent: HTTP API 参考
nav_order: 3
description: "异步 submit 任务、能力卡片、file workspace 与授权"
lang: zh
ref: http-api-agent
---

{% include lang_switcher.html %}

# Agent 补充能力

主表已列出 CRUD、文件工作区、自动生成与 prompt 优化等。本页补充 **异步** 与 **展示向** 接口。

## 同步 vs 异步「生成 / 优化」


| 端点                                              | 行为                                                                                                |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `POST /api/agent/auto-generate`                 | 在线等待，直接返回生成草稿（`build_auto_generate_response`）。                                                    |
| `POST /api/agent/auto-generate/submit`          | 只提交到异步队列，**立即** 返回 `task_id` 等，由客户端轮询 `GET /api/agent/tasks/{task_id}`。适合 LLM 耗时较长、避免 HTTP 长连接超时。 |
| `POST /api/agent/system-prompt/optimize`        | 同步优化。                                                                                             |
| `POST /api/agent/system-prompt/optimize/submit` | 异步优化，轮询方式同上。                                                                                      |


`AsyncTaskResponse` 形态（`common/schemas/agent.py`）包含 `status`、`result`、`error`、`metadata` 等；具体状态机以 `common/services/async_task_service` 为准。

`POST /api/agent/tasks/{task_id}/cancel` 为软取消：返回最新任务结构，**是否**完全停止长耗时推理取决于任务类型与实现。

## 能力卡片 `abilities`

`POST /api/agent/abilities` 请求体为 `AgentAbilitiesRequest`：


| 字段           | 含义                  |
| ------------ | ------------------- |
| `agent_id`   | 必填，目标 Agent         |
| `session_id` | 可选，用于从会话里取更贴近上下文的材料 |
| `context`    | 可选，额外结构化上下文         |
| `language`   | 默认 `zh`，影响卡片文案语言    |


响应用于前端展示「Agent 会做什么」类卡片（标题、说明、可复制的 `promptText` 片段等），不直接改 Agent 存盘配置。

## 文件工作区与授权

- `file_workspace` 系列为沙箱/会话目录下列文件、下载、删除；`session_id` 用于区分多会话工作目录。
- `GET/POST .../auth` 管理「哪些 user_id 能使用该 Agent」；与 OAuth 的「谁登录」是两层概念：前者是 **Agent 级授权列表**，后者是 **账户登录**。

## 删除用户侧 workspace

`POST /api/agent/workspace/delete` 体为 `{"agent_id","user_id"}`，通常用于管理员/运维清理 `agents/{user_id}/{agent_id}` 目录；会返回路径与 `deleted` 标志。

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)