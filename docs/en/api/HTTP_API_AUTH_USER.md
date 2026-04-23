---
layout: default
title: Auth and users
parent: HTTP API Reference
nav_order: 1
description: "Deployment modes, sessions, local/OIDC, admin user APIs, compatibility paths"
lang: en
ref: http-api-auth
---

{% include lang_switcher.html %}

# Auth and users

Routers: `app/server/routers/auth.py`, `app/server/routers/user.py`. Middleware and allowlists: `app/server/core/middleware.py`.

## How deployment mode changes behavior

The platform can run in combinations such as `native` (local accounts + email), `trusted_proxy` (identity injected in front), `oauth`, etc. Typical differences:

- **Registration and email codes** under `/api/auth/register*` and legacy `/api/user/register*` are only available when local registration is enabled; otherwise the API returns 400-style business errors (see the main doc).
- **Password login** may be open in `native` and `trusted_proxy`, but `trusted_proxy` often **restricts logins to admins** while normal users come from upstream / SSO.
- **`GET /api/auth/session`** is the main way the web app decides whether a user is logged in and onboarded.

## Integration patterns

1. **First-party browser app**: use **session cookies** (`withCredentials: true` / `curl -c`) like the built-in web UI. Do not assume an OAuth2 `access_token` alone unlocks all product routes—most admin APIs rely on the server session (see the main “Quick rules” table).
2. **M2M / third-party systems**: use the **OAuth2 authorization server** and/or your IdP, then `trusted_proxy` if applicable—different contract from `POST /api/auth/login`. For a worked example (doc is Chinese-only today), see [OAuth2 Lage integration guide](../zh/OAUTH2_LAGE_INTEGRATION.md).
3. **User preferences**: `GET/POST /api/user/config` is **per user**, not the same as **system** settings in `POST /api/system/update_settings` (admin only).

## `/api/auth` vs legacy `/api/user`

Prefer `/api/auth/*` in new code. The `/api/user/*` mirror exists for old clients. Avoid mixing the two in one flow unless you are writing a compatibility layer.

## Admin and roles

- `list/add/delete` user APIs require the **admin** role.
- Password change, options, etc. are for the **current** user, separate from admin tools.

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
