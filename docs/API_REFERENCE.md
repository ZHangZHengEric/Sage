---
layout: default
title: API Reference
nav_order: 8
description: "Main HTTP route groups in the current server"
---

# API Reference

## Scope

This page summarizes the primary route groups registered by `app/server/routers/__init__.py`. It is intended as a map of the API surface, not a field-by-field schema listing.

Use this page to find the right router module quickly. Use the router and schema files when you need request or response details.

## Service Health and System

- `GET /api/health`
- `GET /api/system/info`
- `POST /api/system/update_settings`
- `GET /active`

`GET /api/health` is the standard first endpoint to test after startup.

## Chat and Streaming

Defined primarily in `app/server/routers/chat.py`.

- `POST /api/chat`
- `POST /api/stream`
- `POST /api/web-stream`
- `GET /api/stream/resume/{session_id}`
- `GET /api/stream/active_sessions`

These endpoints are the runtime-facing chat transport layer. Streaming responses are returned as `text/plain`.

## Main Route Groups

- `/api/auth`
- `/api/agent`
- chat and streaming endpoints from the chat router
- `/api/tools`
- `/api/skills`
- `/api/knowledge-base`
- `/api/mcp`
- `/api/oss`
- `/api/user`
- `/api/llm-provider`
- `/api/observability`
- `/api/system/version`
- OAuth2 endpoints from `app/server/routers/oauth2.py`

## What Each Group Covers

- `agent`: create, list, update, authorize, and manage agent configurations
- `chat`: streaming chat session execution and resume flows
- `auth` and `oauth2`: login and identity-provider flows
- `tools` and `skills`: inspect and manage available extensions
- `knowledge-base`: knowledge base and retrieval-related operations
- `mcp`: MCP server integration management
- `oss`: file and object storage access
- `user`: user and profile operations
- `llm-provider`: configured model provider management
- `observability`: tracing and observability-facing endpoints

## Source Files

- `app/server/routers/chat.py`
- `app/server/routers/agent.py`
- `app/server/routers/auth.py`
- `app/server/routers/conversation.py`
- `app/server/routers/kdb.py`
- `app/server/routers/mcp.py`
- `app/server/routers/skill.py`
- `app/server/routers/tool.py`
- `app/server/routers/user.py`
- `app/server/routers/system.py`
- `app/server/routers/version.py`
- `app/server/routers/llm_provider.py`
- `app/server/routers/observability.py`
- `app/server/routers/oauth2.py`

## Recommendation

For endpoint-level implementation details, read the router and matching schema modules together:

- `app/server/routers/`
- `app/server/schemas/`
- `app/server/services/`

If you are debugging behavior rather than contract shape, start from the router and then move into the corresponding service module.
