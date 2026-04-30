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

## 1. LLM defaults

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_DEFAULT_LLM_API_KEY` | — | Default OpenAI-compatible API key |
| `SAGE_DEFAULT_LLM_API_BASE_URL` | — | Default model base URL |
| `SAGE_DEFAULT_LLM_MODEL_NAME` | — | Default model name |

## 2. Service ports & directories

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_HOST` | `0.0.0.0` | Server bind address |
| `SAGE_PORT` | `8001` (server) / dynamic (desktop) | Service port |
| `SAGE_ROOT` | `~/.sage` | Root for sessions/agents/logs |
| `SAGE_SESSIONS_PATH` | `$SAGE_ROOT/sessions` | Session persistence directory |
| `SAGE_AGENTS_PATH` | `$SAGE_ROOT/agents` | Agent config directory |
| `SAGE_MCP_CONFIG_PATH` | `$SAGE_ROOT/mcp.json` | MCP server config file |

## 3. User identity

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_DESKTOP_USER_ID` | `desktop_default_user` | Default desktop user id |
| `SAGE_DESKTOP_USER_ROLE` | `user` | Default desktop user role |
| `SAGE_CLI_USER_ID` | `cli_default_user` | Default CLI user id |
| `SAGE_TASK_SCHEDULER_USER_ID` | — | Identity used by the task scheduler |

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

### 4.1 OpenSandbox (remote)

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENSANDBOX_URL` | — | OpenSandbox endpoint |
| `OPENSANDBOX_API_KEY` | — | API key |
| `OPENSANDBOX_IMAGE` | — | Default image |
| `OPENSANDBOX_TIMEOUT` | — | Request timeout (s) |
| `SAGE_OPENSANDBOX_APPEND_MAX_BYTES` | — | Max bytes per append call |
| `SAGE_APPEND_PATH` / `SAGE_APPEND_B64` | — | Internal append-tool plumbing |

## 5. Agent loop & prompt cache

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_AGENT_STATUS_PROTOCOL_ENABLED` | `true` | Enable the agent turn-status protocol (inject `turn_status` and require the LLM to report status explicitly) |
| `SAGE_CLI_MAX_LOOP_COUNT` | — | Max loops per CLI turn |
| `SAGE_SPLIT_SYSTEM` | `true` | Split the system message into stable / semi_stable / volatile segments to maximise prompt-cache hit rate |
| `SAGE_STABLE_TOOLS_ORDER` | `true` | Sort the `tools` field by function name to stabilise the cache key |
| `SAGE_AUTO_LINT` | `true` | Auto-run ruff/eslint/tsc after `file_write` / `file_update` and inline diagnostics |
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

## 8. Desktop & install

| Variable | Default | Purpose |
| --- | --- | --- |
| `SAGE_HOST_PID` | — | Parent process PID (desktop shell watcher) |
| `SAGE_UPDATE_URL` | — | Desktop auto-updater URL |
| `HOST_WEBDAV_SERVER_ROOT` | — | WebDAV server root |
| `ENABLE_DEBUG_WEBDAV` | `false` | Enable WebDAV debug output |

## 9. Dev & debug

| Variable | Default | Purpose |
| --- | --- | --- |
| `TESTING` | `false` | Test mode; some background tasks are skipped |
| `SAGENTS_PROFILING_TOOL_DECORATOR` | `false` | Profile every `@tool` call |
| `PYTHON_BIN` / `CONDA_PYTHON_EXE` / `CONDA_PREFIX` / `CONDA_ROOT` | — | Python interpreter discovery (install-time) |

## 10. Standard system variables (consumed but not set by Sage)

`HOME`, `USERPROFILE`, `PATH`, `NODE_PATH`, `SSL_CERT_FILE` are read for
cross-platform path / certificate discovery.

---

Before changing any behaviour above, grep the codebase for
`os.environ.get('VARIABLE_NAME')` to confirm the actual default and branching
logic — this table is a summary, not a contract.
