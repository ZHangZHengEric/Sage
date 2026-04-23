---
layout: default
title: Platform, storage, and observability
parent: HTTP API Reference
nav_order: 7
description: "LLM providers, system, versions, OSS, Jaeger, liveness, OAuth2 and links"
lang: en
ref: http-api-platform
---

{% include lang_switcher.html %}

# Platform, storage, and observability

Routers: `llm_provider.py`, `system.py`, `oss.py`, `version.py`, `observability.py`. The root liveness `GET /active` is registered in `app/server/main.py`, not under `/api`.

## LLM provider (`/api/llm-provider/...`)

- `verify` vs `verify-capabilities` vs `verify-multimodal` answer different questions: connectivity, capability probing, and image probes.
- `create` returns `data: {"provider_id": ...}`; use that id in `update` and `delete`.
- Default providers are protected on delete; see the main doc’s business-error examples.

## System and usage stats

- `GET /api/system/info` is used by the SPA to decide registration/login options—do not assume it exposes secret keys.
- `POST /api/system/update_settings` is **admin**-only.
- `POST /api/system/agent/usage-stats` is per-user usage with `days` and optional `agent_id`.

## Version endpoints (`/api/system/version*`)

- `.../check` and `.../latest` are for different client surfaces (desktop vs web) with different response models.
- `POST/GET/DELETE` for version records are product metadata, not a guarantee of image tags in your cluster.

## OSS upload

- `POST /api/oss/upload` backs user uploads. Desktop builds may return paths that the UI later maps locally—treat the response schema as part of the contract you test against, not a universal HTTPS URL.

## Jaeger and observability

- `/api/observability/jaeger* ` routes handle redirects and auth; expect HTML flows for admins and possible `503` when local login is not available.

## Liveness: `GET /active` vs `GET /api/health`

- `/active` is **plain text**; `/api/health` returns a JSON `BaseResponse`. Use them for different kinds of checks (LB vs in-app health).

## OAuth2 vs `/api/auth`

- The OAuth2 surface (`/oauth2/*` and `/api/oauth2/*`) is for **standards-based clients** (metadata, `authorize`, `token`, `userinfo`). Your browser’s username/password form is a different path—see [Auth and users](HTTP_API_AUTH_USER.md) and, for a full third-party example, the repo’s [OAUTH2_LAGE_INTEGRATION.md](OAUTH2_LAGE_INTEGRATION.md) (Chinese, still useful for request shapes).

[Back to HTTP API Reference](HTTP_API_REFERENCE.md)
