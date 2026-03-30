---
layout: default
title: 快速开始指南
nav_order: 3
description: "基于当前代码库的 Sage 快速开始"
---

# 快速开始指南

本文档以当前仓库代码为准，覆盖可直接运行的入口。

## 前置要求

- Python 3.10+
- Node.js 18+（Web 前端需要）
- 一个兼容 OpenAI 的模型接口

## 安装

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
pip install -r requirements.txt
```

## 最小环境变量

当前服务端主要读取 `SAGE_*` 配置，最少建议设置：

```bash
export SAGE_DEFAULT_LLM_API_KEY="your-api-key"
export SAGE_DEFAULT_LLM_API_BASE_URL="https://api.deepseek.com/v1"
export SAGE_DEFAULT_LLM_MODEL_NAME="deepseek-chat"
```

## 方式一：运行 CLI

当前维护中的命令行入口是 [`examples/sage_cli.py`](../examples/sage_cli.py)。

```bash
python examples/sage_cli.py \
  --default_llm_api_key "$SAGE_DEFAULT_LLM_API_KEY" \
  --default_llm_api_base_url "$SAGE_DEFAULT_LLM_API_BASE_URL" \
  --default_llm_model_name "$SAGE_DEFAULT_LLM_MODEL_NAME"
```

常用参数：

- `--agent_mode fibre|multi|simple`
- `--workspace ./agent_workspace`
- `--sandbox_type local|passthrough`
- `--skills_path <path>`
- `--tools_folders <dir1> <dir2>`

## 方式二：运行 Web 应用

启动 FastAPI 后端：

```bash
python -m app.server.main
```

默认监听端口是 `8080`。

另开一个终端启动 Vue 前端：

```bash
cd app/server/web
npm install
npm run dev
```

## 方式三：直接使用 `SAgent`

当前运行时入口是 [`sagents/sagents.py`](../sagents/sagents.py) 中的 `SAgent`。

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
        input_messages=[{"role": "user", "content": "请总结一下仓库结构。"}],
        model=client,
        model_config={"model": "deepseek-chat"},
        system_prefix="You are Sage.",
        default_memory_type="session",
        sandbox_agent_workspace="./agent_workspace",
        tool_manager=tool_manager,
        skill_manager=skill_manager,
        agent_mode="multi",
        deep_thinking=True,
        system_context={"response_language": "zh-CN(简体中文)"},
    ):
        for chunk in chunks:
            if chunk.content:
                print(chunk.content, end="")


asyncio.run(main())
```

## 关键运行参数

- `agent_mode`：`simple`、`multi`、`fibre`
- `deep_thinking`：是否先执行分析阶段
- `system_context`：会话级共享上下文
- `sandbox_agent_workspace`：本地沙箱和直通模式必填
- `custom_flow`：可自定义 `AgentFlow` 执行流程

## 常见误区

- 不要再使用 `agents.agent.agent_controller` 这类旧路径，当前有效包名是 `sagents`。
- 不要再使用 `app/fastapi_react_demo`，当前维护中的 Web 应用在 `app/server/` 和 `app/server/web/`。
- 本地运行时如果没有提供合法的 `sandbox_agent_workspace`，`run_stream()` 会直接报错。
