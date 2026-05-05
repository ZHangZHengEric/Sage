---
layout: default
title: Python runtime API
parent: API documentation
nav_order: 2
description: "Runtime embedding API aligned with sagents: SAgent, tools, and streaming messages (not the main HTTP app)"
lang: en
ref: api-reference
---

{% include lang_switcher.html %}

{: .note }
> Chinese version: [Python 运行时 API](../zh/API_REFERENCE.md)

{: .note }
> For **HTTP** integration with the hosted app, use [HTTP API Reference](HTTP_API_REFERENCE.md). This page documents the **Python** surface of the `sagents` package as implemented in this repo. See also [Core Concepts](CORE_CONCEPTS.md) and `sagents/sagents.py`.

## Table of Contents
{: .no_toc .text-delta }

1. TOC
{:toc}

# Python runtime API

## 1. Entry point: `SAgent`

Defined in `sagents/sagents.py`. This is the supported streaming runtime entry (legacy v0.9 names such as `AgentController` do not match the current main code path).

```python
from sagents.sagents import SAgent

agent = SAgent(
    session_root_space="/path/to/session/storage",
    enable_obs=True,
    sandbox_type=None,  # optional; can also use SAGE_SANDBOX_MODE or the instance default
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_root_space` | `str` | Root directory for session persistence (required) |
| `enable_obs` | `bool` | Enable observability hooks (default `True`) |
| `sandbox_type` | `Optional[str]` | `"local"` \| `"remote"` \| `"passthrough"`; if omitted, `SAGE_SANDBOX_MODE` or default `local` applies |

## 2. Core method: `run_stream`

**Async generator** that yields lists of `MessageChunk` (often a single element). Consume with `async for`.

**Required / validated arguments:**

- `model` — must be non-empty (e.g. OpenAI-compatible async client).
- `model_config` — non-empty `dict`.
- `max_loop_count` — must not be `None` (explicit check).
- `system_prefix` — system prompt prefix string.

**Sandbox:**

- `sandbox_type` for the call overrides the instance default; effective order is **argument &gt; instance &gt; `SAGE_SANDBOX_MODE` &gt; `local`**.
- `local` / `passthrough`: `sandbox_agent_workspace` is required.
- `remote`: if `sandbox_agent_workspace` is missing, the implementation defaults it to `"/sage-workspace"`; `sandbox_id` is optional for reusing a remote sandbox.

**Other important parameters:**

| Parameter | Description |
|-----------|-------------|
| `input_messages` | `List[dict]` or `List[MessageChunk]`; `session_id` can be filled from the first message or generated |
| `tool_manager` / `skill_manager` | `ToolManager` / `ToolProxy` and `SkillManager` / `SkillProxy` |
| `agent_mode` | `"simple"` \| `"multi"` \| `"fibre"` — selects the default `AgentFlow` |
| `custom_flow` | If set, the built-in default flow is **not** used |
| `custom_sub_agents` | Sub-agent configuration list |
| `system_context` | Extra system context `dict` |
| `available_workflows` | Uses `{}` internally if omitted |
| `context_budget_config` | Context budget controls |
| `volume_mounts` | List of `VolumeMount` from `sagents.utils.sandbox.config` |
| `deep_thinking` | Legacy; prefer message-level tags such as `&lt;enable_deep_thinking&gt;` |

The method ends a session in `finally` by calling `close_session` on the session manager. See the source for exact observability and chunk-yielding behavior.

**Minimal example:**

```python
async for chunks in agent.run_stream(
    input_messages=[{"role": "user", "content": "Hello"}],
    model=client,
    model_config={"model": "gpt-4o", "api_key": "...", "base_url": "https://..."},
    system_prefix="You are a helpful assistant.",
    max_loop_count=10,
    sandbox_agent_workspace="/abs/path/to/agent/workspace",
    volume_mounts=[],
):
    for chunk in chunks:
        print(chunk.content)
```

## 3. Session helpers on `SAgent`

Thin wrappers on the global session manager (`sagents/session_runtime.py`):

- `get_session_status`, `list_active_sessions`, `cleanup_session`, `save_session`, `interrupt_session`, `get_tasks_status`

### Runtime guidance helpers

These helpers let host code add user guidance to a live session without interrupting it. The message is queued on `SessionContext.pending_user_injections`; the agent drains that queue before the next LLM request, persists the drained items as normal user messages, and yields them back in the stream with `metadata.guidance_id`.

| Method | Return | Notes |
| --- | --- | --- |
| `inject_user_message(session_id, content, guidance_id=None, metadata=None)` | `str` | Queues one guidance message and returns the effective `guidance_id`. |
| `list_pending_user_injections(session_id)` | `List[dict]` | Snapshot of queued, not-yet-consumed guidance messages. |
| `update_pending_user_injection(session_id, guidance_id, content)` | `bool` | Updates queued content; `False` means missing or already consumed. |
| `delete_pending_user_injection(session_id, guidance_id)` | `bool` | Deletes a queued message; `False` means missing or already consumed. |

Example:

```python
guidance_id = agent.inject_user_message(
    session_id="sess_123",
    content="Please prioritize the failing test first",
    guidance_id="ui-guidance-1",
    metadata={"source_ui": "guidance_area"},
)

pending = agent.list_pending_user_injections("sess_123")
agent.update_pending_user_injection(
    "sess_123",
    guidance_id,
    "Please prioritize the failing test and summarize the fix",
)
agent.delete_pending_user_injection("sess_123", guidance_id)
```

`inject_user_message` raises `LookupError` if the target session is not live and `ValueError` if `content` is empty. The update/delete helpers operate only on pending messages; after consumption, the guidance is a normal persisted user message.

## 4. Default flow and `agent_mode`

If `custom_flow` is omitted, `_build_default_flow` builds a graph with `sagents/flow/schema.py` node types. High-level behavior is described in [Core Concepts](CORE_CONCEPTS.md) and [ARCHITECTURE_SAGENTS_AGENT_FLOW.md](ARCHITECTURE_SAGENTS_AGENT_FLOW.md).

## 5. Tools and skills

### 5.1 `ToolManager`

- File: `sagents/tool/tool_manager.py`
- Can behave as a singleton; use `isolated=True` for a dedicated instance
- Auto-discovery: `discover_tools_from_path()` (under `sagents/tool/impl`), `discover_builtin_mcp_tools_from_path()` (under `mcp_servers`)
- Typical methods: `register_tool`, `register_tools_from_object`, `list_tools` / `list_tools_simplified` / `get_openai_tools`, `run_tool_async`, plus MCP registration helpers

### 5.2 `@tool` decorator

- File: `sagents/tool/tool_base.py`  
- See the decorator’s docstring for i18n fields and `param_schema`

### 5.3 `SkillManager`

- File: `sagents/skill/skill_manager.py`  
- Discovers and loads `SKILL.md` on the host; copying into the sandbox is handled with `SessionContext` and the sandbox layer

## 6. `MessageChunk` and `MessageType`

- File: `sagents/context/messages/message.py`  
- `MessageChunk` holds streaming pieces (`role`, `content`, `tool_calls`, `message_id`, `message_type`, etc.)  
- `MessageType` enumerates values such as `user_input`, `assistant_text`, `task_analysis`, `tool_call`, plus legacy compatibility for older stored messages

## 7. Environment

| Variable | Role |
|----------|------|
| `SAGE_SANDBOX_MODE` | Default sandbox mode: `local` / `remote` / `passthrough` |

## 8. Example in this repo

- `examples/sage_server.py` — FastAPI + SSE example built on `SAgent`

The [HTTP API Reference](HTTP_API_REFERENCE.md) documents the **FastAPI** app under `app/server/routers` only; it is not a substitute for this Python API.
