---
layout: default
title: 环境变量
nav_order: 9
lang: zh
ref: v2-ENV_VARS
---

{% include lang_switcher.html %}

# 环境变量

## Server v2

`python -m app.server_v2` 读取 `app/server_v2/.env`，进程环境变量优先。默认值以 [ServerSettings](https://github.com/ZHangZHengEric/Sage/blob/main/app/server_v2/config/settings.py) 为准。

| 变量 | 默认值 / 用途 |
| --- | --- |
| `SAGE_SERVER_MYSQL_URL` | 必须配置的 MySQL 连接地址 |
| `SAGE_SERVER_HOST` | `127.0.0.1` |
| `SAGE_SERVER_PORT` | `8090` |
| `SAGE_SERVER_DATA` | `data/server_v2` |
| `SAGE_SERVER_LANGUAGE` | `zh` |
| `SAGE_SERVER_JWT_SECRET` | 配置自己的密钥，至少 32 字节 |
| `SAGE_SERVER_JWT_EXPIRE_HOURS` | `72` |
| `SAGE_SERVER_ADMIN_USERNAME` | `admin` (初始管理员) |
| `SAGE_SERVER_ADMIN_PASSWORD` | `admin12345` (部署前修改) |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS` | `8` |
| `SAGE_SERVER_MAX_CONCURRENT_RUNS_PER_USER` | `2` |
| `SAGE_SERVER_MAX_PENDING_RUNS` | `1024` |
| `SAGE_SERVER_MAX_MODEL_CLIENTS` | `64` |
| `SAGE_SERVER_MAX_MANAGED_APPLICATIONS` | `32` |
| `SAGE_SERVER_MAX_MANAGED_BUILDS` | `4` |
| `SAGE_SERVER_LOG_LEVEL` | `info` |
| `SAGE_SERVER_LOG_FORMAT` | `json` （也支持 `text`） |
| `SAGE_SERVER_LOG_DIRECTORY` | 可选 |
| `SAGE_SERVER_JAEGER_URL` | 可选 OTLP 地址 |
| `SAGE_SERVER_JAEGER_SERVICE_NAME` | `sage-server` |
| `SAGE_SERVER_JAEGER_PUBLIC_URL` | `http://127.0.0.1:16686/jaeger` |

并发和容量参数必须为正数，约束单进程，不是分布式配额。Redis 不再是启动依赖或 AG-UI 回放存储。

## Desktop 与嵌入式运行时

Desktop v2 读取持久化设置，不通过环境变量覆盖 Agent/模型。需要隔离源码调试数据时，使用后端 `--data-root` 参数。

嵌入式包显式声明凭据来源变量名。快速开始中的 `MODEL_API_KEY` 由该 manifest 选择，不是全局固定配置。旧版 `SAGE_DEFAULT_*` 变量不配置此示例。
