---
layout: default
title: API
nav_order: 8
lang: en
ref: v2-api-README
has_children: true
---

{% include lang_switcher.html %}

# API

| Interface | Use |
| --- | --- |
| [Python runtime](API_REFERENCE.md) | Embed SAgents v2 and own its lifecycle. |
| [Server HTTP](HTTP_API_REFERENCE.md) | Authenticate users and manage models, Agents, Skills, MCP, and Runs. |
| [Platform and observability](HTTP_API_PLATFORM.md) | Inspect health, logs, and storage boundaries. |

Server v2 and the Desktop sidecar are different APIs. Server chat uses AG-UI SSE at `POST /api/agent`; Desktop uses authenticated local `/api/v2/...` routes and native runtime events. Do not copy routes from the legacy server into a v2 client.
