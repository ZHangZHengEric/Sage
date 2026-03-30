---
layout: default
title: 示例和用例
nav_order: 11
description: "基于当前 Sage 运行时的示例"
---

{: .note }
> 英文版本请查看 [Examples & Use Cases](EXAMPLES.html)。

# 示例和用例

本文档只保留与当前仓库结构一致的示例：`sagents/`、`examples/`、`app/server/`、`app/desktop/`。

## 1. CLI 示例

当前主要交互式示例是 [`examples/sage_cli.py`](../examples/sage_cli.py)。

```bash
python examples/sage_cli.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME" \
  --agent_mode fibre
```

适用场景：

- 终端交互式会话
- 加载工具和技能
- 本地沙箱或直通模式运行

## 2. Streamlit 示例

仓库中仍保留轻量本地演示 [`examples/sage_demo.py`](../examples/sage_demo.py)。

```bash
streamlit run examples/sage_demo.py -- \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

适合快速体验，不需要启动完整服务端和 Web 前端。

## 3. 独立 HTTP 服务示例

[`examples/sage_server.py`](../examples/sage_server.py) 可用于本地实验性的流式 HTTP 服务。

```bash
python examples/sage_server.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

## 4. 直接使用 `SAgent`

代码集成时，建议直接使用 `SAgent`。

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
        input_messages=[{"role": "user", "content": "请总结当前项目结构。"}],
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

## 5. 自定义 Tool 示例

当前 Tool 装饰器定义在 [`sagents/tool/tool_base.py`](../sagents/tool/tool_base.py)。

```python
from sagents.tool.tool_base import tool


class CalculatorTool:
    @tool()
    def add(self, a: int, b: int) -> dict:
        """
        两个整数求和。

        Args:
            a: 第一个整数
            b: 第二个整数
        """
        return {"result": a + b}
```

## 6. 内置 MCP Tool 示例

如果要定义内置 MCP 风格工具，使用 [`sagents/tool/mcp_tool_base.py`](../sagents/tool/mcp_tool_base.py) 里的 `@sage_mcp_tool`。

```python
from sagents.tool.mcp_tool_base import sage_mcp_tool


@sage_mcp_tool(server_name="demo")
def get_status(name: str) -> dict:
    """
    获取 demo 状态。

    Args:
        name: 目标名称
    """
    return {"name": name, "status": "ok"}
```

## 7. Web 应用示例

当前维护中的 Web 方案是：

- 后端：[`app/server/main.py`](../app/server/main.py)
- 前端：[`app/server/web`](../app/server/web)

```bash
python -m app.server.main

cd app/server/web
npm install
npm run dev
```

## 说明

- 当前代码示例优先参考 `examples/sage_cli.py` 和 `SAgent`。
- 凡是还在使用 `AgentController`、`agents.*`、`deep_research` 的旧示例，都不应再作为当前集成方式参考。
