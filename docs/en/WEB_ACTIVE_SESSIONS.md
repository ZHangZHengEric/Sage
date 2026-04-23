---
layout: default
title: Web Active Sessions
nav_order: 12
description: "How the web app connects to the active-sessions SSE stream"
lang: en
---

{% include lang_switcher.html %}

# Web Active Sessions Integration Guide

This page explains two things:

1. How the desktop frontend currently discovers active sessions.
2. How the web frontend can provide the same behavior using the existing backend API.

## Goal

We want the web app to behave like the desktop app:

- while a session is running, show it in the sidebar automatically
- refresh the sidebar when the session ends
- let the user jump back into the live session from the sidebar
- keep `last_index` so resumed streaming continues from the right position

## Backend Contract

The backend already exposes:

- route: `GET /api/stream/active_sessions`
- response: `text/event-stream`
- event format: each push is `data: <json>\n\n`

Implementation lives in `app/server/routers/chat.py`.

Important behavior:

- the connection sends a full snapshot immediately after connect
- the full snapshot is pushed again when the active session list changes
- the client should treat each snapshot as the source of truth

## Desktop Behavior

The desktop implementation is split into four layers:

1. Sidebar mount starts the subscription.
2. A shared cache keeps `activeSessions`, offsets, and the SSE source.
3. Native `EventSource` is used.
4. The sidebar only renders and routes to the session.

That design keeps the sidebar live as long as the UI shell is present.

## Web Difference

The main web difference is authentication.

The web request layer adds a bearer token header automatically, but browser-native `EventSource` cannot add custom headers. For this reason, the web side should use a streamed `fetch`-style reader and parse SSE manually.

## Recommended Web Layout

### 1. API layer

Create a `subscribeActiveSessions` helper in:

- `app/server/web/src/api/chat.js`

It should:

- call the existing authenticated streaming request helper
- parse `data:` lines from the SSE stream
- expose a lightweight `onmessage` / `onerror` / `close()` interface

### 2. State layer

Keep a shared cache for:

- `activeSessions`
- `sessionStreamOffsets`
- `sseSource`
- `subscriberCount`

When a snapshot arrives:

1. normalize records for the UI
2. preserve existing `last_index`
3. mark missing live sessions as completed
4. update local storage
5. notify the UI with a custom event

### 3. Lifecycle layer

The most important integration point is where the SSE subscription starts.

If the subscription only lives inside the Chat page, it stops when the user leaves the page. If it lives in the sidebar shell, the list stays fresh as long as the app is open.

### 4. Sidebar layer

The sidebar should only:

- render the active session list
- sort by `lastUpdate`
- show status
- route into `Chat?session_id=...`

## Suggested Product Behavior

- start the subscription when the app shell loads
- keep it alive while the app is open
- treat the active session list as a real-time sidebar index

