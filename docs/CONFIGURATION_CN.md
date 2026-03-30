---
layout: default
title: 配置参考
nav_order: 13
description: "基于当前 Sage 代码库的配置参考"
---

{: .note }
> 英文版本请查看 [Configuration Reference](CONFIGURATION.html)。

# 配置参考

本文档只描述当前仓库里仍然有效的配置入口。

## 1. 主要配置来源

当前配置主要分布在三层：

1. 服务启动配置：[`app/server/core/config.py`](../app/server/core/config.py)
2. 运行时参数：[`sagents/sagents.py`](../sagents/sagents.py)
3. 示例 CLI 参数：[`examples/sage_cli.py`](../examples/sage_cli.py) 和 [`examples/sage_server.py`](../examples/sage_server.py)

## 2. 服务端环境变量

主配置结构体 `StartupConfig` 定义在 [`app/server/core/config.py`](../app/server/core/config.py)。

### 核心服务

| 变量 | 默认值 | 含义 |
|---|---|---|
| `SAGE_PORT` | `8080` | FastAPI 监听端口 |
| `SAGE_LOGS_DIR_PATH` | `logs` | 日志目录 |
| `SAGE_SESSION_DIR` | `sessions` | 会话存储目录 |
| `SAGE_AGENTS_DIR` | `agents` | Agent 存储目录 |
| `SAGE_USER_DIR` | `users` | 用户数据目录 |
| `SAGE_SKILL_WORKSPACE` | `skills` | 宿主机技能目录 |

### 默认 LLM

| 变量 | 默认值 |
|---|---|
| `SAGE_DEFAULT_LLM_API_KEY` | `""` |
| `SAGE_DEFAULT_LLM_API_BASE_URL` | `https://api.deepseek.com/v1` |
| `SAGE_DEFAULT_LLM_MODEL_NAME` | `deepseek-chat` |
| `SAGE_DEFAULT_LLM_MAX_TOKENS` | `4096` |
| `SAGE_DEFAULT_LLM_TEMPERATURE` | `0.2` |
| `SAGE_DEFAULT_LLM_MAX_MODEL_LEN` | `54000` |
| `SAGE_DEFAULT_LLM_TOP_P` | `0.9` |
| `SAGE_DEFAULT_LLM_PRESENCE_PENALTY` | `0.0` |

### 上下文预算

| 变量 | 默认值 |
|---|---|
| `SAGE_CONTEXT_HISTORY_RATIO` | `0.2` |
| `SAGE_CONTEXT_ACTIVE_RATIO` | `0.3` |
| `SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO` | `0.5` |
| `SAGE_CONTEXT_RECENT_TURNS` | `0` |

### 数据库

| 变量 | 默认值 |
|---|---|
| `SAGE_DB_TYPE` | `file` |
| `SAGE_MYSQL_HOST` | `127.0.0.1` |
| `SAGE_MYSQL_PORT` | `3306` |
| `SAGE_MYSQL_USER` | `root` |
| `SAGE_MYSQL_PASSWORD` | `sage.1234` |
| `SAGE_MYSQL_DATABASE` | `sage` |

### 鉴权

| 变量 | 默认值 |
|---|---|
| `SAGE_JWT_KEY` | 内置开发密钥 |
| `SAGE_JWT_EXPIRE_HOURS` | `24` |
| `SAGE_REFRESH_TOKEN_SECRET` | 内置开发密钥 |
| `SAGE_SESSION_SECRET` | 内置开发密钥 |
| `SAGE_SESSION_COOKIE_NAME` | `sage_session` |

### Embedding / 搜索 / 存储

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

### 可观测性

- `SAGE_TRACE_JAEGER_ENDPOINT`
- `SAGE_TRACE_JAEGER_UI_URL`
- `SAGE_TRACE_JAEGER_PUBLIC_URL`
- `SAGE_TRACE_JAEGER_BASE_PATH`

## 3. `.env` 示例

```bash
SAGE_DEFAULT_LLM_API_KEY=sk-your-api-key
SAGE_DEFAULT_LLM_API_BASE_URL=https://api.deepseek.com/v1
SAGE_DEFAULT_LLM_MODEL_NAME=deepseek-chat

SAGE_PORT=8080
SAGE_DB_TYPE=file
SAGE_SESSION_DIR=./sessions
SAGE_LOGS_DIR_PATH=./logs

SAGE_CONTEXT_HISTORY_RATIO=0.2
SAGE_CONTEXT_ACTIVE_RATIO=0.3
SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO=0.5
SAGE_CONTEXT_RECENT_TURNS=6
```

## 4. CLI 配置

### `examples/sage_cli.py`

常用参数：

- `--default_llm_api_key`
- `--default_llm_api_base_url`
- `--default_llm_model_name`
- `--agent_mode`
- `--workspace`
- `--virtual_workspace`
- `--sandbox_type`
- `--tools_folders`
- `--skills_path`
- `--memory_type`
- `--session_root`
- `--context_history_ratio`
- `--context_active_ratio`
- `--context_max_new_message_ratio`
- `--context_recent_turns`

### `examples/sage_server.py`

常用参数：

- `--default_llm_api_key`
- `--default_llm_api_base_url`
- `--default_llm_model_name`
- `--host`
- `--port`
- `--mcp-config`
- `--workspace`
- `--skills-path`
- `--logs-dir`
- `--preset_running_config`
- `--memory_type`
- `--session-root`

## 5. `SAgent` 运行时参数

当前最重要的运行时参数直接传给 `SAgent.run_stream()`：

- `agent_mode`
- `deep_thinking`
- `max_loop_count`
- `system_context`
- `available_workflows`
- `context_budget_config`
- `custom_sub_agents`
- `custom_flow`
- `sandbox_type`
- `sandbox_agent_workspace`
- `volume_mounts`

## 6. 服务端 Agent 配置

服务端 Agent 配置 DTO 定义在 [`app/server/routers/agent.py`](../app/server/routers/agent.py)。

常见持久化字段：

- `name`
- `systemPrefix`
- `systemContext`
- `availableWorkflows`
- `availableTools`
- `availableSubAgentIds`
- `availableSkills`
- `availableKnowledgeBases`
- `memoryType`
- `maxLoopCount`
- `deepThinking`
- `multiAgent`
- `agentMode`
- `llm_provider_id`

## 7. 说明

- 不要再依赖旧文档里出现的 `config/settings.yaml`、`agents.config`、`AgentController` 一类配置方式；它们不是当前仓库的主配置入口。
- 如果你要看代码里真正保证存在的环境变量列表，优先参考 [`app/server/core/config.py`](../app/server/core/config.py) 和 [`docs/ENVIRONMENT_VARIABLES.md`](ENVIRONMENT_VARIABLES.md)。
