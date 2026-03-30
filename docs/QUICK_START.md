---
layout: default
title: Quick Start Guide
nav_order: 2
description: "Run the current Sage codebase locally"
---

# Quick Start Guide

This guide reflects the current repository layout and runnable entry points.

## Prerequisites

- Python 3.10+
- Node.js 18+ for the web frontend
- An OpenAI-compatible model endpoint

## Install

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
pip install -r requirements.txt
```

## Minimal Environment

The current server-side config reads `SAGE_*` variables. The most important defaults are:

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
```

## Option 1: Run The CLI

The maintained CLI entry is [`examples/sage_cli.py`](../examples/sage_cli.py).

```bash
python examples/sage_cli.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

Useful flags:

- `--agent_mode fibre|multi|simple`
- `--workspace ./agent_workspace`
- `--sandbox_type local|passthrough`
- `--skills_path <path>`
- `--tools_folders <dir1> <dir2>`

## Option 2: Run The Web App

Start the FastAPI backend:

```bash
python -m app.server.main
```

By default the backend listens on port `8080`.

Start the Vue frontend in another terminal:

```bash
cd app/server/web
npm install
npm run dev
```

## Option 3: Use `SAgent` Directly

`SAgent` in [`sagents/sagents.py`](../sagents/sagents.py) is the current runtime entry point.

```python
import asyncio
from openai import AsyncOpenAI

from sagents.sagents import SAgent
from sagents.tool import ToolManager
from sagents.skill import SkillManager


async def main():
    client = AsyncOpenAI(
        api_key="your-api-key",
        base_url="https://api.deepseek.com/v1",
    )

    agent = SAgent(session_root_space="./agent_sessions")
    tool_manager = ToolManager()
    skill_manager = SkillManager(skill_dirs=["app/skills"])

    async for chunks in agent.run_stream(
        input_messages=[{"role": "user", "content": "Summarize the repository structure."}],
        model=client,
        model_config={"model": "deepseek-chat"},
        system_prefix="You are Sage.",
        default_memory_type="session",
        sandbox_agent_workspace="./agent_workspace",
        tool_manager=tool_manager,
        skill_manager=skill_manager,
        agent_mode="multi",
        deep_thinking=True,
        system_context={"response_language": "en-US"},
    ):
        for chunk in chunks:
            if chunk.content:
                print(chunk.content, end="")


asyncio.run(main())
```

## Main Runtime Parameters

- `agent_mode`: `simple`, `multi`, or `fibre`
- `deep_thinking`: enables the analysis stage before execution
- `system_context`: shared runtime context injected into the session
- `sandbox_agent_workspace`: required for local and passthrough sandbox modes
- `custom_flow`: lets you replace the default flow with an `AgentFlow`

## Common Mistakes

- Do not use old examples that import `agents.agent.agent_controller`; the active package is `sagents`.
- Do not use `app/fastapi_react_demo`; the maintained web app lives in `app/server/` and `app/server/web/`.
- For local execution, provide a valid `sandbox_agent_workspace` or `run_stream()` will reject the call.
