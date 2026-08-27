---
layout: default
title: Configuration
nav_order: 5
description: "Environment variables and runtime configuration"
lang: en
ref: configuration
---

{% include lang_switcher.html %}

# Configuration

## Source of Truth

The primary configuration source is `app/server/core/config.py`, which builds a `StartupConfig` from environment variables and defaults.

When documentation and behavior disagree, treat `app/server/core/config.py` as authoritative.

## Minimum Required Settings

These are the settings you normally need first:

- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_DEFAULT_LLM_API_BASE_URL`
- `SAGE_DEFAULT_LLM_MODEL_NAME`

For many local runs, these three variables plus `SAGE_PORT` are enough.

## Server and Storage

- `SAGE_PORT`
- `SAGE_SESSION_DIR`
- `SAGE_LOGS_DIR_PATH`
- `SAGE_AGENTS_DIR`
- `SAGE_USER_DIR`
- `SAGE_SKILL_WORKSPACE`

These control where Sage writes runtime state, sessions, agents, and skill workspace data.

## Database

- `SAGE_DB_TYPE`
- `SAGE_MYSQL_HOST`
- `SAGE_MYSQL_PORT`
- `SAGE_MYSQL_USER`
- `SAGE_MYSQL_PASSWORD`
- `SAGE_MYSQL_DATABASE`

`SAGE_DB_TYPE` supports `file`, `memory`, and `mysql`.

## Default Model Configuration

- `SAGE_DEFAULT_LLM_MAX_TOKENS`
- `SAGE_DEFAULT_LLM_TEMPERATURE`
- `SAGE_DEFAULT_LLM_MAX_MODEL_LEN`
- `SAGE_DEFAULT_LLM_TOP_P`
- `SAGE_DEFAULT_LLM_PRESENCE_PENALTY`

## Context Budget

- `SAGE_CONTEXT_HISTORY_RATIO`
- `SAGE_CONTEXT_ACTIVE_RATIO`
- `SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO`
- `SAGE_CONTEXT_COMPRESSION_THRESHOLD` (default `0.85`; input-only threshold for persistent model-generated history summaries, independent of output token limits)
- `SAGE_CONTEXT_RECENT_TURNS`

## Authentication and Session

- `SAGE_BOOTSTRAP_ADMIN_USERNAME`
- `SAGE_BOOTSTRAP_ADMIN_PASSWORD`
- `SAGE_JWT_KEY`
- `SAGE_JWT_EXPIRE_HOURS`
- `SAGE_REFRESH_TOKEN_SECRET`
- `SAGE_SESSION_SECRET`
- `SAGE_SESSION_COOKIE_NAME`
- `SAGE_SESSION_COOKIE_SECURE`
- `SAGE_SESSION_COOKIE_SAME_SITE`
- `SAGE_CORS_ALLOWED_ORIGINS`
- `SAGE_CORS_ALLOW_CREDENTIALS`
- `SAGE_CORS_ALLOW_METHODS`
- `SAGE_CORS_ALLOW_HEADERS`
- `SAGE_CORS_EXPOSE_HEADERS`
- `SAGE_CORS_MAX_AGE`
- `SAGE_WEB_BASE_PATH`

Sage uses built-in local accounts. Login and self-registration both use only a username and password.

Sage keeps CORS configurable with safe defaults:

- `SAGE_CORS_ALLOWED_ORIGINS`: comma-separated origin allowlist, default `*`
- `SAGE_CORS_ALLOW_CREDENTIALS`: whether browser credentials are allowed, default `false`
- `SAGE_CORS_ALLOW_METHODS`: comma-separated method allowlist, default `*`
- `SAGE_CORS_ALLOW_HEADERS`: comma-separated request-header allowlist, default `*`
- `SAGE_CORS_EXPOSE_HEADERS`: comma-separated response headers exposed to the browser, default empty
- `SAGE_CORS_MAX_AGE`: preflight cache TTL in seconds, default `600`

The default shape is public CORS with `*` and no browser credentials. If you enable `SAGE_CORS_ALLOW_CREDENTIALS=true`, wildcard origin `*` is rejected and you must configure explicit origins.

`SAGE_BOOTSTRAP_ADMIN_USERNAME` and `SAGE_BOOTSTRAP_ADMIN_PASSWORD` are both optional, but they now work as an explicit opt-in pair. If either one is missing, Sage will not create a bootstrap admin user during startup.

## Embeddings, Search, and Object Storage

- `SAGE_EMBEDDING_API_KEY`
- `SAGE_EMBEDDING_BASE_URL`
- `SAGE_EMBEDDING_MODEL`
- `SAGE_EMBEDDING_DIMS`
- `SAGE_ELASTICSEARCH_URL`
- `SAGE_ELASTICSEARCH_API_KEY`
- `SAGE_ELASTICSEARCH_USERNAME`
- `SAGE_ELASTICSEARCH_PASSWORD`
- `SAGE_S3_ENDPOINT`
- `SAGE_S3_ACCESS_KEY`
- `SAGE_S3_SECRET_KEY`
- `SAGE_S3_SECURE`
- `SAGE_S3_BUCKET_NAME`
- `SAGE_S3_PUBLIC_BASE_URL`

You only need these when you enable knowledge-base, search, embedding, or object-storage-backed features.

## Observability

- `SAGE_TRACE_JAEGER_ENDPOINT`
- `SAGE_TRACE_JAEGER_PUBLIC_URL`

These are optional unless you actively run observability infrastructure.

## Sandbox and Runtime Safety

These settings are consumed by the runtime outside the main server config object:

- `SAGE_SANDBOX_MODE`
- `SAGE_REMOTE_PROVIDER`
- `SAGE_SANDBOX_MOUNT_PATHS`
- `SAGE_LOCAL_CPU_TIME_LIMIT`
- `SAGE_LOCAL_MEMORY_LIMIT_MB`
- `SAGE_LOCAL_LINUX_ISOLATION`
- `SAGE_LOCAL_MACOS_ISOLATION`
- `SAGE_USE_CLAW_MODE`

Most local users can start with `SAGE_SANDBOX_MODE=local` and leave the rest at defaults.
The multi-user server requires Linux `bwrap` for `local` mode and fails closed
for `passthrough`; use a remote sandbox on platforms without that boundary.

## Frontend Environment

The web client also reads frontend-specific Vite variables:

- `VITE_SAGE_API_BASE_URL`
- `VITE_SAGE_WEB_BASE_PATH`

## Example `.env`

```env
SAGE_PORT=8080
SAGE_DEFAULT_LLM_API_KEY=your-api-key
SAGE_DEFAULT_LLM_API_BASE_URL=https://api.deepseek.com/v1
SAGE_DEFAULT_LLM_MODEL_NAME=deepseek-chat
SAGE_DB_TYPE=file
SAGE_SESSION_DIR=sessions
SAGE_AGENTS_DIR=agents
SAGE_BOOTSTRAP_ADMIN_USERNAME=admin
SAGE_BOOTSTRAP_ADMIN_PASSWORD=change-this-before-first-run
SAGE_SANDBOX_MODE=local
```

## Recommendation

Start with the model variables, `SAGE_PORT`, and local storage directories. Add auth, database, object storage, embedding, or observability settings only when those subsystems are actually in use.
