---
layout: default
title: API Reference
nav_order: 8
description: "Current API reference for Sage runtime and server endpoints"
---

{: .note }
> Looking for Chinese? See [API 参考](API_REFERENCE_CN.html).

# Sage API Reference

This page reflects the current public surfaces that are visible in the repository: the Python runtime centered on `SAgent`, and the FastAPI endpoints under `app/server/routers/`.

## Python Runtime

### `SAgent`

Defined in [`sagents/sagents.py`](../sagents/sagents.py).

```python
from sagents.sagents import SAgent

agent = SAgent(
    session_root_space="./agent_sessions",
    enable_obs=True,
    sandbox_type="local",
)
```

#### Constructor

| Parameter | Type | Description |
|---|---|---|
| `session_root_space` | `str` | Root directory used by the global session manager |
| `enable_obs` | `bool` | Enables observability hooks |
| `sandbox_type` | `str \| None` | Default sandbox mode, typically `local`, `remote`, or `passthrough` |

#### `run_stream()`

`SAgent.run_stream()` is the main execution entry point.

```python
async def run_stream(
    input_messages,
    model,
    model_config,
    system_prefix,
    default_memory_type,
    sandbox_type=None,
    sandbox_agent_workspace=None,
    volume_mounts=None,
    sandbox_id=None,
    tool_manager=None,
    skill_manager=None,
    session_id=None,
    user_id=None,
    agent_id=None,
    deep_thinking=None,
    max_loop_count=50,
    agent_mode=None,
    more_suggest=False,
    force_summary=False,
    system_context=None,
    available_workflows=None,
    context_budget_config=None,
    custom_sub_agents=None,
    custom_flow=None,
)
```

Important parameters:

| Parameter | Description |
|---|---|
| `input_messages` | Input message list, either plain dicts or `MessageChunk` objects |
| `model` | OpenAI-compatible async client |
| `model_config` | Runtime model config, usually including `model` |
| `system_prefix` | Base system prompt |
| `default_memory_type` | Memory mode passed into the session |
| `sandbox_agent_workspace` | Required for `local` and `passthrough` sandbox modes |
| `tool_manager` | Tool registry and MCP-backed tool access |
| `skill_manager` | Skill registry used by the runtime |
| `agent_mode` | `simple`, `multi`, or `fibre` |
| `deep_thinking` | Enables the analysis stage before execution |
| `system_context` | Shared per-session context merged into runtime state |
| `custom_flow` | Replaces the default flow with a custom `AgentFlow` |

Notes:

- If `session_id` is omitted, `run_stream()` creates one.
- In `local` mode, `sandbox_agent_workspace` is mandatory.
- The runtime yields lists of `MessageChunk`; only chunks with visible content, tool calls, or token usage are emitted outward.

### `ToolManager`

Defined in [`sagents/tool/tool_manager.py`](../sagents/tool/tool_manager.py).

```python
from sagents.tool import ToolManager

tool_manager = ToolManager()
```

Behavior:

- auto-discovers Python tools under `sagents/tool/`
- auto-discovers built-in MCP tools
- can later initialize MCP server-backed tools asynchronously

### `SkillManager`

Defined in [`sagents/skill/skill_manager.py`](../sagents/skill/skill_manager.py).

```python
from sagents.skill import SkillManager

skill_manager = SkillManager(skill_dirs=["app/skills"])
```

Behavior:

- loads `SKILL.md` based skill packages from configured host directories
- exposes metadata and instructions for runtime injection

## FastAPI Server

The maintained HTTP service entry point is [`app/server/main.py`](../app/server/main.py).

### Health

#### `GET /active`

Simple liveness endpoint.

### Chat

Defined in [`app/server/routers/chat.py`](../app/server/routers/chat.py).

#### `POST /api/chat`

Starts a streaming chat session using an `agent_id`.

Request body:

```json
{
  "messages": [
    { "role": "user", "content": "Summarize this repo." }
  ],
  "agent_id": "my-agent",
  "session_id": "optional-session-id",
  "user_id": "optional-user-id",
  "system_context": {}
}
```

#### `POST /api/stream`

Streaming endpoint without requiring `agent_id` in the request schema.

Important request fields from [`app/server/schemas/chat.py`](../app/server/schemas/chat.py):

- `messages`
- `session_id`
- `user_id`
- `system_context`
- `agent_mode`
- `deep_thinking`
- `max_loop_count`
- `available_tools`
- `available_skills`
- `available_workflows`
- `custom_sub_agents`
- `context_budget_config`
- `extra_mcp_config`

#### `POST /api/web-stream`

Authenticated streaming endpoint used by the web UI.

#### `GET /api/stream/resume/{session_id}`

Resumes stream subscription for an existing session.

#### `GET /api/stream/active_sessions`

SSE endpoint that reports currently active streaming sessions.

## Agent Configuration DTO

The server exposes an agent config model in [`app/server/routers/agent.py`](../app/server/routers/agent.py).

Important fields:

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

## Startup Configuration

Server startup config is defined in [`app/server/core/config.py`](../app/server/core/config.py).

Frequently used environment variables:

- `SAGE_PORT`
- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_DEFAULT_LLM_API_BASE_URL`
- `SAGE_DEFAULT_LLM_MODEL_NAME`
- `SAGE_SESSION_DIR`
- `SAGE_LOGS_DIR_PATH`
- `SAGE_AGENTS_DIR`
- `SAGE_SKILL_WORKSPACE`
- `SAGE_DB_TYPE`

## Compatibility Note

Older docs may still mention `AgentController`, `agents.*`, or the deprecated `deep_research` flag. Those names are part of older layouts or compatibility surfaces and are not the main runtime entry point in the current repository.
