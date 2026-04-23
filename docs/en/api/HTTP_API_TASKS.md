---
layout: default
title: Planner tasks and /tasks
parent: HTTP API Reference
nav_order: 6
description: "One-time and recurring jobs, internal scheduler routes, response shapes"
lang: en
ref: http-api-tasks
---

{% include lang_switcher.html %}

# Planner tasks and `/tasks`

These jobs are **not** the same as in-conversation status from `POST /api/sessions/.../tasks_status`. The planner uses `common/services/task_service` and DB-backed entities.

## Path prefix

Routes live under **`/tasks`** (no `/api` prefix). If you only reverse-proxy `/api/*`, you must add a separate rule for `/tasks`.

## Response shape

- List endpoints return Pydantic models such as `OneTimeTaskListResponse` or `TaskListResponse` (fields like `items`, `page`, `page_size`, `total`). There is **no** top-level `code` / `message` / `timestamp` `BaseResponse` wrapper.
- Deletes often return `{"success": true}`.

## One-time jobs

`OneTimeTaskCreate` (see `common/schemas/base.py`) includes:

| Field | Meaning |
| --- | --- |
| `name` / `description` | Title and text |
| `agent_id` | Which agent to run at `execute_at` |
| `execute_at` | `datetime` for the fire time |

`GET /tasks/one-time/{id}/history` returns a list with a `limit` query cap (a lighter history than the paged recurring history).

## Recurring jobs

`RecurringTaskCreate` includes a `cron_expression` and `enabled`. `POST /tasks/recurring/{id}/toggle` uses a JSON body `{"enabled": <bool>}` (embedded field).

`GET /tasks/recurring/{id}/history` is paginated (`TaskHistoryListResponse`).

## Internal `.../internal/...` routes

For **schedulers, workers, or controlled automation**:

- `POST /tasks/internal/spawn-due` — materialize due work.
- `GET /tasks/internal/due` — pull pending items.
- `.../claim`, `.../complete`, `.../fail` — one-time job lifecycle.
- `POST /tasks/internal/recurring/{id}/complete` — mark a recurring run complete.

`SAGE_TASK_SCHEDULER_USER_ID` and `get_request_user_id` affect whether internal calls are scoped; protect these paths at the network/gateway layer.

## Not the same as agent async tasks
{:#planner-vs-agent-async}

`GET /api/agent/tasks/{task_id}` is the **async long-running task** system (e.g. auto-generate / prompt optimization) managed by `async_task_service`, not this planner. Similar names, different storage—do not mix them.

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
