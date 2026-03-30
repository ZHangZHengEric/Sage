---
layout: default
title: Configuration Reference
nav_order: 12
description: "Configuration reference based on the current Sage codebase"
---

{: .note }
> Looking for Chinese? See [配置参考](CONFIGURATION_CN.html).

# Configuration Reference

This document reflects the active configuration surfaces that exist in the repository today.

## 1. Main Sources Of Configuration

Current configuration is spread across three main layers:

1. server startup config in [`app/server/core/config.py`](../app/server/core/config.py)
2. runtime parameters passed to [`sagents/sagents.py`](../sagents/sagents.py)
3. CLI arguments in [`examples/sage_cli.py`](../examples/sage_cli.py) and [`examples/sage_server.py`](../examples/sage_server.py)

## 2. Server Environment Variables

The main server config struct is `StartupConfig` in [`app/server/core/config.py`](../app/server/core/config.py).

### Core Service

| Variable | Default | Meaning |
|---|---|---|
| `SAGE_PORT` | `8080` | FastAPI server port |
| `SAGE_LOGS_DIR_PATH` | `logs` | Logs directory |
| `SAGE_SESSION_DIR` | `sessions` | Session storage directory |
| `SAGE_AGENTS_DIR` | `agents` | Agent storage directory |
| `SAGE_USER_DIR` | `users` | User data directory |
| `SAGE_SKILL_WORKSPACE` | `skills` | Host-side skill directory |

### Default LLM

| Variable | Default |
|---|---|
| `SAGE_DEFAULT_LLM_API_KEY` | `""` |
| `SAGE_DEFAULT_LLM_API_BASE_URL` | `https://api.deepseek.com/v1` |
| `SAGE_DEFAULT_LLM_MODEL_NAME` | `deepseek-chat` |
| `SAGE_DEFAULT_LLM_MAX_TOKENS` | `4096` |
| `SAGE_DEFAULT_LLM_TEMPERATURE` | `0.2` |
| `SAGE_DEFAULT_LLM_MAX_MODEL_LEN` | `54000` |
| `SAGE_DEFAULT_LLM_TOP_P` | `0.9` |
| `SAGE_DEFAULT_LLM_PRESENCE_PENALTY` | `0.0` |

### Context Budget

| Variable | Default |
|---|---|
| `SAGE_CONTEXT_HISTORY_RATIO` | `0.2` |
| `SAGE_CONTEXT_ACTIVE_RATIO` | `0.3` |
| `SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO` | `0.5` |
| `SAGE_CONTEXT_RECENT_TURNS` | `0` |

### Database

| Variable | Default |
|---|---|
| `SAGE_DB_TYPE` | `file` |
| `SAGE_MYSQL_HOST` | `127.0.0.1` |
| `SAGE_MYSQL_PORT` | `3306` |
| `SAGE_MYSQL_USER` | `root` |
| `SAGE_MYSQL_PASSWORD` | `sage.1234` |
| `SAGE_MYSQL_DATABASE` | `sage` |

### Auth

| Variable | Default |
|---|---|
| `SAGE_JWT_KEY` | built-in dev secret |
| `SAGE_JWT_EXPIRE_HOURS` | `24` |
| `SAGE_REFRESH_TOKEN_SECRET` | built-in dev secret |
| `SAGE_SESSION_SECRET` | built-in dev secret |
| `SAGE_SESSION_COOKIE_NAME` | `sage_session` |

### Embedding / Search / Storage

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

### Observability

- `SAGE_TRACE_JAEGER_ENDPOINT`
- `SAGE_TRACE_JAEGER_UI_URL`
- `SAGE_TRACE_JAEGER_PUBLIC_URL`
- `SAGE_TRACE_JAEGER_BASE_PATH`

## 3. Example `.env`

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

## 4. CLI Configuration

### `examples/sage_cli.py`

Common flags:

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

Common flags:

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

## 5. Runtime Configuration In `SAgent`

The most important runtime knobs are passed directly to `SAgent.run_stream()`:

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

## 6. Agent Configuration In Server APIs

The server-side agent DTO is defined in [`app/server/routers/agent.py`](../app/server/routers/agent.py).

Common persisted fields:

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

## 7. Notes

- Do not rely on older docs that describe `config/settings.yaml`, `agents.config`, or `AgentController`-style runtime config. Those are not the primary configuration surfaces in the current repository.
- For the actual environment variable list that is guaranteed by code, prefer [`app/server/core/config.py`](../app/server/core/config.py) and [`docs/ENVIRONMENT_VARIABLES.md`](ENVIRONMENT_VARIABLES.md).
