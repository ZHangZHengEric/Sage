---
layout: default
title: Chat, streaming, and message edits
parent: HTTP API Reference
nav_order: 2
description: "optimize-input, the three stream POST endpoints, rerun-stream, last user message edit"
lang: en
ref: http-api-chat
---

{% include lang_switcher.html %}

# Chat, streaming, and message edits

This page explains behavior and integration choices for chat/streaming routes listed in the main index. See `app/server/routers/chat.py` and `conversation.py` for the implementation.

## The three stream `POST` entry points

| Endpoint | Auth | When to use |
| --- | --- | --- |
| `/api/chat` | Session middleware (unless allowlisted) | **Requires** `agent_id` in JSON; `prepare_session` fills tools/skills from the saved agent. |
| `/api/stream` | Same | `StreamRequest` with `require_agent_id=False`—if `agent_id` is present it is used, otherwise the server resolves the agent from saved defaults / session. Typical product flow: selected agent + this endpoint. |
| `/api/web-stream` | Same | Backed by `StreamManager` for re-entrancy: a new request for the same `session_id` **stops** the old stream first. Good for web tabs and reconnect UX. |

Shared validation: `messages` must be non-empty. `user_id` can be injected from the session if omitted.

## User input optimization

- `POST /api/chat/optimize-input`: `BaseResponse` with structured `data` from the service.
- `POST /api/chat/optimize-input/stream`: `text/plain` where **each line** is one JSON object from the stream.

`UserInputOptimizeRequest.user_id` is optional; the server reads the current user from `request.state.user_claims`.

## Resume and active sessions

- `GET /api/stream/resume/{session_id}`: continues from `last_index` in `StreamManager`. If no new chunks, you may get a `stream_end` line with `resume_fallback: true`.
- `GET /api/stream/active_sessions`: SSE of currently active streaming session ids for the UI.

## Rerun vs edit

- `POST /api/conversations/{session_id}/rerun-stream`: does not require `messages` in the request body. The server loads the last user turn and re-runs the stream. Optional `RerunStreamRequest` fields override `agent_id`, sub-agents, mode, etc. Same `text/plain` stream shape as `web-stream`.
- `POST /api/conversations/{session_id}/edit-last-user-message` updates the stored last **user** message; call `rerun-stream` after if you need a new model response.

## `tool_progress` events in the stream

In addition to regular `message` events, the NDJSON stream from any of the three
endpoints above may also contain `tool_progress` events that carry incremental
output from a tool while it is still running:

```json
{"type":"tool_progress","tool_call_id":"call_abc","text":"...","stream":"stdout","closed":false,"ts":1761700000.123}
```

- UI-only. These events **never** enter session history / MessageManager / the
  LLM context.
- Clients aggregate by `tool_call_id` into the corresponding tool card;
  `closed: true` marks the end of the live stream.
- Downstream consumers that don't care can simply ignore lines with
  `type=tool_progress`; the existing protocol is fully preserved.
- To disable: set `SAGE_TOOL_PROGRESS_ENABLED=false` on the server.

See [Architecture · §12 Tool live-progress channel](../architecture/ARCHITECTURE_SAGENTS_TOOL_SKILL.md#12-tool-live-progress-channel-tool_progress).

## Interrupt

`POST /api/sessions/{session_id}/interrupt` stops a running session at the engine level. That is different from the automatic stop inside `web-stream` / `rerun-stream` when the same session is replaced.

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
