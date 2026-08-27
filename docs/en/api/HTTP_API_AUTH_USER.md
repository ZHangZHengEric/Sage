---
layout: default
title: Auth and users
parent: HTTP API Reference
nav_order: 1
description: "Local account sessions, registration, admin user APIs, compatibility paths"
lang: en
ref: http-api-auth
---

{% include lang_switcher.html %}

# Auth and users

Routers: `app/server/routers/auth.py`, `app/server/routers/user.py`. Middleware and allowlists: `app/server/core/middleware.py`.

## Local account behavior

- **Self-registration** under `/api/auth/register` and legacy `/api/user/register` accepts only `username` and `password` when registration is enabled.
- **Password login** accepts the same `username` and `password` identity.
- **`GET /api/auth/session`** is the main way the web app decides whether a user is logged in and onboarded.

## Integration patterns

1. **First-party browser app**: use **session cookies** (`withCredentials: true` / `curl -c`) like the built-in web UI.
2. **User preferences**: `GET/POST /api/user/config` is **per user**, not the same as **system** settings in `POST /api/system/update_settings` (admin only).

## `/api/auth` vs legacy `/api/user`

Prefer `/api/auth/*` in new code. The `/api/user/*` mirror exists for old clients. Avoid mixing the two in one flow unless you are writing a compatibility layer.

## Admin and roles

- `list/add/delete` user APIs require the **admin** role.
- Password change, options, etc. are for the **current** user, separate from admin tools.

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
