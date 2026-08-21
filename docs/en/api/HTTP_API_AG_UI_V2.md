---
layout: default
title: AG-UI V2 chat
parent: HTTP API Reference
nav_order: 3
description: "Native AG-UI 0.1.19 chat input, SSE events, idempotency, and replay limits"
lang: en
ref: http-api-ag-ui-v2
---

{% include lang_switcher.html %}

# AG-UI V2 chat

`POST /api/v2/agent/chat` is an additive AG-UI endpoint. It does not change
`/api/chat`, `/api/stream`, `/api/web-stream`, or their native Sage NDJSON
contracts.

The endpoint uses `ag-ui-protocol==0.1.19`:

- Request: AG-UI `RunAgentInput` JSON.
- Response: `text/event-stream` with AG-UI events.
- Authentication: the current Sage session or bearer identity is authoritative;
  a client-provided user id cannot select another user's runtime.
- Agent selection: `forwardedProps.agentId` is required.

## Request

```json
{
  "threadId": "conversation-123",
  "runId": "run-456",
  "state": {},
  "messages": [
    {"id": "message-789", "role": "user", "content": "Hello"}
  ],
  "tools": [],
  "context": [],
  "forwardedProps": {
    "agentId": "agent-1",
    "providerId": "provider-1",
    "fastProviderId": "provider-fast",
    "systemContext": {},
    "agentMode": "simple",
    "maxLoopCount": 8,
    "moreSuggest": false,
    "availableSubAgentIds": []
  }
}
```

Only the latest `role=user` message enters the new Sage run. Conversation
history remains authoritative in Sage's existing session persistence. Text and
URL image parts are mapped to the native Sage multimodal message shape.
Execution and sandbox approval policies are server-owned; V2 does not accept
client overrides for `commandPolicy` or `sandboxApprovalMode`.

## Response events

A successful stream begins with `RUN_STARTED` and ends with `RUN_FINISHED`.
Failures that prevent or abort a run end with `RUN_ERROR`. Intermediate events
include:

- `TEXT_MESSAGE_START` / `TEXT_MESSAGE_CONTENT` / `TEXT_MESSAGE_END`
- `REASONING_START` / `REASONING_MESSAGE_*` / `REASONING_END`
- `TOOL_CALL_START` / `TOOL_CALL_ARGS` / `TOOL_CALL_END`
- `TOOL_CALL_RESULT`
- `ACTIVITY_SNAPSHOT` for Sage progress and diagnostic activities

Every non-heartbeat SSE frame has an `id`:

```text
id: 12-0
data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"answer-1","delta":"Hi"}

```

## Idempotency and resubscription

Within one Sage Server process, `(authenticated user, runId)` identifies a run.
Sending the same `runId` and `threadId` again subscribes to the existing run and
does not start the model twice. Binding that pair to a different thread returns
HTTP 409.

Send the last received SSE id in the `Last-Event-ID` request header to replay
later buffered events:

```http
Last-Event-ID: 12-0
```

The response includes `X-Sage-AG-UI-Replay: process-local`. This qualifier is
important: V2 uses a bounded, 24-hour, process-memory delivery buffer. It keeps
the background run alive when an HTTP subscriber disconnects, but it does not
provide Redis-backed cross-worker or post-restart replay. Conversation messages
are still persisted by Sage's existing session/conversation storage and remain
the business source of truth.

## Errors

- HTTP 401: no authenticated Sage identity.
- HTTP 404: `threadId` belongs to another user.
- HTTP 409: `runId` is already bound to another AG-UI thread for that user, or
  the Sage thread already has an active run.
- HTTP 422: missing `forwardedProps.agentId`, no user message, or an invalid
  forwarded property.

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
