---
layout: default
title: Platform and Observability
nav_order: 3
lang: en
ref: v2-api-HTTP_API_PLATFORM
parent: API
---

{% include lang_switcher.html %}

# Platform and Observability

- `GET /health` and `GET /active` report service health and actual backend selections.
- Server logs use `sage.log/v1` JSON lines by default. Configure level, format, and optional directory with `SAGE_SERVER_LOG_*`.
- Request correlation uses `X-Request-ID`; JSON responses also include `request_id`.
- Optional Jaeger integration uses `SAGE_SERVER_JAEGER_*`; it is not required to run chat.
- Session state is authoritative. Diagnostic files and log retention must not be used to reconstruct a second message ledger.

Server v2 uses MySQL for application inventory and Session persistence, and Session events for AG-UI replay. Desktop uses its own local data root and catalog. Neither host uses the legacy desktop-update API.

[Environment variables](../ENV_VARS.md) · [Server component](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/README.md)
