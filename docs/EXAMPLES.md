---
layout: default
title: Examples & Use Cases
nav_order: 10
description: "Current examples based on the active Sage runtime"
---

{: .note }
> Looking for Chinese? See [示例和用例](EXAMPLES_CN.html).

# Examples and Use Cases

These examples are aligned with the current repository layout: `sagents/`, `examples/`, `app/server/`, and `app/desktop/`.

## 1. CLI Example

The main interactive example is [`examples/sage_cli.py`](../examples/sage_cli.py).

```bash
python examples/sage_cli.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME" \
  --agent_mode fibre
```

Use this when you want:

- an interactive terminal session
- tool and skill loading
- local or passthrough sandbox execution

## 2. Streamlit Demo

The repository still includes a standalone demo in [`examples/sage_demo.py`](../examples/sage_demo.py).

```bash
streamlit run examples/sage_demo.py -- \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

Use this when you want a lightweight local demo UI without running the full server/web stack.

## 3. Standalone HTTP Service Example

[`examples/sage_server.py`](../examples/sage_server.py) starts a self-contained streaming HTTP service for local experiments.

```bash
python examples/sage_server.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

## 4. Direct `SAgent` Example

For code-level integration, use `SAgent` directly.

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
        input_messages=[{"role": "user", "content": "Summarize the current project structure."}],
        model=client,
        model_config={"model": "deepseek-chat"},
        system_prefix="You are Sage.",
        default_memory_type="session",
        sandbox_agent_workspace="./agent_workspace",
        tool_manager=tool_manager,
        skill_manager=skill_manager,
        agent_mode="multi",
        deep_thinking=True,
    ):
        for chunk in chunks:
            if chunk.content:
                print(chunk.content, end="")


asyncio.run(main())
```

## 5. Custom Tool Example

The current tool decorator lives in [`sagents/tool/tool_base.py`](../sagents/tool/tool_base.py).

```python
from sagents.tool.tool_base import tool


class CalculatorTool:
    @tool()
    def add(self, a: int, b: int) -> dict:
        """
        Add two integers.

        Args:
            a: First integer
            b: Second integer
        """
        return {"result": a + b}
```

## 6. Built-in MCP Tool Example

For built-in MCP-style tools, use `@sage_mcp_tool` from [`sagents/tool/mcp_tool_base.py`](../sagents/tool/mcp_tool_base.py).

```python
from sagents.tool.mcp_tool_base import sage_mcp_tool


@sage_mcp_tool(server_name="demo")
def get_status(name: str) -> dict:
    """
    Get demo status.

    Args:
        name: Target name
    """
    return {"name": name, "status": "ok"}
```

## 7. Web App Example

The maintained web stack is:

- backend: [`app/server/main.py`](../app/server/main.py)
- frontend: [`app/server/web`](../app/server/web)

```bash
python -m app.server.main

cd app/server/web
npm install
npm run dev
```

## Notes

- Prefer `examples/sage_cli.py` and `SAgent` for current code examples.
- Older examples that use `AgentController`, `agents.*`, or `deep_research` are from older layouts and should not be used as integration references.
