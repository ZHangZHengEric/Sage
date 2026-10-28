---
layout: default
title: Environment Variables
nav_order: 9
lang: en
ref: v2-ENV_VARS
---

{% include lang_switcher.html %}

# Environment Variables

## Server

`python -m app.v2.server` reads `app/v2/server/.env`; process environment variables take precedence. The source of truth is [ServerSettings](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/config/settings.py).

| Variable | Default / role |
| --- | --- |
| `SAGE_SERVER_REDIS_URL` | Optional Redis URL for Session archival; requires MySQL. |
| `SAGE_SERVER_SESSION_STORE_PLUGIN` | Unset: select MySQL or Redis/MySQL from configured URLs. `sage.session.redis-mysql` supports shared state across instances. |
| `SAGE_SERVER_SCHEDULER_PLUGIN` | `sage.scheduler.ephemeral`; select `sage.scheduler.redis-distributed` explicitly for shared Run scheduling and `sage.job.redis-distributed`. Requires MySQL and Redis. Workspace files remain node-local. |
| `SAGE_SERVER_SESSION_STORE_KEY_PREFIX` | Optional explicit Redis Session namespace; all instances sharing sessions must use the same prefix. |
| `SAGE_SERVER_MYSQL_URL` | Required MySQL connection URL |
| `SAGE_SERVER_HOST` | `127.0.0.1` |
| `SAGE_SERVER_PORT` | `8090` |
| `SAGE_SERVER_DATA` | `data/server_v2` |
| `SAGE_SERVER_LANGUAGE` | `zh` |
| `SAGE_SERVER_JWT_SECRET` | Configure your own secret, at least 32 bytes |
| `SAGE_SERVER_JWT_EXPIRE_HOURS` | `72` |
| `SAGE_SERVER_ADMIN_USERNAME` | `admin` (initial administrator) |
| `SAGE_SERVER_ADMIN_PASSWORD` | `admin12345` (replace before deployment) |
| `SAGE_SERVER_EXECUTION_SHELL_MODE` | `sandboxed`; `ask` / `sandboxed` / `deny` |
| `SAGE_SERVER_LINUX_EXECUTION_UID` | Unset; Linux sandbox execution user ID. Set together with GID; both must be integers from `1` to `4294967294` (non-root). |
| `SAGE_SERVER_LINUX_EXECUTION_GID` | Unset; Linux sandbox execution group ID. Set together with UID; both must be integers from `1` to `4294967294` (non-root). |
| `SAGE_SERVER_APPROVAL_TIMEOUT_SECONDS` | `86400` seconds |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS` | `8` |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER` | `2` |
| `SAGE_SERVER_MAX_PENDING_RUNS` | `1024` |
| `SAGE_SERVER_MAX_MODEL_CLIENTS` | `64` |
| `SAGE_SERVER_MAX_MANAGED_APPLICATIONS` | `32` |
| `SAGE_SERVER_MAX_MANAGED_BUILDS` | `4` |
| `SAGE_SERVER_LOG_LEVEL` | `info` |
| `SAGE_SERVER_LOG_FORMAT` | `json` (`text` also supported) |
| `SAGE_SERVER_LOG_DIRECTORY` | `./logs` |
| `SAGE_SERVER_JAEGER_URL` | Optional OTLP endpoint |
| `SAGE_SERVER_JAEGER_SERVICE_NAME` | `sage-server` |
| `SAGE_SERVER_JAEGER_PUBLIC_URL` | `http://127.0.0.1:16686/jaeger` |
| `SAGE_SERVER_TRACE_BACKEND` | Empty: use OTLP when `JAEGER_URL` is configured, otherwise `noop`; select `noop`, `otlp`, `langfuse`, or `phoenix` |
| `SAGE_SERVER_TRACE_OTLP_ENDPOINT` | Empty; falls back to the legacy Jaeger endpoint |
| `SAGE_SERVER_TRACE_OTLP_PROTOCOL` | `grpc`; `grpc` or `http` |
| `SAGE_SERVER_TRACE_OTLP_INSECURE` | `false`; enable only for plaintext gRPC |
| `SAGE_SERVER_TRACE_SERVICE_NAME` | `sage-server` |
| `SAGE_SERVER_TRACE_ENVIRONMENT` | `production` |
| `SAGE_SERVER_TRACE_CONTENT_MODE` | `redacted`; `redacted` or `metadata` |
| `SAGE_SERVER_TRACE_MAX_CONTENT_CHARS` | `16384`; between 256 and 65536 characters |
| `SAGE_SERVER_TRACE_SAMPLE_RATE` | `1`; between 0 and 1 |
| `SAGE_SERVER_TRACE_TIMEOUT_SECONDS` | `3`; greater than 0 and at most 30 seconds |
| `SAGE_SERVER_TRACE_QUERY_URL` | Empty; trace query endpoint, falling back to the configured backend endpoint |
| `SAGE_SERVER_TRACE_QUERY_HEADERS_ENV` | `OTEL_EXPORTER_OTLP_TRACES_HEADERS`; environment variable containing trace query headers |
| `SAGE_SERVER_LANGFUSE_BASE_URL` | Empty; required for the Langfuse backend |
| `SAGE_SERVER_LANGFUSE_PUBLIC_URL` | Empty; optional project console URL |
| `SAGE_SERVER_LANGFUSE_PUBLIC_KEY_ENV` | `LANGFUSE_PUBLIC_KEY`; environment variable containing the public key |
| `SAGE_SERVER_LANGFUSE_SECRET_KEY_ENV` | `LANGFUSE_SECRET_KEY`; environment variable containing the secret key |
| `SAGE_SERVER_LANGFUSE_INGESTION_VERSION` | `4`; `3` or `4` |
| `SAGE_SERVER_PHOENIX_ENDPOINT` | Empty; Phoenix endpoint for trace export and queries |
| `SAGE_SERVER_PHOENIX_PUBLIC_URL` | Empty; optional public Phoenix console URL |
| `SAGE_SERVER_PHOENIX_PROJECT_NAME` | `sage`; Phoenix project name |
| `SAGE_SERVER_PHOENIX_API_KEY_ENV` | `PHOENIX_API_KEY`; environment variable containing the Phoenix API key |
| `SAGE_SERVER_PUBLIC_URL` | Empty: A2A uses the request origin; IM connection creation requires a fixed public HTTPS base |

Concurrency and capacity values must be positive. Run limits are per process with the default Scheduler and shared across instances with the distributed Scheduler. The distributed Job plugin has its own shared admission, execution and output bounds. Redis is required when selecting the Redis runtime plugins; local workspaces and memory databases are not made cross-node by that selection.

## Desktop and embedded runtime

Desktop reads persisted settings, not environment overrides for Agents/models. Use the backend's `--data-root` argument for an isolated source-debug data directory.

Embedded packages declare credential environment names explicitly. `MODEL_API_KEY` in the quick start is selected by its manifest, not a universal runtime setting. Legacy `SAGE_DEFAULT_*` variables do not configure this example.
