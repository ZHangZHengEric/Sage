---

## layout: default
title: 对话、流式与消息编辑
parent: HTTP API 参考
nav_order: 2
description: "optimize-input、三种流式入口、rerun-stream 与最后一条用户消息编辑"
lang: zh
ref: http-api-chat

{% include lang_switcher.html %}

# 对话、流式与消息编辑

本页说明主参考表中「聊天 / 流式 / 会话」相关端点的行为细节与选型建议。路由实现见 `app/server/routers/chat.py` 与 `conversation.py`。

## 三种流式 `POST` 的差异


| 端点                | 鉴权与入口            | 典型用途                                                                                                                                                                       |
| ----------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/api/chat`       | 经中间件，需登录（除白名单配置） | **必须**在 JSON 中提供 `agent_id`；`prepare_session` 会按 Agent 已保存配置补全 tools/skills 等。                                                                                             |
| `/api/stream`     | 同上               | 与 chat 共用的 `StreamRequest`，`populate_request_from_agent_config(..., require_agent_id=False)`：若 body 中带有 `agent_id` 会用于解析，否则来自 Agent 侧默认或会话关联配置。产品前端通常用「已选 Agent + stream」。 |
| `/api/web-stream` | 同上               | 通过 `StreamManager` 管理多标签/重入：同一 `session_id` 再次请求会先 **中断** 旧流再启动新流。适合 Web 多窗口与重连。                                                                                           |


流式 body 的公共校验：`messages` 不能为空，否则报「消息列表不能为空」。`user_id` 可从 session 自动注入。

## 用户输入优化

- `POST /api/chat/optimize-input`：返回标准 `BaseResponse`，`data` 为服务层产出的结构（如优化后的建议文本/片段）。
- `POST /api/chat/optimize-input/stream`：每个 chunk 为 **一行 JSON**（`text/plain`），适合边下边展示。

`UserInputOptimizeRequest` 的 `user_id` 可省略，服务端从 `request.state.user_claims` 取当前用户。

## 断线重连与活跃会话

- `GET /api/stream/resume/{session_id}?last_index=`：在 `StreamManager` 中从某序号继续推 chunk；若无新数据，可能回退为读取历史消息，并下发一条 `type: "stream_end"` 且 `resume_fallback: true` 的 JSON 行，便于客户端结束 loading。
- `GET /api/stream/active_sessions`：SSE，推送当前平台认为「正在流式输出」的会话列表，用于多会话 UI 的角标或列表刷新。

## 重跑与编辑消息

- `POST /api/conversations/{session_id}/rerun-stream`：不依赖本次请求里的 `messages`。服务端用 `get_rerun_conversation_payload` 取出「最后用户消息」与历史 agent 绑定，并构造 `StreamRequest`（`system_context` 中标记重跑来源）。`RerunStreamRequest` 中字段均可选，用于覆盖 `agent_id`、子 Agent 列表、模式等。响应与 `web-stream` 一样走 `StreamManager` 的 `text/plain` 流。
- `POST /api/conversations/{session_id}/edit-last-user-message`：只更新存储中的最后一条 **用户** 消息；若之后要重跑模型输出，可再调 `rerun-stream`。

## 与 `/api/sessions/.../interrupt` 的关系

`interrupt` 会尝试停止正在运行的 sagents 会话；与 `web-stream` / `rerun-stream` 里「同会话重入先停旧流」是两条路径：前者是显式用户中断，后者是自动替换流。

## 回主索引

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)