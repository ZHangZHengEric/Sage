---
layout: default
title: Architecture Guide
nav_order: 5
description: "Current Sage architecture overview"
---

# Architecture Guide

This page describes the architecture that is visible in the current repository.

## 1. Top-Level Layout

The active codebase is organized around these areas:

- `sagents/`: core runtime, flow execution, session state, tools, skills, sandbox, observability
- `app/server/`: FastAPI backend and Vue web app
- `app/desktop/`: desktop backend, Vue UI, and Tauri shell
- `examples/`: standalone CLI, Streamlit demo, and example server
- `mcp_servers/`: built-in MCP server implementations

## 2. Core Runtime Model

The current runtime entry point is `SAgent` in [`sagents/sagents.py`](../sagents/sagents.py).

`SAgent` is intentionally thin:

- validates runtime parameters
- resolves session identity
- configures a `Session`
- builds or accepts an `AgentFlow`
- streams visible `MessageChunk` output back to the caller

The runtime state itself lives in `SessionContext`, not in `SAgent`.

## 3. Main Architectural Split

Sage is easiest to understand as four layers:

1. entry layer
2. session/state layer
3. execution/flow layer
4. capability layer

### Entry Layer

- `examples/sage_cli.py`
- `examples/sage_server.py`
- `app/server/main.py`
- `app/desktop/core/main.py`

These are different shells around the same `sagents` runtime.

### Session / State Layer

The important pieces are:

- [`sagents/session_runtime.py`](../sagents/session_runtime.py)
- [`sagents/context/session_context.py`](../sagents/context/session_context.py)
- [`sagents/context/messages/`](../sagents/context/messages)
- [`sagents/context/user_memory/`](../sagents/context/user_memory)

Responsibilities:

- create or resume sessions
- merge persisted and incoming `system_context`
- manage workspace and file permissions
- hold message history, task state, user memory, workflow data, and runtime metadata

### Execution / Flow Layer

The flow system is defined by:

- [`sagents/flow/schema.py`](../sagents/flow/schema.py)
- [`sagents/flow/executor.py`](../sagents/flow/executor.py)
- [`sagents/agent/`](../sagents/agent)

`SAgent` builds a default `AgentFlow` when `custom_flow` is not provided.

### Capability Layer

The main capability managers are:

- [`sagents/tool/tool_manager.py`](../sagents/tool/tool_manager.py)
- [`sagents/skill/skill_manager.py`](../sagents/skill/skill_manager.py)
- [`sagents/utils/sandbox/`](../sagents/utils/sandbox)
- [`sagents/observability/`](../sagents/observability)

## 4. Default Execution Flow

The default flow is assembled in [`sagents/sagents.py`](../sagents/sagents.py).

At a high level:

1. `task_router`
2. optional `task_analysis` when `deep_thinking` is enabled
3. switch on `agent_mode`
4. optional follow-up suggestion generation

### `agent_mode = simple`

Default path:

- `tool_suggestion` and `memory_recall` in parallel
- `simple`
- optional `task_summary`

### `agent_mode = multi`

Default path:

- `memory_recall`
- loop of `task_planning` -> `tool_suggestion` -> `task_executor` -> `task_observation` -> `task_completion_judge`
- `task_summary`

### `agent_mode = fibre`

Default path:

- `tool_suggestion` and `memory_recall` in parallel
- `fibre`

This is the mode that enables the repository’s parallel / delegated orchestration path.

## 5. Session Lifecycle

The session lifecycle is implemented around `Session` and `SessionManager` in [`sagents/session_runtime.py`](../sagents/session_runtime.py).

High-level sequence:

1. runtime config is attached to the session
2. saved `system_context` may be loaded from disk
3. `SessionContext` is created and initialized
4. flow execution runs against that context
5. visible chunks are streamed outward
6. session status can be queried, saved, interrupted, or cleaned up

## 6. Tools, Skills, And MCP

### Tools

`ToolManager`:

- discovers normal Python tools
- discovers built-in MCP-style tools
- can initialize external MCP-backed tools

### Skills

`SkillManager` loads host-side `SKILL.md` packages and exposes metadata and instruction bodies to the runtime.

### MCP

The repo contains built-in MCP server implementations under [`mcp_servers/`](../mcp_servers).

## 7. Sandbox And Workspace

Sandboxing is handled under [`sagents/utils/sandbox/`](../sagents/utils/sandbox).

The runtime currently supports these sandbox modes:

- `local`
- `remote`
- `passthrough`

For `local` and `passthrough`, `sandbox_agent_workspace` is required by `SAgent.run_stream()`.

## 8. Service Architecture

### Server

[`app/server/main.py`](../app/server/main.py) creates the FastAPI service and registers routers from [`app/server/routers/`](../app/server/routers).

Notable surfaces:

- chat and stream endpoints
- agent management
- tools / skills / MCP management
- knowledge base
- auth and OAuth2
- observability proxying

### Desktop

[`app/desktop/core/main.py`](../app/desktop/core/main.py) runs a desktop-local backend. The UI is in [`app/desktop/ui`](../app/desktop/ui), and Tauri packaging is under [`app/desktop/tauri`](../app/desktop/tauri).

## 9. Architectural Notes

- `SAgent` is the orchestration entry, not the long-lived state container.
- `SessionContext` is the main state boundary.
- `AgentFlow` is the runtime control graph.
- `ToolManager`, `SkillManager`, sandbox, and observability are pluggable capability layers around that graph.

## 10. Compatibility Note

Older materials may describe `AgentController`, `agents.*`, or older multi-agent pipeline terminology. The current architecture should be read from `sagents/`, `app/server/`, `app/desktop/`, and `examples/`.
