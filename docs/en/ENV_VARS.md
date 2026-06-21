---
layout: default
title: Environment Variables Reference
nav_order: 6
description: "Authoritative list of every environment variable Sage reads"
lang: en
ref: env_vars
---

{% include lang_switcher.html %}

# Environment Variables Reference

> Compiled by scanning every `os.environ.get` / `os.getenv` call in `sagents/`,
> `app/`, `common/`, and `mcp_servers/`. Treat the source as the source of truth
> for default values; "—" means there is no static default (required, or
> derived dynamically).

## 0. Deployment Example Policy

`deploy/dev|test|prod/.env.example` uses a minimal-required policy: it keeps only Compose/application values that are normally changed per environment, secrets, accounts, and external URLs. Kubernetes-only settings live in `deploy/k8s/env/*.env.example` instead of the shared environment templates. Stable defaults live in code, Compose, or the K8s deploy script.

Variables intentionally kept in the examples:

| Type | Variables |
| --- | --- |
| Environment and entrypoint | `SAGE_ENV`, `SAGE_ROOT` |
| Secrets and accounts | `SAGE_JWT_KEY`, `SAGE_REFRESH_TOKEN_SECRET`, `SAGE_SESSION_SECRET`, MySQL/S3/Grafana passwords, LLM/Embedding/video-analysis API keys, email AK/SK |
| External URLs | `SAGE_TRACE_JAEGER_PUBLIC_URL`, `SAGE_GRAFANA_PUBLIC_URL`, `SAGE_S3_PUBLIC_BASE_URL`, `SAGE_ELASTICSEARCH_URL` |

Kubernetes templates separately keep `NAMESPACE`, `SAGE_HOST`, `SAGE_PUBLIC_URL`, `IMAGE_REGISTRY`, `IMAGE_PULL_POLICY`, `K8S_IMAGE_TARGET`, `CTR_BIN`, `CTR_NAMESPACE`, `STORAGE_CLASS`, `INGRESS_CLASS_NAME`, `TLS_SECRET_NAME`, `ENABLE_INGRESS`, `SAGE_WEB_SERVICE_TYPE`, `SAGE_WIKI_SERVICE_TYPE`, `SAGE_WEB_NODE_PORT`, and `SAGE_WIKI_NODE_PORT`.

Advanced overrides are not listed in `.env.example` unless a deployment needs to change them. Common examples include Compose project/port overrides, `SAGE_WEB_BASE_PATH`, `SAGE_TRACE_JAEGER_URL`, `SAGE_LOKI_PUSH_URL`, `SAGE_MCP_*`, `OPENSANDBOX_IMAGE`, `OPENSANDBOX_TIMEOUT`, `SAGE_OPENSANDBOX_APPEND_MAX_BYTES`, default LLM/Embedding model parameters, video-analysis model parameters, and fixed email defaults.

## 1. LLM defaults

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_DEFAULT_LLM_API_KEY` | — | Default OpenAI-compatible API key |
| `SAGE_DEFAULT_LLM_API_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1/` | Default model base URL |
| `SAGE_DEFAULT_LLM_MODEL_NAME` | `deepseek-v3` | Default model name |
| `SAGE_DEFAULT_LLM_MAX_TOKENS` | `4096` | Default max output tokens |
| `SAGE_DEFAULT_LLM_TEMPERATURE` | `0.2` | Default sampling temperature |
| `SAGE_DEFAULT_LLM_MAX_MODEL_LEN` | `52000` | Default context length |
| `SAGE_DEFAULT_LLM_TOP_P` | `1.0` | Default nucleus sampling value |
| `SAGE_DEFAULT_LLM_PRESENCE_PENALTY` | `0.0` | Default presence penalty |
| `SAGE_REASONING_EFFORT_OFF` | `low` | Reasoning effort to use for OpenAI reasoning models when thinking is disabled; accepts provider-supported values such as `minimal` / `low` / `medium` / `high` |

## 2. Service ports & directories

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_HOST` | — | Public deployment hostname/IP, mainly used by K8s URL derivation; not the server bind address |
| `SAGE_ENV` | `development` | Application environment name |
| `SAGE_AUTH_MODE` | `native` | Server auth mode |
| `SAGE_LOG_LEVEL` | `info` | Server log level |
| `SAGE_PORT` | `8001` (server) / dynamic (desktop) | Service port |
| `SAGE_ROOT` | `~/.sage` | Root for sessions/agents/logs |
| `SAGE_SESSION_DIR` | `$SAGE_ROOT/sessions` | Server/terminal session directory |
| `SAGE_LOGS_DIR_PATH` | `$SAGE_ROOT/logs` | Log directory |
| `SAGE_AGENTS_DIR` | `$SAGE_ROOT/agents` | Server/terminal agent directory |
| `SAGE_USER_DIR` | `$SAGE_ROOT/users` | User data directory |
| `SAGE_DB_FILE` | `$SAGE_ROOT/sage.db` | SQLite/file database path |
| `SAGE_SKILL_WORKSPACE` | `$SAGE_ROOT/skills` | Skill workspace directory |
| `SAGE_SESSIONS_PATH` | `$SAGE_ROOT/sessions` | Session persistence directory |
| `SAGE_AGENTS_PATH` | `$SAGE_ROOT/agents` | Agent config directory |
| `SAGE_MCP_CONFIG_PATH` | `$SAGE_ROOT/mcp.json` | MCP server config file |
| `SAGE_PRESET_RUNNING_CONFIG_PATH` | — | Optional preset running config path |

## 3. User identity

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_DESKTOP_USER_ID` | `desktop_default_user` | Default desktop user id |
| `SAGE_DESKTOP_USER_ROLE` | `user` | Default desktop user role |
| `SAGE_CLI_USER_ID` | `cli_default_user` | Default CLI user id |
| `SAGE_TASK_SCHEDULER_USER_ID` | — | Identity used by the task scheduler |

## 3.1 Server auth, cookies & CORS

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_AUTH_PROVIDERS` | — | JSON array of enabled upstream auth providers |
| `SAGE_TRUSTED_IDENTITY_PROXY_IPS` | — | Comma-separated trusted proxy IPs for identity headers |
| `SAGE_BOOTSTRAP_ADMIN_USERNAME` | `admin` | Initial admin username |
| `SAGE_BOOTSTRAP_ADMIN_PASSWORD` | — | Initial admin password |
| `SAGE_JWT_KEY` | — | JWT signing secret |
| `SAGE_JWT_EXPIRE_HOURS` | `24` | JWT lifetime in hours |
| `SAGE_REFRESH_TOKEN_SECRET` | — | Refresh-token signing secret |
| `SAGE_SESSION_SECRET` | — | Server session secret |
| `SAGE_SESSION_COOKIE_NAME` | `sage_session` | Session cookie name |
| `SAGE_SESSION_COOKIE_SECURE` | `false` | Whether session cookies require HTTPS |
| `SAGE_SESSION_COOKIE_SAME_SITE` | `lax` | Session cookie SameSite policy |
| `SAGE_CORS_ALLOWED_ORIGINS` | — | CORS allowed origins |
| `SAGE_CORS_ALLOW_CREDENTIALS` | `true` | CORS credentials flag |
| `SAGE_CORS_ALLOW_METHODS` | — | CORS allowed methods |
| `SAGE_CORS_ALLOW_HEADERS` | — | CORS allowed request headers |
| `SAGE_CORS_EXPOSE_HEADERS` | — | CORS exposed response headers |
| `SAGE_CORS_MAX_AGE` | `600` | CORS preflight max age |
| `SAGE_WEB_BASE_PATH` | `/` | Web app base path |

## 4. Sandbox & execution

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_SANDBOX_MODE` | `passthrough` | One of `passthrough` / `local` / `remote` |
| `SAGE_REMOTE_PROVIDER` | — | Provider name when remote sandbox is used |
| `SAGE_SANDBOX_MOUNT_PATHS` | — | Extra mount paths (`;`/newline separated) |
| `SAGE_SANDBOX_RUNTIME_DIR` | — | Sandbox runtime directory |
| `SAGE_SHARED_SANDBOX_RUNTIME_DIR` | — | Shared sandbox runtime root |
| `SAGE_SHARED_PYTHON_ENV` | `false` | Share a single Python env across sessions |
| `SAGE_SHARED_PYTHON_ENV_DIR` | — | Shared venv directory |
| `SAGE_LOCAL_CPU_TIME_LIMIT` | — | Local sandbox CPU time limit (s) |
| `SAGE_LOCAL_MEMORY_LIMIT_MB` | — | Local sandbox memory limit (MB) |
| `SAGE_LOCAL_LINUX_ISOLATION` | `false` | Linux namespace isolation |
| `SAGE_LOCAL_MACOS_ISOLATION` | `false` | macOS sandbox-exec isolation |
| `SAGE_USE_CLAW_MODE` | `true` | Inject IDENTITY/AGENT/SOUL/USER/MEMORY md into the system prompt |
| `SAGE_BUNDLED_NODE_BIN` | — | Bundled Node binary (desktop installs) |
| `SAGE_NODE_HOST` | — | Bundled Node service host |
| `SAGE_NODE_MODULES_DIR` | — | Shared `node_modules` directory |
| `SAGE_NODE_PATH` | — | Desktop bundled Node module lookup path |
| `SAGE_NODE_EXECUTABLE` / `SAGE_NPM_CLI` | — | Desktop Node/npm executable overrides |
| `SAGE_PYTHON` | — | Python executable override used by desktop/terminal launchers |

### 4.1 OpenSandbox (remote)

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENSANDBOX_URL` | — | OpenSandbox endpoint |
| `OPENSANDBOX_API_KEY` | — | API key |
| `OPENSANDBOX_IMAGE` | `opensandbox/code-interpreter:v1.0.2` | Default image |
| `OPENSANDBOX_TIMEOUT` | `1800` | Request timeout (s) |
| `SAGE_OPENSANDBOX_APPEND_MAX_BYTES` | `262144` | Max bytes per append call |
| `SAGE_APPEND_PATH` / `SAGE_APPEND_B64` | — | Internal append-tool plumbing |

## 4.2 Embedding defaults

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_EMBEDDING_API_KEY` | — | Embedding API key |
| `SAGE_EMBEDDING_BASE_URL` | `https://dashscope.aliyuncs.com/compatible-mode/v1/` | Embedding base URL |
| `SAGE_EMBEDDING_MODEL` | `text-embedding-v4` | Embedding model |
| `SAGE_EMBEDDING_DIMS` | `1024` | Embedding dimensions |

## 4.3 Storage, observability & integrations

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_S3_ENDPOINT` / `SAGE_S3_ACCESS_KEY` / `SAGE_S3_SECRET_KEY` | — | S3-compatible object storage connection |
| `SAGE_S3_SECURE` | `false` | Use HTTPS for S3-compatible storage |
| `SAGE_S3_BUCKET_NAME` | — | Object storage bucket |
| `SAGE_S3_PUBLIC_BASE_URL` | — | Public base URL for stored objects |
| `SAGE_MYSQL_HOST` / `SAGE_MYSQL_PORT` / `SAGE_MYSQL_USER` / `SAGE_MYSQL_PASSWORD` / `SAGE_MYSQL_DATABASE` | — | MySQL connection settings |
| `SAGE_ELASTICSEARCH_URL` / `SAGE_ELASTICSEARCH_API_KEY` / `SAGE_ELASTICSEARCH_USERNAME` / `SAGE_ELASTICSEARCH_PASSWORD` | — | Elasticsearch connection settings |
| `SAGE_TRACE_JAEGER_URL` | — | Internal Jaeger query URL |
| `SAGE_TRACE_JAEGER_ENDPOINT` | — | Jaeger OTLP endpoint |
| `SAGE_TRACE_JAEGER_PUBLIC_URL` | `http://127.0.0.1:30051/jaeger` | Public Jaeger URL |
| `SAGE_GRAFANA_PUBLIC_URL` | — | Public Grafana URL used by deployments |
| `SAGE_LOKI_PUSH_URL` | — | Loki push endpoint |
| `SAGE_KB_MCP_URL` / `SAGE_KB_MCP_API_KEY` | — | Knowledge-base MCP integration |
| `SAGE_OAUTH2_CLIENTS` / `SAGE_OAUTH2_ISSUER` / `SAGE_OAUTH2_ACCESS_TOKEN_EXPIRES_IN` | — | Built-in OAuth2 provider settings |
| `SAGE_EML_ENDPOINT` / `SAGE_EML_ACCESS_KEY_ID` / `SAGE_EML_ACCESS_KEY_SECRET` / `SAGE_EML_SECURITY_TOKEN` | — | Email provider credentials |
| `SAGE_EML_ACCOUNT_NAME` / `SAGE_EML_TEMPLATE_ID` / `SAGE_EML_REGISTER_SUBJECT` / `SAGE_EML_ADDRESS_TYPE` / `SAGE_EML_REPLY_TO_ADDRESS` | — | Email sender/template defaults |

## 5. Agent loop & prompt cache

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_TASK_COMPLETION_MODE` | `turn_status` | Select how SimpleAgent decides that a turn is complete. `turn_status` exposes the `turn_status` protocol tool and lets the model report `task_done` / `need_user_input` / `blocked` / `continue_work`; `llm_judge` disables `turn_status` and uses the legacy rule-first + LLM `task_complete_judge` check; `no_tool_call` disables `turn_status` and treats an LLM response without tool calls as complete. |
| `SAGE_RUNTIME_CONTEXT_IN_USER` | `true` | Move volatile runtime context (`system_context`, workspace files, active ToDo) out of system messages and freeze it into the latest user message inference metadata. Set `false` only for legacy behaviour where volatile context stays in system. |
| `SAGE_CLI_MAX_LOOP_COUNT` | — | Max loops per CLI turn |
| `SAGE_CONTEXT_HISTORY_RATIO` / `SAGE_CONTEXT_ACTIVE_RATIO` / `SAGE_CONTEXT_MAX_NEW_MESSAGE_RATIO` / `SAGE_CONTEXT_RECENT_TURNS` | code defaults | Context budget allocation knobs |
| `SAGE_TOOL_SUGGESTION_DIRECT_THRESHOLD` | `15` | When the available tool count is at or below this value, skip the LLM tool-suggestion call and pass all available tools through |
| `SAGE_EMIT_TOOL_CALL_ON_COMPLETE` | `true` | Re-emit tool_call chunks once the LLM stream completes |
| `SAGE_ECHO_SHELL_OUTPUT` | `false` | Echo background-shell stdout/stderr into the main stream |
| `SAGE_FORCE_TOOL_CHOICE_REQUIRED` | `false` | Force `tool_choice=required` on every LLM call that carries `tools`. Off by default to avoid `unsupported_parameter` errors on models such as OpenAI o1/o3; enable explicitly with `1/true/yes/on` |
| `SAGE_TOOL_PROGRESS_ENABLED` | `true` | Enable the tool live-progress channel (NDJSON `type=tool_progress` events for the UI only; never sent to MessageManager or the LLM) |
| `SAGE_TOOL_PROGRESS_FLUSH_INTERVAL_MS` | `50` | Coalesce window (ms). Multiple `emit_tool_progress` calls within the window for the same `(tool_call, stream)` are merged into one event. Set to `0` to disable coalescing and emit immediately |
| `SAGE_TOOL_PROGRESS_FLUSH_BYTES` | `16384` | Per-stream byte threshold; once accumulated text reaches it, flush immediately (prevents fast-producing commands from saturating the channel) |

## 6. Memory

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_DB_TYPE` | — | Database backend |
| `SAGE_SESSION_MEMORY_BACKEND` | — | Session memory backend implementation |
| `SAGE_SESSION_MEMORY_STRATEGY` | — | Session memory compress / recall strategy |
| `SAGE_FILE_MEMORY_BACKEND` | — | File memory backend implementation |
| `MEMORY_ROOT_PATH` | — | Root directory for file memory |
| `ENABLE_REDIS_LOCK` | `false` | Enable Redis distributed lock |
| `MEMORY_LOCK_EXPIRE_SECONDS` | — | Redis lock TTL |
| `REDIS_URL` | — | Redis connection string |

## 7. MCP / AnyTool

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_DEFAULT_ANYTOOL_TIMEOUT` | — | AnyTool call timeout |
| `SAGE_LS_PATH` | — | Default root for the MCP `list_dir` tool |
| `SAGE_LS_HIDDEN` | `false` | Whether `list_dir` shows hidden files |
| `SAGE_MCP_PER_CONNECTION_CONCURRENCY` | `100` | Max concurrent MCP calls per pooled connection |
| `SAGE_MCP_MAX_CONNECTIONS_PER_SERVER` | `0` | Max pooled MCP connections per server; `0` means no fixed cap |
| `SAGE_MCP_SESSION_IDLE_TTL_SECONDS` | `1800` | Idle TTL for MCP pooled sessions |
| `SAGE_MCP_REFRESH_DRAIN_TIMEOUT_SECONDS` | `30` | Grace period while draining refreshed MCP connections |
| `SAGE_MCP_CALL_TIMEOUT_SECONDS` | `1800` | MCP tool call timeout |
| `SAGE_MCP_LIST_TOOLS_RETRY_ON_CONNECTION_ERROR` | `true` | Retry MCP `list_tools` once on connection-like errors |
| `SAGE_MCP_CALL_RETRY_ON_CONNECTION_ERROR` | `true` | Retry MCP tool calls once on connection-like errors |

## 8. Desktop & install

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_HOST_PID` | — | Parent process PID (desktop shell watcher) |
| `SAGE_UPDATE_URL` | — | Desktop auto-updater URL |
| `SAGE_INTERNAL_DESKTOP_PROCESS` | — | Internal desktop process marker |
| `SAGE_TERMINAL_BIN` | — | Terminal binary override |
| `SAGE_TERMINAL_CLI` | — | Terminal launcher CLI override |
| `SAGE_TERMINAL_RUNTIME_ROOT` | — | Terminal packaged runtime root |
| `SAGE_TERMINAL_STATE_ROOT` | — | Terminal state root |
| `SAGE_TERMINAL_DEBUG_LAUNCH` | `0` | Print terminal launcher diagnostics |
| `HOST_WEBDAV_SERVER_ROOT` | — | WebDAV server root |
| `ENABLE_DEBUG_WEBDAV` | `false` | Enable WebDAV debug output |

## 9. Dev & debug

| Variable | Default | Purpose |
| --- | --- | --- |
| `TESTING` | `false` | Test mode; some background tasks are skipped |
| `SAGENTS_PROFILING_TOOL_DECORATOR` | `false` | Profile every `@tool` call |
| `SAGE_DISABLE_SAGENTS_FILE_LOGGING` | `false` | Disable sagents file logging |
| `AGENT_BROWSER_HEADED` | `1` in desktop core | Run the bundled browser automation in headed mode |
| `SAGE_TERMINAL_TEST_PERSIST_PREFERENCES` | — | Test-only terminal preferences persistence override |
| `VITE_SAGE_API_BASE_URL` / `VITE_BACKEND_API_PREFIX` / `VITE_SAGE_GRAFANA_URL` | — | Frontend build/runtime API URL overrides |
| `PYTHON_BIN` / `CONDA_PYTHON_EXE` / `CONDA_PREFIX` / `CONDA_ROOT` | — | Python interpreter discovery (install-time) |

## 9.1 Deprecated / legacy compatibility variables

| Variable | Replacement / status |
| --- | --- |
| `SAGE_AGENT_STATUS_PROTOCOL_ENABLED` | Deprecated. Used only when `SAGE_TASK_COMPLETION_MODE` is unset; `false` maps to `llm_judge`. |
| `SAGE_COMPLETE_ON_NO_TOOL_CALL` | Deprecated. Used only when `SAGE_TASK_COMPLETION_MODE` is unset; `true` maps to `no_tool_call`. |
| `SAGE_SPLIT_SYSTEM` | Deprecated and ignored. Split system messages are always enabled. |
| `SAGE_STABLE_TOOLS_ORDER` | Deprecated and ignored. Tools are always sorted by `function.name` before LLM requests. |
| `SAGE_AUTO_LINT` | Deprecated and ignored. File-tool linting is always enabled. |
| `SAGE_SESSION_DIR_PATH` | Legacy alias for `SAGE_SESSION_DIR` in CLI stream code. |
| `LLM_API_KEY` / `LLM_API_BASE_URL` / `LLM_MODEL_NAME` | Legacy names; use `SAGE_DEFAULT_LLM_API_KEY` / `SAGE_DEFAULT_LLM_API_BASE_URL` / `SAGE_DEFAULT_LLM_MODEL_NAME`. |

## 10. Standard system variables (consumed but not set by Sage)

`HOME`, `USERPROFILE`, `PATH`, `NODE_PATH`, `SSL_CERT_FILE` are read for
cross-platform path / certificate discovery.

---

Before changing any behaviour above, grep the codebase for
`os.environ.get('VARIABLE_NAME')` to confirm the actual default and branching
logic — this table is a summary, not a contract.
