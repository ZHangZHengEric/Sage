---
layout: default
title: Agent extra capabilities
parent: HTTP API Reference
nav_order: 3
description: "Async submit flows, ability cards, workspace and auth"
lang: en
ref: http-api-agent
---

{% include lang_switcher.html %}

# Agent extra capabilities

The main table already covers CRUD, workspace, auto-generate, and prompt optimization. This page documents **async** and **UI-facing** endpoints.

## Sync vs async generation / optimization

| Endpoint | Behavior |
| --- | --- |
| `POST /api/agent/auto-generate` | Waits and returns a draft in one HTTP round-trip. |
| `POST /api/agent/auto-generate/submit` | Enqueues work and returns a `task_id` immediately; poll `GET /api/agent/tasks/{task_id}`. Use when the LLM step may exceed HTTP time limits. |
| `POST /api/agent/system-prompt/optimize` | Synchronous optimization. |
| `POST /api/agent/system-prompt/optimize/submit` | Asynchronous; poll like auto-generate. |

`AsyncTaskResponse` in `common/schemas/agent.py` includes `status`, `result`, `error`, `metadata`, and timestamps. Exact status transitions live in `common/services/async_task_service`.

`POST /api/agent/tasks/{task_id}/cancel` requests cancellation; whether heavy work stops immediately is task-type specific.

## Ability cards

`POST /api/agent/abilities` with `AgentAbilitiesRequest`:

| Field | Meaning |
| --- | --- |
| `agent_id` | Required |
| `session_id` | Optional, for more grounded cards |
| `context` | Optional structured add-ons |
| `language` | Defaults to `zh` for copy |

The response powers UI “what this agent can do” tiles (titles, descriptions, and suggested `promptText` snippets) and does not persist a config change by itself.

## File workspace and authorization

- `file_workspace` routes list, download, and delete under per-session sandboxes; pass `session_id` when the UI needs session-scoped files.
- `.../auth` administers **which `user_id`s may use the agent**—separate from login identity, which is handled under `/api/auth` / `/api/user`.

## Deleting a user workspace

`POST /api/agent/workspace/delete` with `{"agent_id","user_id"}` is mainly for admin cleanup of `agents/{user_id}/{agent_id}` on disk, returning the path and a `deleted` flag.

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
