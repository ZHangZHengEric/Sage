---

## layout: default

title: 工具、技能与 MCP
parent: HTTP API 参考
nav_order: 5
description: "list/exec、技能维度与同步、MCP 注册与刷新"
lang: zh
ref: http-api-tools

{% include lang_switcher.html %}

# 工具、技能与 MCP

路由源文件：`app/server/routers/tool.py`、`skill.py`、`mcp.py`。与 Agent 上配置的 `availableTools` / `availableSkills` 以及运行时 ToolManager 配合使用。

## `/api/tools`

- `GET /api/tools?type=...` 列出当前可发现的工具；`type` 用于过滤，具体取值以服务端实现为准。
- `POST /api/tools/exec` 是「直接调工具一次」的入口，适合管理端或测试。**生产对话流**中工具调用多数仍由智能体在会话内按策略执行，与 exec 的相同点是底层 tool 名与参数，不同点是**上下文与权限**由会话注入。

执行失败时，主参考已说明**不一定**是统一 `BaseResponse` 成功体，请按 HTTP 与业务 code 分分支处理。

## `/api/skills` 与「同步到 workspace」的几种方式


| 场景                                         | 端点                                                                      | 说明                                        |
| ------------------------------------------ | ----------------------------------------------------------------------- | ----------------------------------------- |
| 当前用户下，把一个技能**拷到**某个 Agent 的 workspace      | `POST /api/skills/sync-to-agent`（`multipart`；`skill_name` + `agent_id`） | 技能广场/用户技能 → 单 Agent 目录。                   |
| 把某 Agent **在所有用户** 下的 workspace 都同步一批技能    | `POST /api/skills/sync-to-agent-workspaces`                             | 多租户/管理场景，注意权限与数据量。                        |
| 用 Agent **已保存配置** 里的技能列表，落盘到某用户的 workspace | `POST /api/skills/sync-workspace-skills`                                | `purge_extra` 为真时会删掉目录里**多余**技能文件以完全对齐配置。 |


`GET /api/skills` 可带 `dimension`（`system` / `user` / `agent`）和 `agent_id` 做过滤；`GET /api/skills/agent-available?agent_id=` 会带去重与来源标签，适合 UI 多选。

## `/api/mcp`

- 注册：`POST /api/mcp/add`，协议字段见主参考 `MCPServerRequest`。
- 列举：`GET /api/mcp/list`。
- 删除：`DELETE /api/mcp/{server_name}`。
- 发现/刷新能力：`POST /api/mcp/{server_name}/refresh`（在远端 MCP 配置变更后常用）。

MCP 工具出现在 Agent 对话中，还依赖 Agent 的可用工具/策略及服务端是否把该 MCP 暴露给该用户/会话；**只注册 MCP 不等于**所有对话自动能调用，需在 Agent 与权限模型里一并设计。

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)