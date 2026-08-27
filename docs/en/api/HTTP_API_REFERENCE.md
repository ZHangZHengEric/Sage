---
layout: default
title: HTTP API Reference
parent: API documentation
nav_order: 1
has_children: true
description: "Backend HTTP API reference based on the current codebase"
lang: en
ref: http-api-reference
---

{% include lang_switcher.html %}

# HTTP API Reference

This page documents the backend HTTP endpoints that actually exist in the current codebase. It is organized as: quick rules, endpoint index, key payload models, and working `curl` examples.

For embedding the Python runtime (`SAgent`, `run_stream`, tools), see [API Reference](API_REFERENCE.md). For the hosted FastAPI server, this page is authoritative.

**Scope:** This list reflects `register_routes` in `app/server/routers` (the main platform FastAPI app). The desktop app (`app/desktop/`) has additional routes (IM, browser extension, questionnaire, etc.) that are **not** included here.

## API surface map

### Relation to OpenAPI

**OpenAPI 3** is the usual machine-readable contract (exportable from FastAPI; it can live next to this hand-maintained page). What follows is a **layer → module → router file** text index, not a diagram. **Layers are for cataloguing only**—not a required call order. The **Endpoint index** is authoritative for every path; the subpages are narrative.

### Layer 1: access and identity


| Module                 | Router      | Main paths / family                                                                                    |
| ---------------------- | ----------- | ------------------------------------------------------------------------------------------------------ |
| Local account          | `auth.py`   | `/api/auth/…` registration, username/password login, session, and logout                              |
| Users and compat       | `user.py`   | `/api/user/…` config, admin list/add/delete, options, `change-password`, and legacy `check_login` etc. |


### Layer 2: core product


| Module               | Router                          | Main paths / family                                                                                                                                           |
| -------------------- | ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Streaming and input  | `chat.py`, `agui_v2.py`         | Existing Sage streams plus additive `POST /api/v2/agent/chat` using AG-UI HTTP/SSE                                                                            |
| Sessions and sharing | `conversation.py`               | `/api/conversations`*, `…/share/…/messages`, `…/interrupt`, `…/tasks_status`, `…/edit-last-user-message`, `…/rerun-stream`                                    |
| Agent and workspace  | `agent.py`                      | `/api/agent/…` CRUD, `auto-generate*`, `system-prompt*`, `abilities`, `auth`, `file_workspace*`, `GET/POST /api/agent/tasks/…` async jobs, `workspace/delete` |
| Planner              | `task.py`                       | Prefix `/tasks/…` (**not** `/api/tasks`), including `internal/…` — [not the same as agent async tasks](HTTP_API_TASKS.md#planner-vs-agent-async)              |
| Tools / skills / MCP | `tool.py`, `skill.py`, `mcp.py` | `/api/tools`, `/api/skills`, `/api/mcp` (incl. `exec`, sync, refresh)                                                                                         |


### Layer 3: platform and observability


| Module              | Router             | Main paths / family                                                                               |
| ------------------- | ------------------ | ------------------------------------------------------------------------------------------------- |
| Model providers     | `llm_provider.py`  | `/api/llm-provider/…` verify*, list, create, update, delete                                       |
| System and stats    | `system.py`        | `/api/system/info`, `/api/health`, `/api/system/update_settings`, `/api/system/agent/usage-stats` |
| File upload         | `oss.py`           | `POST /api/oss/upload`                                                                            |
| Observability       | `observability.py` | `/api/observability/jaeger`* (incl. login/auth redirects)                                         |
| Root liveness       | `main.py`          | `GET /active` plain text, **no** `/api` prefix (unlike `GET /api/health`)                         |


**Note:** in layer 2, [GET /api/agent/tasks/{id} (agent async)](HTTP_API_TASKS.md#planner-vs-agent-async) and `**/tasks/…` (planner)** are different systems. If a row disagrees with `app/server/routers`, the **routers** win.

## Deep-dive subpages

**Suggested reading for integrators:** start with [Auth and users](HTTP_API_AUTH_USER.md), then [Chat, streaming, and message edits](HTTP_API_CHAT.md) or [AG-UI V2 chat](HTTP_API_AG_UI_V2.md), then [Platform, storage, and observability](HTTP_API_PLATFORM.md) for model keys and health checks.

- [Auth and users](HTTP_API_AUTH_USER.md): local account sessions, registration, and admin APIs.
- [Chat, streaming, and message editing](HTTP_API_CHAT.md): `optimize-input`, `rerun-stream`, and the three stream POST entry points.
- [AG-UI V2 chat](HTTP_API_AG_UI_V2.md): native `RunAgentInput`, standard AG-UI SSE events, idempotency, and process-local replay limits.
- [Agent: extra capabilities](HTTP_API_AGENT.md): async `submit`, ability cards, `/api/agent/tasks/`*, workspace, authz.
- [Tools, skills, and MCP](HTTP_API_TOOLS_MCP.md): `exec`, skill sync options, registering MCP servers.
- [Scheduled tasks and `/tasks](HTTP_API_TASKS.md)`: one-time and recurring jobs, internal routes, not async agent tasks.
- [Platform, storage, and observability](HTTP_API_PLATFORM.md): LLM providers, system settings, OSS, Jaeger, and liveness.

**Are subpages “complete”?** The **index tables** are the exhaustive path list for `app/server`. Subpages cover **per-domain** scenarios and confusions. **Not yet a dedicated subpage (could be added or generated):** an **OpenAPI** export, a unified **error code** matrix, a **middleware allowlist** dump, DTO field-by-field docs for *every* model, a protocol spec for **stream line JSON / SSE** payloads, and a **security & idempotency** guide. For hard integrations, treat this repo’s routers as ground truth, with these docs as a map.

## Quick rules


| Item                      | Notes                                                                                                                                                                                                             |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Base URL                  | For example `http://127.0.0.1:8000`                                                                                                                                                                               |
| Main response shape       | Most `/api/`* routes return `BaseResponse[T]`. The **planner/scheduler** module is mounted at `/tasks` (not `/api/tasks`) and usually returns Pydantic models or plain JSON, without a top-level `code` field     |
| Streaming endpoints       | `/api/chat`, `/api/chat/optimize-input/stream`, `/api/stream`, `/api/web-stream`, `/api/v2/agent/chat`, `POST /api/conversations/{id}/rerun-stream`, `/api/stream/resume/`*, `/api/stream/active_sessions` do not return `BaseResponse` |
| File download             | `/api/agent/{agent_id}/file_workspace/download` returns a file response                                                                                                                                           |
| Liveness                  | `GET /active` returns plain text (no `BaseResponse`, no `/api` prefix)                                                                                                                                            |
| Login state               | Most product-facing endpoints depend on server-side session state, not only on the returned `access_token`                                                                                                        |


Standard response envelope:

```json
{
  "code": 200,
  "message": "success",
  "data": {},
  "timestamp": 1710000000.123
}
```


| Field       | Meaning                                         |
| ----------- | ----------------------------------------------- |
| `code`      | Business status code, usually `200` for success |
| `message`   | Human-readable status                           |
| `data`      | Endpoint-specific payload                       |
| `timestamp` | Server-side timestamp                           |


## Endpoint index

### Authentication and user

Sage uses local accounts. Login and self-registration both accept only a username and password.


| Method | Path                                        | Request                           | `data` response                                 | Purpose                                                |
| ------ | ------------------------------------------- | --------------------------------- | ----------------------------------------------- | ------------------------------------------------------ |
| POST   | `/api/auth/register`                        | `RegisterRequest`                 | `{"user_id"}`                                   | Local account registration                             |
| POST   | `/api/auth/login`                           | `LoginRequest`                    | `{"access_token","refresh_token","expires_in"}` | Local login                                            |
| GET    | `/api/auth/session`                         | none                              | `UserInfoResponse`                              | Read current login session and onboarding status       |
| POST   | `/api/auth/logout`                          | none                              | `{}`                                            | Logout                                                 |
| GET    | `/api/user/options`                         | none                              | user option list                                | User dropdown selector                                 |
| POST   | `/api/user/change-password`                 | `{"old_password","new_password"}` | `{}`                                            | Change current user's password                         |
| GET    | `/api/user/list`                            | Query: `page`,`page_size`         | `{"items":[],"total":n}`                        | Admin user list                                        |
| POST   | `/api/user/add`                             | `UserAddRequest`                  | `{"user_id"}`                                   | Admin create user                                      |
| POST   | `/api/user/delete`                          | `{"user_id"}`                     | `{}`                                            | Admin delete user                                      |
| GET    | `/api/user/config`                          | none                              | `{"config":{}}`                                 | Read current user config                               |
| POST   | `/api/user/config`                          | `{"config":{}}`                   | `{"config":{}}`                                 | Update current user config                             |


Compatibility paths:

- `/api/user/register`
- `/api/user/login`
- `/api/user/logout`
- `/api/user/check_login`

These are still present mostly for backward compatibility and are largely equivalent to the corresponding `/api/auth/*` endpoints.

### Chat and streaming


| Method | Path                                           | Request                    | Response            | Purpose                                                                                      |
| ------ | ---------------------------------------------- | -------------------------- | ------------------- | -------------------------------------------------------------------------------------------- |
| POST   | `/api/chat/optimize-input`                     | `UserInputOptimizeRequest` | `BaseResponse`      | Polish the current user input (synchronous JSON)                                             |
| POST   | `/api/chat/optimize-input/stream`              | same as above              | `text/plain` stream | Stream optimized chunks (one JSON object per line)                                           |
| POST   | `/api/chat`                                    | `ChatRequest`              | `text/plain` stream | Chat stream that requires `agent_id`                                                         |
| POST   | `/api/stream`                                  | `StreamRequest`            | `text/plain` stream | More generic stream; behavior resolved from stored agent / optional `agent_id` (see subpage) |
| POST   | `/api/web-stream`                              | `StreamRequest`            | `text/plain` stream | Web-managed stream; same-session re-entry interrupts the old run first                       |
| POST   | `/api/v2/agent/chat`                          | AG-UI `RunAgentInput`      | `text/event-stream` | Additive native AG-UI V2 stream; existing Sage stream endpoints remain unchanged             |
| GET    | `/api/stream/resume/{session_id}`              | Query: `last_index`        | `text/plain` stream | Resume an interrupted subscription                                                           |
| GET    | `/api/stream/active_sessions`                  | none                       | `text/event-stream` | Subscribe to active streaming sessions                                                       |
| POST   | `/api/conversations/{session_id}/rerun-stream` | `RerunStreamRequest`       | `text/plain` stream | Re-run from the last user message under the web stream manager                               |


### Conversations and history


| Method | Path                                                     | Request                                                           | `data` response             | Purpose                                                        |
| ------ | -------------------------------------------------------- | ----------------------------------------------------------------- | --------------------------- | -------------------------------------------------------------- |
| GET    | `/api/conversations`                                     | Query: `page`,`page_size`,`user_id`,`search`,`agent_id`,`sort_by` | paginated conversation list | Sidebar and search                                             |
| GET    | `/api/conversations/{session_id}/messages`               | none                                                              | message list                | Read conversation messages                                     |
| GET    | `/api/share/conversations/{session_id}/messages`         | none                                                              | message list                | Shared conversation view                                       |
| POST   | `/api/conversations/{session_id}/title`                  | `{"title"}`                                                       | update result               | Rename a conversation                                          |
| POST   | `/api/conversations/{session_id}/edit-last-user-message` | `{"content"}`                                                     | update result               | Edit the last user message in the session                      |
| DELETE | `/api/conversations/{session_id}`                        | none                                                              | `{"session_id"}`            | Delete conversation                                            |
| POST   | `/api/sessions/{session_id}/interrupt`                   | `{"message"}` optional                                            | interrupt result            | Stop a running session                                         |
| POST   | `/api/sessions/{session_id}/tasks_status`                | none                                                              | task status                 | In-conversation task status (not the `/tasks` scheduler below) |


### Planner and scheduled tasks (`/tasks`, not under `/api`)

Defined in `app/server/routers/task.py`. Most responses are **Pydantic models** or plain objects, not the `BaseResponse` envelope. Internal `.../internal/...` routes are for workers and ops; read [HTTP_API_TASKS.md](HTTP_API_TASKS.md) before calling them.


| Method | Path                                           | Request                               | Response (summary)      | Purpose                         |
| ------ | ---------------------------------------------- | ------------------------------------- | ----------------------- | ------------------------------- |
| GET    | `/tasks/one-time`                              | Query: `page`,`page_size`,`agent_id?` | paged one-time list     | List one-time tasks             |
| GET    | `/tasks/one-time/{task_id}`                    | none                                  | `TaskResponse`          | Read one                        |
| POST   | `/tasks/one-time`                              | `OneTimeTaskCreate`                   | `TaskResponse`          | Create                          |
| PUT    | `/tasks/one-time/{task_id}`                    | `OneTimeTaskUpdate`                   | `TaskResponse`          | Update                          |
| DELETE | `/tasks/one-time/{task_id}`                    | none                                  | `{"success":true}`      | Delete                          |
| GET    | `/tasks/recurring`                             | Query: `page`,`page_size`,`agent_id?` | paged list              | List recurring                  |
| GET    | `/tasks/recurring/{task_id}`                   | none                                  | `RecurringTaskResponse` | Read one                        |
| POST   | `/tasks/recurring`                             | `RecurringTaskCreate`                 | `RecurringTaskResponse` | Create (cron)                   |
| PUT    | `/tasks/recurring/{task_id}`                   | `RecurringTaskUpdate`                 | `RecurringTaskResponse` | Update                          |
| DELETE | `/tasks/recurring/{task_id}`                   | none                                  | `{"success":true}`      | Delete                          |
| POST   | `/tasks/recurring/{task_id}/toggle`            | `{"enabled": bool}`                   | `RecurringTaskResponse` | Enable/disable                  |
| GET    | `/tasks/recurring/{task_id}/history`           | Query: `page`,`page_size`             | history                 | History for a recurring job     |
| GET    | `/tasks/one-time/{task_id}/history`            | Query: `limit`                        | list                    | Short history for one-time      |
| POST   | `/tasks/internal/spawn-due`                    | none                                  | `{"items":[]}`          | Scheduler: materialize due work |
| GET    | `/tasks/internal/due`                          | Query: `limit`                        | `{"items":[]}`          | Pull due work items             |
| POST   | `/tasks/internal/one-time/{task_id}/claim`     | none                                  | `{"claimed":...}`       | Worker: claim a task            |
| POST   | `/tasks/internal/one-time/{task_id}/complete`  | `{"response"}` optional               | task                    | Mark success                    |
| POST   | `/tasks/internal/one-time/{task_id}/fail`      | `{"error_message"}` optional          | task                    | Mark failure                    |
| POST   | `/tasks/internal/recurring/{task_id}/complete` | none                                  | body                    | Mark a recurring run complete   |


### Agent


| Method | Path                                            | Request                                   | `data` response      | Purpose                                                       |
| ------ | ----------------------------------------------- | ----------------------------------------- | -------------------- | ------------------------------------------------------------- |
| GET    | `/api/agent/list`                               | none                                      | `AgentConfigDTO[]`   | List visible agents                                           |
| GET    | `/api/agent/template/default_system_prompt`     | Query: `language`                         | `{"content"}`        | Get default prompt template                                   |
| POST   | `/api/agent/create`                             | `AgentConfigDTO`                          | `{"agent_id"}`       | Create agent                                                  |
| GET    | `/api/agent/{agent_id}`                         | none                                      | `AgentConfigDTO`     | Read agent                                                    |
| PUT    | `/api/agent/{agent_id}`                         | `AgentConfigDTO`                          | `{"agent_id"}`       | Update agent                                                  |
| DELETE | `/api/agent/{agent_id}`                         | none                                      | `{"agent_id"}`       | Delete agent                                                  |
| POST   | `/api/agent/auto-generate`                      | `{"agent_description","available_tools"}` | generated config     | Generate agent draft                                          |
| POST   | `/api/agent/system-prompt/optimize`             | `{"original_prompt","optimization_goal"}` | optimized result     | Optimize system prompt                                        |
| GET    | `/api/agent/{agent_id}/auth`                    | none                                      | authorized user list | Read agent authorization                                      |
| POST   | `/api/agent/{agent_id}/auth`                    | `{"user_ids":[]}`                         | `{}`                 | Update agent authorization                                    |
| POST   | `/api/agent/{agent_id}/file_workspace`          | Query: `session_id`                       | workspace file list  | List workspace files                                          |
| GET    | `/api/agent/{agent_id}/file_workspace/download` | Query: `file_path`,`session_id?`          | file response        | Download workspace file                                       |
| DELETE | `/api/agent/{agent_id}/file_workspace/delete`   | Query: `file_path`,`session_id?`          | delete result        | Delete workspace file                                         |
| POST   | `/api/agent/auto-generate/submit`               | `AutoGenAgentRequest`                     | task submission      | Async agent generation; poll `GET /api/agent/tasks/{task_id}` |
| POST   | `/api/agent/system-prompt/optimize/submit`      | `SystemPromptOptimizeRequest`             | task submission      | Async prompt optimization                                     |
| POST   | `/api/agent/abilities`                          | `AgentAbilitiesRequest`                   | ability card payload | Build UI-facing ability cards for an agent                    |
| GET    | `/api/agent/tasks/{task_id}`                    | none                                      | async task           | Poll async work                                               |
| POST   | `/api/agent/tasks/{task_id}/cancel`             | none                                      | task                 | Request cancellation                                          |


### Tools, skills, MCP


| Method | Path                                   | Request                                        | `data` response            | Purpose                                                                                                   |
| ------ | -------------------------------------- | ---------------------------------------------- | -------------------------- | --------------------------------------------------------------------------------------------------------- |
| GET    | `/api/tools`                           | Query: `type`                                  | `{"tools":[]}`             | List tools                                                                                                |
| POST   | `/api/tools/exec`                      | `{"tool_name","tool_params"}`                  | tool result                | Execute a tool directly                                                                                   |
| GET    | `/api/skills`                          | Query: `agent_id`,`dimension`                  | `{"skills":[]}`            | List skills                                                                                               |
| GET    | `/api/skills/agent-available`          | Query: `agent_id`                              | `{"skills":[]}`            | List agent-available skills                                                                               |
| POST   | `/api/skills/upload`                   | `multipart/form-data`                          | `{"user_id"}`              | Upload skill ZIP                                                                                          |
| POST   | `/api/skills/import-url`               | `{"url","is_system","is_agent","agent_id"}`    | `{"user_id"}`              | Import skill from URL                                                                                     |
| DELETE | `/api/skills`                          | Query: `name`,`agent_id?`                      | empty result               | Delete skill                                                                                              |
| GET    | `/api/skills/content`                  | Query: `name`                                  | `{"content"}`              | Read `SKILL.md` content                                                                                   |
| PUT    | `/api/skills/content`                  | `{"name","content"}`                           | empty result               | Update `SKILL.md`                                                                                         |
| POST   | `/api/skills/sync-to-agent`            | `multipart/form-data`: `skill_name`,`agent_id` | result                     | Copy a skill into the **current** user's one agent workspace                                              |
| POST   | `/api/skills/sync-to-agent-workspaces` | `{"agent_id","skill_names?"}`                  | bulk summary               | Copy skills to **all** user workspaces for that agent                                                     |
| POST   | `/api/skills/sync-workspace-skills`    | `{"user_id","agent_id","purge_extra"}`         | result                     | Materialize the agent’s configured skills into the workspace tree; `purge_extra` may delete extra folders |
| POST   | `/api/mcp/add`                         | `MCPServerRequest`                             | `{"server_name","status"}` | Add MCP server                                                                                            |
| GET    | `/api/mcp/list`                        | none                                           | `{"servers":[]}`           | List MCP servers                                                                                          |
| DELETE | `/api/mcp/{server_name}`               | none                                           | `{"server_name"}`          | Delete MCP server                                                                                         |
| POST   | `/api/mcp/{server_name}/refresh`       | none                                           | `{"server_name","status"}` | Refresh MCP server                                                                                        |


### Providers, system, storage, and observability


| Method | Path                                     | Request                  | Response                                            | Purpose                                                     |
| ------ | ---------------------------------------- | ------------------------ | --------------------------------------------------- | ----------------------------------------------------------- |
| POST   | `/api/llm-provider/verify`               | `LLMProviderCreate`      | verify result                                       | Basic connectivity check                                    |
| POST   | `/api/llm-provider/verify-capabilities`  | `LLMProviderCreate`      | capability data                                     | Connect and probe capabilities (e.g. multimodal, JSON mode) |
| POST   | `/api/llm-provider/verify-multimodal`    | `LLMProviderCreate`      | verify result                                       | Image probe for multimodal                                  |
| GET    | `/api/llm-provider/list`                 | none                     | provider list                                       | List providers                                              |
| POST   | `/api/llm-provider/create`               | `LLMProviderCreate`      | `{"provider_id"}`                                   | Create and return the new id                                |
| PUT    | `/api/llm-provider/update/{provider_id}` | `LLMProviderUpdate`      | provider                                            | Update provider                                             |
| DELETE | `/api/llm-provider/delete/{provider_id}` | none                     | delete result                                       | Delete provider                                             |
| GET    | `/api/system/info`                       | none                     | public system config                                | Frontend bootstrap                                          |
| POST   | `/api/system/update_settings`            | `{"allow_registration"}` | `{}`                                                | Update system settings                                      |
| POST   | `/api/system/agent/usage-stats`          | `{"days","agent_id?"}`   | `{"usage":{...}}`                                   | Per-user agent call counts aggregated by day                |
| GET    | `/api/health`                            | none                     | `{"status","timestamp","service"}`                  | Health check                                                |
| GET    | `/active`                                | none                     | plain text                                          | Uvicorn root liveness, not JSON-wrapped                     |
| POST   | `/api/agent/workspace/delete`            | `{"agent_id","user_id"}` | `{"agent_id","user_id","workspace_path","deleted"}` | Delete a user's personal agent workspace                    |
| POST   | `/api/oss/upload`                        | `multipart/form-data`    | `{"url"}`                                           | Upload file to object storage                               |
| GET    | `/api/observability/jaeger/login`        | Query: `next?`           | 302 or error                                        | Gate entry into Jaeger                                      |
| GET    | `/api/observability/jaeger/auth`         | none                     | 204/401/403                                         | Check current Jaeger access                                 |
| GET    | `/api/observability/jaeger`              | none                     | 307                                                 | Redirect to Jaeger root                                     |
| ANY    | `/api/observability/jaeger/{full_path}`  | preserved request        | 307                                                 | Redirect to Jaeger path                                     |


## Key request and response models

### Registration and login

Registration:

```json
{
  "username": "alice",
  "password": "StrongPassword123"
}
```

Login:

```json
{
  "username": "alice",
  "password": "StrongPassword123"
}
```

Successful login `data`:

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "expires_in": 3600
}
```

### ChatRequest

Used by `/api/chat`, and it requires `agent_id`:

```json
{
  "messages": [
    {
      "message_id": "optional",
      "role": "user",
      "content": "Hello"
    }
  ],
  "session_id": "sess_123",
  "user_id": "optional",
  "system_context": {},
  "agent_id": "agent_abc",
  "provider_id": "provider_xxx",
  "fast_provider_id": "provider_fast_xxx"
}
```


| Field            | Meaning                                      |
| ---------------- | -------------------------------------------- |
| `messages`       | Message list                                 |
| `message_id`     | Optional message ID                          |
| `role`           | For example `user`, `assistant`, `system`    |
| `content`        | String or multimodal array                   |
| `session_id`     | Session ID                                   |
| `user_id`        | Usually injected from the session if omitted |
| `system_context` | Structured context object                    |
| `agent_id`       | Required target agent                        |
| `provider_id`    | Optional per-request main model provider override |
| `fast_provider_id` | Optional per-request fast model provider override |


### StreamRequest

`/api/stream` and `/api/web-stream` extend the chat payload with runtime override fields such as:

- `agent_name`
- `deep_thinking`
- `max_loop_count`
- `agent_mode`
- `more_suggest`
- `available_workflows`
- `llm_model_config`
- `system_prefix`
- `available_tools`
- `available_skills`
- `available_sub_agent_ids`
- `force_summary`
- `memory_type`
- `custom_sub_agents`
- `context_budget_config`
- `extra_mcp_config`

Use those fields when:

- You want per-request runtime overrides rather than only relying on saved agent config.

### RerunStreamRequest

Used by `POST /api/conversations/{session_id}/rerun-stream`. All fields are optional; the server fills defaults from the stored conversation if omitted.


| Field                     | Meaning                                                        |
| ------------------------- | -------------------------------------------------------------- |
| `agent_id`                | Force which agent to run; defaults to the conversation’s agent |
| `agent_mode`              | Agent mode for this rerun                                      |
| `more_suggest`            | Ask for more suggestions                                       |
| `max_loop_count`          | Max tool/reasoning loop count for this run                     |
| `available_sub_agent_ids` | Allowed sub-agents for this run                                |


### UserInputOptimizeRequest

Used by `POST /api/chat/optimize-input` and `.../stream`.


| Field                                 | Meaning                                                  |
| ------------------------------------- | -------------------------------------------------------- |
| `current_input`                       | Required: text to refine                                 |
| `history_messages`                    | Optional display history (`role` + `content`)            |
| `session_id` / `agent_id` / `user_id` | Optional; `user_id` is taken from the session if missing |


### AgentConfigDTO

```json
{
  "id": "optional",
  "user_id": "optional",
  "name": "Research Agent",
  "systemPrefix": "You are a careful research assistant.",
  "systemContext": {},
  "availableWorkflows": {},
  "availableTools": ["web_search"],
  "availableSubAgentIds": [],
  "availableSkills": ["market-research"],
  "memoryType": "session",
  "maxLoopCount": 10,
  "deepThinking": false,
  "llm_provider_id": "provider_xxx",
  "enableMultimodal": false,
  "agentMode": "team",
  "description": "Handles market research"
}
```

### LLMProviderCreate

```json
{
  "name": "OpenAI Compatible",
  "base_url": "https://api.example.com/v1",
  "api_keys": ["sk-xxxx"],
  "model": "gpt-4o",
  "max_tokens": 4096,
  "temperature": 0.7,
  "top_p": 1,
  "presence_penalty": 0,
  "max_model_len": 128000,
  "supports_multimodal": true,
  "is_default": true
}
```

Constraint:

- `api_keys` must contain exactly one non-empty single-line key

### MCPServerRequest

```json
{
  "name": "docs-mcp",
  "protocol": "streamable_http",
  "streamable_http_url": "https://mcp.example.com",
  "sse_url": null,
  "api_key": "secret"
}
```

## Field-level notes

### `AgentConfigDTO` field table


| Field                     | Type     | Meaning                   | When to use it                         |
| ------------------------- | -------- | ------------------------- | -------------------------------------- |
| `name`                    | string   | Agent name                | Required for create and display        |
| `systemPrefix`            | string   | System prompt             | Define the agent's role and behavior   |
| `systemContext`           | object   | Structured context        | Inject fixed context into the agent    |
| `availableWorkflows`      | object   | Workflow mapping          | When the agent should expose workflows |
| `availableTools`          | string[] | Allowed tools             | Restrict or grant tool usage           |
| `availableSubAgentIds`    | string[] | Allowed sub-agent IDs     | Multi-agent orchestration              |
| `availableSkills`         | string[] | Allowed skills            | When the agent should use skills       |
| `memoryType`              | string   | Memory mode               | Usually `session`                      |
| `maxLoopCount`            | integer  | Loop upper bound          | Limit runtime depth/cost               |
| `deepThinking`            | boolean  | Deeper reasoning mode     | Complex reasoning runs                 |
| `llm_provider_id`         | string   | Bound provider ID         | Pin the model provider                 |
| `enableMultimodal`        | boolean  | Enable multimodal support | Image-capable flows                    |
| `agentMode`               | string   | Agent mode                | `simple`, `fibre`, or `team`           |
| `description`             | string   | Agent description         | Management UI and generation flows     |


### Extra `StreamRequest` fields


| Field                       | Type     | Meaning                        | When to use it                       |
| --------------------------- | -------- | ------------------------------ | ------------------------------------ |
| `agent_name`                | string   | Temporary agent name override  | Debug or temporary presentation      |
| `deep_thinking`             | boolean  | Per-request deep reasoning     | One-off heavier reasoning            |
| `max_loop_count`            | integer  | Per-request loop cap           | Control cost or depth                |
| `agent_mode`                | string   | Per-request agent mode         | `simple`, `fibre`, or `team`         |
| `more_suggest`              | boolean  | Return more suggestions        | UI wants extra candidate suggestions |
| `available_workflows`       | object   | Temporary workflows            | Inject workflows per request         |
| `llm_model_config`          | object   | Temporary model config         | Override model settings              |
| `system_prefix`             | string   | Temporary system prompt        | Change only one request              |
| `available_tools`           | string[] | Temporary tool list            | Narrow or broaden allowed tools      |
| `available_skills`          | string[] | Temporary skill list           | Narrow or broaden allowed skills     |
| `available_sub_agent_ids`   | string[] | Temporary sub-agent list       | Control which sub-agents may run     |
| `force_summary`             | boolean  | Force a summary                | Require a closing summary            |
| `memory_type`               | string   | Temporary memory mode          | Override memory strategy             |
| `custom_sub_agents`         | array    | Inline sub-agent configs       | Use ad-hoc sub-agents                |
| `context_budget_config`     | object   | Context budget settings        | Control request budgeting; main history is compacted only by persistent model summaries |
| `extra_mcp_config`          | object   | Extra MCP config               | Attach MCP config per request        |


### `LLMProviderCreate` field table


| Field                 | Type     | Meaning                        | Notes                                             |
| --------------------- | -------- | ------------------------------ | ------------------------------------------------- |
| `name`                | string   | Provider name                  | Display label                                     |
| `base_url`            | string   | OpenAI-compatible API base URL | Often ends with `/v1`                             |
| `api_keys`            | string[] | API key list                   | Current code only allows 1 key                    |
| `model`               | string   | Model name                     | For example `gpt-4o`                              |
| `max_tokens`          | integer  | Max output tokens              | Optional                                          |
| `temperature`         | float    | Sampling temperature           | Optional                                          |
| `top_p`               | float    | Top-p parameter                | Optional                                          |
| `presence_penalty`    | float    | Presence penalty               | Optional                                          |
| `max_model_len`       | integer  | Context window size            | Optional                                          |
| `supports_multimodal` | boolean  | Multimodal capability flag     | Used by UI and checks                             |
| `is_default`          | boolean  | Default provider flag          | Current create path ultimately stores non-default |


### `MCPServerRequest` field table


| Field                 | Type   | Meaning                  | Notes                                                |
| --------------------- | ------ | ------------------------ | ---------------------------------------------------- |
| `name`                | string | MCP server name          | Avoid duplicates                                     |
| `protocol`            | string | Protocol type            | Current code comments say `streamable_http` or `sse` |
| `streamable_http_url` | string | Streamable HTTP endpoint | Used for `streamable_http`                           |
| `sse_url`             | string | SSE endpoint             | Used for `sse`                                       |
| `api_key`             | string | Access secret            | Optional                                             |


## Common error responses

### Not logged in

Common on:

- `GET /api/auth/session`
- `GET /api/user/options`
- `POST /api/user/change-password`
- `GET /api/user/config`

Example:

```json
{
  "code": 401,
  "message": "未登录",
  "data": null,
  "timestamp": 1710000000.123
}
```

### Permission denied

Common on:

- `GET /api/user/list`
- `POST /api/user/add`
- `POST /api/user/delete`
- `POST /api/system/update_settings`
- `GET /api/observability/jaeger/auth`

Example:

```json
{
  "code": 403,
  "message": "权限不足",
  "data": null,
  "timestamp": 1710000000.123
}
```

### Local registration disabled

Common on:

- `POST /api/auth/register`
- matching compatibility endpoints under `/api/user/*`

Examples:

```json
{
  "code": 400,
  "message": "当前服务未启用本地账号密码登录",
  "data": null,
  "timestamp": 1710000000.123
}
```

or

```json
{
  "code": 400,
  "message": "当前服务未启用本地账号注册",
  "data": null,
  "timestamp": 1710000000.123
}
```

### Provider not found or not editable

Common on:

- `PUT /api/llm-provider/update/{provider_id}`
- `DELETE /api/llm-provider/delete/{provider_id}`

Examples:

```json
{
  "code": 500,
  "message": "Provider not found",
  "data": null,
  "timestamp": 1710000000.123
}
```

or

```json
{
  "code": 500,
  "message": "Cannot delete default provider",
  "data": null,
  "timestamp": 1710000000.123
}
```

Notes:

- These are business-error envelopes, not necessarily the HTTP status codes you might expect
- This reflects current code behavior, not an idealized API design

### Tool missing or execution failed

Common on:

- `POST /api/tools/exec`

Typical causes:

- wrong `tool_name`
- tool manager not initialized
- no permission for an MCP-backed tool
- runtime exception inside the tool

Many of these cases go through exception paths, so the real failure response is not always a clean `BaseResponse` success-style envelope. Handle them as failure branches on the client side.

### Invalid chat request

Common on:

- `POST /api/chat`
- `POST /api/stream`
- `POST /api/web-stream`

Most typical case:

- empty `messages`

These cases raise business exceptions such as "消息列表不能为空".

## Common `curl` examples

### 1. Login and save cookies

```bash
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"StrongPassword123"}'
```

### 2. Read current session state

```bash
curl -b cookies.txt http://127.0.0.1:8000/api/auth/session
```

### 3. Start a streaming chat

```bash
curl -N -b cookies.txt -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{
    "messages":[{"role":"user","content":"Summarize the repository structure."}],
    "session_id":"sess_123",
    "agent_id":"agent_abc"
  }'
```

### 4. Resume a stream

```bash
curl -N http://127.0.0.1:8000/api/stream/resume/sess_123?last_index=15
```

### 5. Create an agent

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/agent/create \
  -H 'Content-Type: application/json' \
  -d '{
    "name":"Research Agent",
    "systemPrefix":"You are a careful research assistant.",
    "availableTools":["web_search"],
    "availableSkills":["market-research"],
    "memoryType":"session",
    "maxLoopCount":10
  }'
```

### 6. Execute a tool

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/tools/exec \
  -H 'Content-Type: application/json' \
  -d '{
    "tool_name":"web_search",
    "tool_params":{"query":"Sage repository"}
  }'
```

### 7. Import a skill from URL

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/skills/import-url \
  -H 'Content-Type: application/json' \
  -d '{
    "url":"https://example.com/skill.zip",
    "is_system":false,
    "is_agent":false,
    "agent_id":null
  }'
```

### 7.1 Bulk sync agent workspace skills

```bash
curl -b cookies.txt -X POST http://127.0.0.1:8000/api/skills/sync-to-agent-workspaces \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_id":"agent_xxx",
    "skill_names":["research-helper","writer-helper"]
  }'
```

When `skill_names` is omitted, the server syncs every skill listed in the agent's `availableSkills` / `available_skills` into all existing `agents/{user_id}/{agent_id}` workspaces.

### 8. Upload a file to OSS

```bash
curl -X POST http://127.0.0.1:8000/api/oss/upload \
  -F 'file=@./example.png' \
  -F 'path=uploads/images'
```

## Notes

- This page keeps only information that is real in the current codebase and useful for integrators; it was cross-checked against the routers in `app/server/routers`. Extra routes from `app/desktop/`, etc., are not listed here.
- Old paths, guessed behavior, and historical noise have been minimized.
- If this page gets extended further, the next useful additions are error response examples and field-level enum notes, not more prose.
