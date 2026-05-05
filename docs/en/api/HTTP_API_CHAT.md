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

`rerun-stream` also accepts optional `guidance_content` and `guidance_id`. The UI uses this for "apply guidance now": it interrupts the running stream, deletes the pending guidance item, and reruns the session with `guidance_content` appended as a new user message.

## Runtime guidance messages

A running session can receive guidance messages. The message first enters the session pending queue. Before the next LLM request, the agent consumes it, writes it to `MessageManager`, includes it in the current LLM context, and streams it back as a regular `role=user` message. The returned message includes `metadata.guidance_id`, so the frontend can remove the matching guidance chip.

Use this when a user sends follow-up guidance while the assistant is already running, for example "prioritize the failing test first". This is different from `interrupt`: it does not stop the session and does not immediately force a new model request.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/sessions/{session_id}/inject-user-message` | Queue one guidance user message for the running session. |
| `GET` | `/api/sessions/{session_id}/inject-user-message` | List queued guidance messages that have not been consumed yet. |
| `PATCH` | `/api/sessions/{session_id}/inject-user-message/{guidance_id}` | Edit one queued guidance message before it is consumed. |
| `DELETE` | `/api/sessions/{session_id}/inject-user-message/{guidance_id}` | Delete one queued guidance message before it is consumed. |

### Add guidance

Request body:

```json
{
  "content": "Please prioritize the failing test first",
  "guidance_id": "optional-client-id",
  "metadata": {
    "source_ui": "guidance_area"
  }
}
```

`guidance_id` is optional. If omitted, the runtime generates one. `metadata` is optional and is merged into the eventual user `MessageChunk.metadata`.

Successful responses use the standard `BaseResponse` wrapper. The important `data` shape is:

```json
{
  "session_id": "sess_123",
  "guidance_id": "optional-client-id",
  "accepted": true
}
```

### List, edit, and delete pending guidance

`GET` returns:

```json
{
  "session_id": "sess_123",
  "items": [
    {
      "guidance_id": "g1",
      "content": "Please prioritize the failing test first",
      "status": "pending",
      "timestamp": 1761700000.123
    }
  ]
}
```

`PATCH` body:

```json
{"content": "Please prioritize the failing test and summarize the fix"}
```

`PATCH` returns `{"updated": true}` in `data`; `DELETE` returns `{"deleted": true}` in `data`.

### Client handling notes

- Keep a local guidance chip keyed by `guidance_id` after `POST` succeeds.
- Remove the chip when the stream emits a normal `role=user` message whose `metadata.guidance_id` matches.
- Treat a 4xx on `PATCH` / `DELETE` as "already consumed or missing" unless the error is clearly validation-related.
- `content` must be non-empty; empty content is rejected.

Once a guidance message is consumed, it is a normal persisted user message and can no longer be edited through the pending-guidance endpoints.

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
