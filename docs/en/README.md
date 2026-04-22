---
layout: default
title: Overview
nav_order: 1
description: "Task-oriented documentation for the current Sage repository"
permalink: /en/
lang: en
ref: home
---

{% include lang_switcher.html %}

# Sage Documentation

This site documents the current repository as it exists today. It is organized around the real entry points in `examples/`, `app/server/`, `app/desktop/`, `sagents/`, and `mcp_servers/`.

## Who This Is For

- Users who want to run Sage locally
- Contributors who need to understand the runtime and application layout
- Integrators extending Sage through tools, skills, APIs, or MCP servers

## Start Here

1. [Getting Started](GETTING_STARTED.md) for local setup and first run
2. [CLI Guide](CLI.md) for command-line workflows and local validation
2. [Core Concepts](CORE_CONCEPTS.md) for the runtime model
3. [Architecture](ARCHITECTURE.md) for repository and subsystem boundaries
4. [Configuration](CONFIGURATION.md) for environment variables and deployment knobs

## Common Reading Paths

### I want to run Sage locally

Read:

1. [Getting Started](GETTING_STARTED.md)
2. [CLI Guide](CLI.md)
2. [Applications](APPLICATIONS.md)
3. [Troubleshooting](TROUBLESHOOTING.md)

### I want to extend the runtime

Read:

1. [Core Concepts](CORE_CONCEPTS.md)
2. [Architecture](ARCHITECTURE.md)
3. [MCP Servers](MCP_SERVERS.md)
4. [Development](DEVELOPMENT.md)

### I want to integrate with the server

Read:

1. [Getting Started](GETTING_STARTED.md)
2. [Configuration](CONFIGURATION.md)
3. [API Reference](API_REFERENCE.md)
4. [HTTP API Reference](HTTP_API_REFERENCE.md)

## Documentation Map

- [Getting Started](GETTING_STARTED.md): install dependencies and run the CLI, server, web UI, or desktop build
- [CLI Guide](CLI.md): command-line workflows, sessions, skills, workspaces, and structured output
- [Core Concepts](CORE_CONCEPTS.md): sessions, agents, tools, skills, flows, and sandboxing
- [Architecture](ARCHITECTURE.md): how the codebase is organized (with sub-chapters)
  - App layer: [Server](ARCHITECTURE_APP_SERVER.md) · [Desktop](ARCHITECTURE_APP_DESKTOP.md) · [Other entries](ARCHITECTURE_APP_OTHERS.md)
  - sagents core: [Overview](ARCHITECTURE_SAGENTS_OVERVIEW.md) · [Agent / Flow](ARCHITECTURE_SAGENTS_AGENT_FLOW.md) · [Session / Context](ARCHITECTURE_SAGENTS_SESSION_CONTEXT.md) · [Tool / Skill](ARCHITECTURE_SAGENTS_TOOL_SKILL.md) · [Sandbox / LLM / Obs](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)
- [Configuration](CONFIGURATION.md): runtime environment variables and storage settings
- [Applications](APPLICATIONS.md): which app surface to use for which job
- [MCP Servers](MCP_SERVERS.md): built-in MCP servers and how they fit into the platform
- [API Reference](API_REFERENCE.md): main HTTP route groups and streaming endpoints
- [HTTP API Reference](HTTP_API_REFERENCE.md): current backend HTTP endpoints, request and response bodies, and curl examples
  - Subpages: [Auth and users](HTTP_API_AUTH_USER.md) · [Chat and streaming](HTTP_API_CHAT.md) · [Agent extras](HTTP_API_AGENT.md) · [Knowledge base (RAG)](HTTP_API_KNOWLEDGE_BASE.md) · [Tools, skills, and MCP](HTTP_API_TOOLS_MCP.md) · [Planner /tasks](HTTP_API_TASKS.md) · [Platform and observability](HTTP_API_PLATFORM.md)
- [OAuth2 Lage Integration Guide](../zh/OAUTH2_LAGE_INTEGRATION.md): restored OAuth2 integration guide from historical docs
- [Development](DEVELOPMENT.md): contributor workflow and source locations
- [Memory Search Validation](MEMORY_SEARCH_VALIDATION.md): unified validation entry for the current memory-search workstream
- [Troubleshooting](TROUBLESHOOTING.md): common startup and environment issues

## Current Product Surfaces

### Lightweight examples

- `sage run` / `sage chat` / `sage doctor`: development CLI entry points
- `examples/sage_demo.py`: Streamlit demo
- `examples/sage_server.py`: standalone FastAPI example service

### Main application server

- `app/server/main.py`: primary FastAPI application entry point
- `app/server/web/`: Vue 3 + Vite web client

Use this path when you want the full product surface instead of a demo.

### Desktop app

- `app/desktop/entry.py`: desktop bootstrap entry
- `app/desktop/core/main.py`: desktop-local FastAPI backend
- `app/desktop/ui/`: desktop UI

Use this path when you need the packaged desktop experience rather than the browser-based app.

### Core runtime

- `sagents/sagents.py`: `SAgent` streaming runtime entry
- `sagents/agent/`: agent implementations
- `sagents/tool/`: tool system and MCP proxy support
- `sagents/skill/`: skill loading and execution
- `sagents/utils/sandbox/`: sandbox abstractions and providers

## Documentation Principles

- This documentation prefers current source accuracy over historical completeness.
- Historical migration notes and duplicate site pages have been removed from the primary doc set.
- The root repository `README.md` remains the marketing and project overview document; this site is the technical source of truth.
