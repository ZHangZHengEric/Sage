---
layout: default
title: Troubleshooting
nav_order: 13
description: "Common Sage setup and runtime issues"
lang: en
ref: troubleshooting
---

{% include lang_switcher.html %}

# Troubleshooting

## The server starts but model calls fail

Check the default model settings:

- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_DEFAULT_LLM_API_BASE_URL`
- `SAGE_DEFAULT_LLM_MODEL_NAME`

These are the most common missing variables during first run.

## The web app loads but cannot reach the backend

Verify both sides are running:

- backend: `python -m app.server.main`
- frontend: `cd app/server/web && npm run dev`

Then verify the frontend is configured to talk to the correct API base URL.

The frontend variables to check first are:

- `VITE_SAGE_API_BASE_URL`
- `VITE_SAGE_WEB_BASE_PATH`

## Desktop startup behaves differently from the server

That is expected. The desktop app uses a separate bootstrap path:

- `app/desktop/entry.py`
- `app/desktop/core/main.py`

It binds to `127.0.0.1` and includes desktop-specific startup behavior.

## Sandbox behavior is not what you expect

Check:

- `SAGE_SANDBOX_MODE`
- `SAGE_REMOTE_PROVIDER`
- `SAGE_SANDBOX_MOUNT_PATHS`

Also remember that `SAgent.run_stream(...)` can override the default sandbox mode per session.

## Session files or agent files are not where you expect

Review the storage-related variables:

- `SAGE_SESSION_DIR`
- `SAGE_AGENTS_DIR`
- `SAGE_USER_DIR`
- `SAGE_SKILL_WORKSPACE`

## Observability pages or traces are missing

Check the Jaeger-related variables:

- `SAGE_TRACE_JAEGER_ENDPOINT`
- `SAGE_TRACE_JAEGER_UI_URL`
- `SAGE_TRACE_JAEGER_PUBLIC_URL`
- `SAGE_TRACE_JAEGER_BASE_PATH`

## There is a mismatch between docs and code

Trust the code. Start with:

- `app/server/main.py`
- `app/server/core/config.py`
- `app/server/routers/`
- `sagents/sagents.py`

This documentation set is intentionally optimized for current accuracy, but the repository is active and can change faster than prose.
