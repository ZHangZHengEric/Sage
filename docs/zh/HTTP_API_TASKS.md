---

## layout: default

title: 计划任务与 /tasks
parent: HTTP API 参考
nav_order: 6
description: "一次性/周期任务、内部调度、响应格式与 Pydantic 模型"
lang: zh
ref: http-api-tasks

{% include lang_switcher.html %}

# 计划任务与 `/tasks` 接口

计划任务与「对话里 `/api/sessions/.../tasks_status` 展示的会话内任务状态」**不是**同一套存储；前者是 `common/services/task_service` 与数据库中的调度实体。

## 路径前缀

所有路由挂在 `**/tasks`**，**没有** `/api` 前缀。若前序反代只转发 `/api/`*，需单独为 `/tasks` 配置路由。

## 响应形状

- 列表类接口返回如 `OneTimeTaskListResponse`、`TaskListResponse` 等，字段名多为 **Pydantic 的驼峰/原样**（如 `page`,`page_size`,`items`），**外层没有** 主文档中的 `code` / `message` / `timestamp` 四段式。
- 删除类接口多返回 `{"success": true}`。

集成时不要用「解析 `data` 下嵌套」的习惯去套这些 API。

## 一次性任务

`OneTimeTaskCreate`（见 `common/schemas/base.py`）主要字段：


| 字段                     | 含义                |
| ---------------------- | ----------------- |
| `name` / `description` | 任务标题与说明           |
| `agent_id`             | 到期后要驱动哪个 Agent 执行 |
| `execute_at`           | `datetime`，到时触发   |


`GET /tasks/one-time/{id}/history` 返回列表结构（实现为简史/事件，非 `TaskHistoryListResponse` 分页模型），`limit` 控制条数上界。

## 周期任务

`RecurringTaskCreate` 含 `cron_expression`、`enabled` 等。`POST .../toggle` 的 body 为 `{"enabled": <bool>}`（FastAPI `embed`）。

`GET /tasks/recurring/{id}/history` 为分页的 `TaskHistoryListResponse`，用于查看每次调度产生的执行记录。

## 内部 `internal` 端点

供 **调度进程、worker、或受控自动化** 使用：

- `spawn-due`：把到期的周期任务展成待执行子项。
- `due`：拉取待处理任务队列。
- `one-time/.../claim` / `complete` / `fail`：工作流式的抢占与收尾。
- `recurring/.../complete`：某轮周期执行完成。

环境变量 `SAGE_TASK_SCHEDULER_USER_ID` 与 `get_request_user_id` 共同决定 `internal` 调用是否按「全局」调度员身份作用域过滤；误用可能看到空列表或越权，部署时需结合网关与密钥限制这些路径。

## 与 Agent 侧异步任务的区别 {: #planner-vs-agent-async }

`GET /api/agent/tasks/{task_id}` 属于 **异步大任务**（如 LLM 生成 Agent、优化 prompt），由 `async_task_service` 管理，**不是** 本页 `/tasks` 调度器。名称相似，存储与轮询方式不同，请勿混用。

[返回 HTTP API 参考](HTTP_API_REFERENCE.md)