---
layout: default
title: Home
nav_order: 1
description: "Documentation index for the current Sage codebase"
permalink: /
---

# Sage Documentation

This documentation matches the current repository structure built around `sagents/`, `examples/`, `app/server`, and `app/desktop`.

## Language

| English | 中文 |
|:--|:--|
| [Quick Start](QUICK_START.html) | [快速开始](QUICK_START_CN.html) |
| [Architecture](ARCHITECTURE.html) | [架构](ARCHITECTURE_CN.html) |
| [API Reference](API_REFERENCE.html) | [API 参考](API_REFERENCE_CN.html) |
| [Configuration](CONFIGURATION.html) | [配置](CONFIGURATION_CN.html) |
| [Tool Development](TOOL_DEVELOPMENT.html) | [工具开发](TOOL_DEVELOPMENT_CN.html) |
| [Examples](EXAMPLES.html) | [示例](EXAMPLES_CN.html) |
| [Server Deployment](SERVER_DEPLOYMENT.html) | [服务部署](SERVER_DEPLOYMENT_CN.html) |

## What Is In This Repo

- `sagents/`: core runtime, agent orchestration, session context, tools, skills, sandbox, observability
- `examples/`: runnable local demos, including the CLI and standalone server examples
- `app/server/`: FastAPI backend and Vue 3 web client
- `app/desktop/`: desktop backend, Vue UI, and Tauri shell
- `mcp_servers/`: built-in MCP server implementations

## Recommended Reading Order

1. [Quick Start](QUICK_START.md)
2. [Architecture](ARCHITECTURE.md)
3. [API Reference](API_REFERENCE.md)
4. [Configuration](CONFIGURATION.md)

## Current Entry Points

### CLI

Use the maintained CLI example in `examples/`:

```bash
python examples/sage_cli.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "${SAGE_DEFAULT_LLM_API_BASE_URL:-https://api.deepseek.com/v1}" \
  --default_llm_model_name "${SAGE_DEFAULT_LLM_MODEL_NAME:-deepseek-chat}"
```

### Web Application

Backend:

```bash
python -m app.server.main
```

Frontend:

```bash
cd app/server/web
npm install
npm run dev
```

### Desktop Source Build

```bash
app/desktop/scripts/build.sh release
```

## Key Runtime Concepts

- `SAgent` in `sagents/sagents.py` is the current runtime entry for streaming execution.
- `ToolManager` auto-discovers built-in tools and MCP-backed tools.
- `SkillManager` loads host-side skills and makes them available to sessions.
- `SessionContext` merges runtime `system_context`, workspace permissions, memory, and session metadata.
- `agent_mode` currently supports `simple`, `multi`, and `fibre`.

## Notes

{: .note }
> Older docs and examples may still mention `AgentController`, `agents.*`, or `app/fastapi_react_demo`. Those paths are from older repository layouts and are not the current primary entry points.
