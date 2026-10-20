---
layout: default
title: 环境变量
nav_order: 9
lang: zh
ref: v2-ENV_VARS
---

{% include lang_switcher.html %}

# 环境变量

## Server

`python -m app.v2.server` 读取 `app/v2/server/.env`，进程环境变量优先。默认值以 [ServerSettings](https://github.com/ZHangZHengEric/Sage/blob/main/app/v2/server/config/settings.py) 为准。

| 变量 | 默认值 / 用途 |
| --- | --- |
| `SAGE_SERVER_REDIS_URL` | 可选的 Session 归档 Redis 地址；需要同时配置 MySQL。 |
| `SAGE_SERVER_MYSQL_URL` | 必须配置的 MySQL 连接地址 |
| `SAGE_SERVER_HOST` | `127.0.0.1` |
| `SAGE_SERVER_PORT` | `8090` |
| `SAGE_SERVER_DATA` | `data/server_v2` |
| `SAGE_SERVER_LANGUAGE` | `zh` |
| `SAGE_SERVER_JWT_SECRET` | 配置自己的密钥，至少 32 字节 |
| `SAGE_SERVER_JWT_EXPIRE_HOURS` | `72` |
| `SAGE_SERVER_ADMIN_USERNAME` | `admin` (初始管理员) |
| `SAGE_SERVER_ADMIN_PASSWORD` | `admin12345` (部署前修改) |
| `SAGE_SERVER_EXECUTION_SHELL_MODE` | `sandboxed`；可选 `ask` / `sandboxed` / `deny` |
| `SAGE_SERVER_LINUX_EXECUTION_UID` | 默认未设置；Linux 沙箱执行用户 ID。须与 GID 一起设置，两者均须为 `1` 至 `4294967294` 的整数（非 root）。 |
| `SAGE_SERVER_LINUX_EXECUTION_GID` | 默认未设置；Linux 沙箱执行组 ID。须与 UID 一起设置，两者均须为 `1` 至 `4294967294` 的整数（非 root）。 |
| `SAGE_SERVER_APPROVAL_TIMEOUT_SECONDS` | `86400` 秒 |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS` | `8` |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER` | `2` |
| `SAGE_SERVER_MAX_PENDING_RUNS` | `1024` |
| `SAGE_SERVER_MAX_MODEL_CLIENTS` | `64` |
| `SAGE_SERVER_MAX_MANAGED_APPLICATIONS` | `32` |
| `SAGE_SERVER_MAX_MANAGED_BUILDS` | `4` |
| `SAGE_SERVER_LOG_LEVEL` | `info` |
| `SAGE_SERVER_LOG_FORMAT` | `json` （也支持 `text`） |
| `SAGE_SERVER_LOG_DIRECTORY` | `./logs` |
| `SAGE_SERVER_JAEGER_URL` | 可选 OTLP 地址 |
| `SAGE_SERVER_JAEGER_SERVICE_NAME` | `sage-server` |
| `SAGE_SERVER_JAEGER_PUBLIC_URL` | `http://127.0.0.1:16686/jaeger` |
| `SAGE_SERVER_TRACE_BACKEND` | 默认空：配置 `JAEGER_URL` 时使用 OTLP，否则为 `noop`；可选 `noop`、`otlp`、`langfuse`、`phoenix` |
| `SAGE_SERVER_TRACE_OTLP_ENDPOINT` | 默认空；回退到旧 Jaeger 地址 |
| `SAGE_SERVER_TRACE_OTLP_PROTOCOL` | `grpc`；可选 `grpc` 或 `http` |
| `SAGE_SERVER_TRACE_OTLP_INSECURE` | `false`；仅明文 gRPC 时启用 |
| `SAGE_SERVER_TRACE_SERVICE_NAME` | `sage-server` |
| `SAGE_SERVER_TRACE_ENVIRONMENT` | `production` |
| `SAGE_SERVER_TRACE_CONTENT_MODE` | `redacted`；可选 `redacted` 或 `metadata` |
| `SAGE_SERVER_TRACE_MAX_CONTENT_CHARS` | `16384`；范围 256–65536 字符 |
| `SAGE_SERVER_TRACE_SAMPLE_RATE` | `1`；范围 0–1 |
| `SAGE_SERVER_TRACE_TIMEOUT_SECONDS` | `3`；大于 0 且不超过 30 秒 |
| `SAGE_SERVER_TRACE_QUERY_URL` | 默认空；Trace 查询地址，未设置时使用已配置后端的地址 |
| `SAGE_SERVER_TRACE_QUERY_HEADERS_ENV` | `OTEL_EXPORTER_OTLP_TRACES_HEADERS`；保存 Trace 查询请求头的环境变量名 |
| `SAGE_SERVER_LANGFUSE_BASE_URL` | 默认空；使用 Langfuse 后端时必填 |
| `SAGE_SERVER_LANGFUSE_PUBLIC_URL` | 默认空；可选项目控制台地址 |
| `SAGE_SERVER_LANGFUSE_PUBLIC_KEY_ENV` | `LANGFUSE_PUBLIC_KEY`；保存公钥的环境变量名 |
| `SAGE_SERVER_LANGFUSE_SECRET_KEY_ENV` | `LANGFUSE_SECRET_KEY`；保存私钥的环境变量名 |
| `SAGE_SERVER_LANGFUSE_INGESTION_VERSION` | `4`；可选 `3` 或 `4` |
| `SAGE_SERVER_PHOENIX_ENDPOINT` | 默认空；用于 Trace 导出和查询的 Phoenix 地址 |
| `SAGE_SERVER_PHOENIX_PUBLIC_URL` | 默认空；可选的 Phoenix 公开控制台地址 |
| `SAGE_SERVER_PHOENIX_PROJECT_NAME` | `sage`；Phoenix 项目名 |
| `SAGE_SERVER_PHOENIX_API_KEY_ENV` | `PHOENIX_API_KEY`；保存 Phoenix API 密钥的环境变量名 |
| `SAGE_SERVER_PUBLIC_URL` | 默认空：使用请求来源地址；反向代理后的 A2A 应设置公开来源地址 |

并发和容量参数必须为正数，约束单进程，不是分布式配额。Redis 不再是启动依赖或 AG-UI 回放存储。

## Desktop 与嵌入式运行时

Desktop 读取持久化设置，不通过环境变量覆盖 Agent/模型。需要隔离源码调试数据时，使用后端 `--data-root` 参数。

嵌入式包显式声明凭据来源变量名。快速开始中的 `MODEL_API_KEY` 由该 manifest 选择，不是全局固定配置。旧版 `SAGE_DEFAULT_*` 变量不配置此示例。
