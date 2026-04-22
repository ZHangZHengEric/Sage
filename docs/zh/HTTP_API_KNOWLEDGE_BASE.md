---
layout: default
title: 知识库 RAG
parent: HTTP API 参考
nav_order: 4
description: "创建、检索、文档与任务、与 Agent 的 availableKnowledgeBases 绑定"
lang: zh
ref: http-api-kdb
---

{% include lang_switcher.html %}

# 知识库 RAG

路由源文件：`app/server/routers/kdb.py`，业务实现位于 `common/services` 下与 KDB 相关的服务（名称可能含 `kdb` / `knowledge`）。主参考中的路径均以 `/api/knowledge-base` 为前缀。

## 与其他模块的关系

- **Agent 侧**：在 `AgentConfigDTO` 的 `availableKnowledgeBases`（或兼容字段名）中列出 `kdb_id` 后，运行时才允许该 Agent 的检索/对话管线访问这些库（具体 enforcement 在 chat/Agent 装配层）。
- **工具侧**：产品也可能通过工具封装间接调用 `POST .../retrieve`；与直接 HTTP 调用的区别主要在鉴权、审计和计费边界。

## 推荐集成顺序

1. `POST /api/knowledge-base/add` 建库，记下返回的 `kdb_id`。
2. 用 `POST /api/knowledge-base/doc/add_by_files` 上传文档，拿到 `taskId`。
3. 用 `GET /api/knowledge-base/doc/task_process` 或文档列表/状态接口观察解析与索引是否完成；必要时 `.../redo`*.
4. `POST /api/knowledge-base/retrieve` 做联调检索；`top_k` 等参数见主参考「知识库常用模型」。
5. 将 `kdb_id` 配入 Agent 或上层应用配置。

## 易错点

- **删除与清空**：`delete/{kdb_id}` 与 `clear` 语义不同，后者是清空内容、保留库元数据，集成自动化前确认业务要哪一种。
- **文档任务 ID**：`task_id` 在列表、进度、重跑类接口中多次出现，**不要**与 [计划任务 `/tasks](HTTP_API_TASKS.md)` 或 [Agent 异步任务 `GET /api/agent/tasks/...](HTTP_API_AGENT.md)` 混读。
- **分页与过滤**：`doc/list` 的 `query_status`、`page_no` 等见主参考「知识库文档查询字段」表。

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)