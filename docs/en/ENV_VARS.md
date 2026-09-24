---
layout: default
title: Environment Variables
nav_order: 9
lang: en
ref: v2-ENV_VARS
---

{% include lang_switcher.html %}

# Environment Variables

## Server v2

`python -m app.server_v2` reads `app/server_v2/.env`; process environment variables take precedence. The source of truth is [ServerSettings](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/core/settings.py).

| Variable | Default / role |
| --- | --- |
| `SAGE_SERVER_MYSQL_URL` | Required MySQL connection URL |
| `SAGE_SERVER_HOST` | `127.0.0.1` |
| `SAGE_SERVER_PORT` | `8090` |
| `SAGE_SERVER_DATA` | `data/server_v2` |
| `SAGE_SERVER_LANGUAGE` | `zh` |
| `SAGE_SERVER_JWT_SECRET` | Configure your own secret, at least 32 bytes |
| `SAGE_SERVER_JWT_EXPIRE_HOURS` | `72` |
| `SAGE_SERVER_ADMIN_USERNAME` | `admin` (initial administrator) |
| `SAGE_SERVER_ADMIN_PASSWORD` | `admin12345` (replace before deployment) |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS` | `8` |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER` | `2` |
| `SAGE_SERVER_MAX_PENDING_RUNS` | `1024` |
| `SAGE_SERVER_MAX_MODEL_CLIENTS` | `64` |
| `SAGE_SERVER_MAX_MANAGED_APPLICATIONS` | `32` |
| `SAGE_SERVER_MAX_MANAGED_BUILDS` | `4` |
| `SAGE_SERVER_LOG_LEVEL` | `info` |
| `SAGE_SERVER_LOG_FORMAT` | `json` (`text` also supported) |
| `SAGE_SERVER_LOG_DIRECTORY` | Optional |
| `SAGE_SERVER_JAEGER_URL` | Optional OTLP endpoint |
| `SAGE_SERVER_JAEGER_SERVICE_NAME` | `sage-server` |
| `SAGE_SERVER_JAEGER_PUBLIC_URL` | `http://127.0.0.1:16686/jaeger` |

Concurrency and capacity values must be positive. They are per-process limits, not distributed quotas. Redis is no longer a startup dependency or AG-UI replay store.

## Desktop and embedded runtime

Desktop v2 reads persisted settings, not environment overrides for Agents/models. Use the backend's `--data-root` argument for an isolated source-debug data directory.

Embedded packages declare credential environment names explicitly. `MODEL_API_KEY` in the quick start is selected by its manifest, not a universal runtime setting. Legacy `SAGE_DEFAULT_*` variables do not configure this example.
