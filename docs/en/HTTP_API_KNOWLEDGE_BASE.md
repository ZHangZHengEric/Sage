---
layout: default
title: Knowledge base (RAG)
parent: HTTP API Reference
nav_order: 4
description: "Create, retrieve, document pipelines, and binding to availableKnowledgeBases"
lang: en
ref: http-api-kdb
---

{% include lang_switcher.html %}

# Knowledge base (RAG)

Router: `app/server/routers/kdb.py`. All route prefixes in the main doc use `/api/knowledge-base`.

## How this ties to other features

- **Agents**: set `kdb_id`s in `AgentConfigDTO.availableKnowledgeBases` (or the snake_case alias) so the runtime can attach the right retrieval to that agent. Exact enforcement is in the chat/agent wiring layer, not the KDB router alone.
- **Tools**: some UIs go through a tool that wraps `POST .../retrieve` instead of calling HTTP from the client—same backend, different surface for auth/auditing.

## Suggested integration order

1. `POST .../add` and store `kdb_id`.
2. `POST .../doc/add_by_files` to ingest files; capture `taskId`.
3. Poll `.../doc/task_process` and/or `.../doc/list` until processing is healthy; use `.../redo` paths when you need a rerun.
4. `POST .../retrieve` to validate RAG end-to-end.
5. Add the `kdb_id` to agent config or your own orchestration.

## Common pitfalls

- **Delete vs clear**: `DELETE /api/knowledge-base/delete/{kdb_id}` vs `POST .../clear` have different semantics.
- **Task IDs** here are **ingestion jobs** for that KDB, not the `/tasks` scheduler in [HTTP_API_TASKS.md](HTTP_API_TASKS.md) nor the async work in [HTTP_API_AGENT.md](HTTP_API_AGENT.md).
- Re-read the main doc’s table of query parameters for `doc/list` and `doc/task_process` before you script filters.

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
