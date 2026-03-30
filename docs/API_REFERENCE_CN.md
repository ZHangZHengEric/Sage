---
layout: default
title: API 参考
nav_order: 9
description: "基于当前代码库的 Sage API 参考"
---

{: .note }
> 英文版本请查看 [API Reference](API_REFERENCE.html)。

# Sage API 参考

本文档只描述当前仓库中仍然有效、且能从代码直接确认的接口面：以 `SAgent` 为核心的 Python 运行时，以及 `app/server/routers/` 下的 FastAPI 接口。

## Python 运行时

### `SAgent`

定义在 [`sagents/sagents.py`](../sagents/sagents.py)。

```python
from sagents.sagents import SAgent

agent = SAgent(
    session_root_space="./agent_sessions",
    enable_obs=True,
    sandbox_type="local",
)
```

#### 构造参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `session_root_space` | `str` | 全局会话管理器使用的根目录 |
| `enable_obs` | `bool` | 是否开启可观测性钩子 |
| `sandbox_type` | `str \| None` | 默认沙箱模式，通常为 `local`、`remote`、`passthrough` |

#### `run_stream()`

`SAgent.run_stream()` 是当前主要执行入口。

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

关键参数：

| 参数 | 说明 |
|---|---|
| `input_messages` | 输入消息列表，可传普通字典或 `MessageChunk` |
| `model` | 兼容 OpenAI 协议的异步客户端 |
| `model_config` | 模型运行配置，通常至少包含 `model` |
| `system_prefix` | 基础系统提示词 |
| `default_memory_type` | 会话默认记忆模式 |
| `sandbox_agent_workspace` | `local` 和 `passthrough` 模式下必填 |
| `tool_manager` | 工具注册与 MCP 工具访问入口 |
| `skill_manager` | 技能加载与分发入口 |
| `agent_mode` | `simple`、`multi`、`fibre` |
| `deep_thinking` | 是否先执行分析阶段 |
| `system_context` | 注入到会话中的共享上下文 |
| `custom_flow` | 用自定义 `AgentFlow` 替换默认流程 |

补充说明：

- 未显式传 `session_id` 时，运行时会自动生成。
- `local` 模式下如果没有提供 `sandbox_agent_workspace`，会直接抛出参数错误。
- 对外产出的流是 `MessageChunk` 列表，只有包含可见内容、工具调用或 token 使用信息的 chunk 才会被向外 yield。

### `ToolManager`

定义在 [`sagents/tool/tool_manager.py`](../sagents/tool/tool_manager.py)。

```python
from sagents.tool import ToolManager

tool_manager = ToolManager()
```

当前行为：

- 自动发现 `sagents/tool/` 下的 Python 工具
- 自动发现内置 MCP 工具
- 后续可异步初始化真正的 MCP Server 连接

### `SkillManager`

定义在 [`sagents/skill/skill_manager.py`](../sagents/skill/skill_manager.py)。

```python
from sagents.skill import SkillManager

skill_manager = SkillManager(skill_dirs=["app/skills"])
```

当前行为：

- 从宿主机目录加载基于 `SKILL.md` 的技能包
- 提供技能元数据和说明，供运行时注入

## FastAPI 服务

当前维护中的 HTTP 服务入口是 [`app/server/main.py`](../app/server/main.py)。

### 健康检查

#### `GET /active`

最简单的存活探针接口。

### 聊天接口

定义在 [`app/server/routers/chat.py`](../app/server/routers/chat.py)。

#### `POST /api/chat`

基于 `agent_id` 启动流式聊天。

请求体示例：

```json
{
  "messages": [
    { "role": "user", "content": "请总结这个仓库。" }
  ],
  "agent_id": "my-agent",
  "session_id": "optional-session-id",
  "user_id": "optional-user-id",
  "system_context": {}
}
```

#### `POST /api/stream`

通用流式接口，请求模型里不强制要求 `agent_id`。

根据 [`app/server/schemas/chat.py`](../app/server/schemas/chat.py)，常用字段包括：

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

Web UI 使用的鉴权流式接口。

#### `GET /api/stream/resume/{session_id}`

恢复已有会话的流订阅。

#### `GET /api/stream/active_sessions`

返回当前活跃流式会话的 SSE 接口。

## Agent 配置模型

服务端在 [`app/server/routers/agent.py`](../app/server/routers/agent.py) 中定义了 Agent 配置 DTO。

常用字段：

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

## 启动配置

服务启动配置定义在 [`app/server/core/config.py`](../app/server/core/config.py)。

最常用环境变量：

- `SAGE_PORT`
- `SAGE_DEFAULT_LLM_API_KEY`
- `SAGE_DEFAULT_LLM_API_BASE_URL`
- `SAGE_DEFAULT_LLM_MODEL_NAME`
- `SAGE_SESSION_DIR`
- `SAGE_LOGS_DIR_PATH`
- `SAGE_AGENTS_DIR`
- `SAGE_SKILL_WORKSPACE`
- `SAGE_DB_TYPE`

## 兼容性说明

旧文档里仍可能出现 `AgentController`、`agents.*`、`deep_research` 等名词。它们属于旧版本目录结构或兼容字段，不是当前仓库的主入口。
