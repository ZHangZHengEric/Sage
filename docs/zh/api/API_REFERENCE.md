---
layout: default
title: Python 运行时 API
parent: API 文档
nav_order: 2
description: "与 sagents 源码一致的运行时入口 SAgent、工具与流式消息说明（非主站 HTTP）"
lang: zh
ref: api-reference
---

{% include lang_switcher.html %}

{: .note }

> 需要英文版本？请查看 [API Reference](../en/API_REFERENCE.md)。

> 主站 **HTTP** 对接请使用 [HTTP API 参考](HTTP_API_REFERENCE.md)。本页描述在 Python 中嵌入 `sagents` 运行时的**公共面**，以仓库源码为准，见 [核心概念](CORE_CONCEPTS.md) 与 `sagents/sagents.py`。

## 目录
{: .no_toc .text-delta }

1. TOC
{:toc}

# Python 运行时 API

## 1. 入口类：`SAgent`

定义于 `sagents/sagents.py`，是当前流式多智能体运行时的**唯一推荐入口**（原 v0.9 文档中的 `AgentController` 等名称已不适用于本仓库主路径）。

```python
from sagents.sagents import SAgent

agent = SAgent(
    session_root_space="/path/to/session/storage",
    enable_obs=True,
    sandbox_type=None,  # 可选；默认可由环境变量 SAGE_SANDBOX_MODE 或 __init__ 提供
)
```

| 参数 | 类型 | 说明 |
|------|------|------|
| `session_root_space` | `str` | 会话存储根目录，必填 |
| `enable_obs` | `bool` | 是否启用可观测性（默认 `True`） |
| `sandbox_type` | `Optional[str]` | 沙箱模式：`"local"` \| `"remote"` \| `"passthrough"`；未传则读 `SAGE_SANDBOX_MODE`，再默认 `local` |

## 2. 核心方法：`run_stream`

**异步生成器**，按块产出 `MessageChunk` 列表（通常每次一个 chunk）。必须在 `async for` 中消费。

**必填 / 强约束：**

- `model`：OpenAI 兼容的异步客户端等，不可为空。
- `model_config`：非空 `dict`（如含 `model`、`api_key`、`base_url` 等，依你的客户端而定）。
- `max_loop_count`：不可为 `None`（会显式校验）。
- `system_prefix`：系统提示前缀字符串。

**沙箱与路径：**

- `sandbox_type`：单次调用可覆盖实例上的默认；最终优先级为 **本参数 &gt; `SAgent` 上保存的值 &gt; 环境变量 &gt; `local`**。
- `local` / `passthrough`：必须提供 `sandbox_agent_workspace`（沙箱/工作区内路径）。
- `remote`：若未提供 `sandbox_agent_workspace`，实现中会默认 `"/sage-workspace"`；`sandbox_id` 可选，用于复用已有远程沙箱。

**行为与能力：**

| 参数 | 说明 |
|------|------|
| `input_messages` | `List[dict]` 或 `List[MessageChunk]`；可带/不带 `session_id`，未带时会补全为新建或从首条消息推断 |
| `tool_manager` / `skill_manager` | `ToolManager` / `ToolProxy` 与 `SkillManager` / `SkillProxy` |
| `session_id` / `user_id` / `agent_id` | 会话与用户、智能体标识 |
| `agent_mode` | `"simple"` \| `"multi"` \| `"fibre"`，影响默认 `AgentFlow` 组装 |
| `custom_flow` | 若提供，则**不**再使用内置默认流 |
| `custom_sub_agents` | 子 Agent 配置列表 |
| `system_context` | 注入到运行时的系统上下文字典 |
| `available_workflows` | 可用工作流（未传时内部以 `{}` 使用） |
| `context_budget_config` | 上下文预算相关 |
| `volume_mounts` | `List[VolumeMount]`，见 `sagents.utils.sandbox.config` |
| `more_suggest` / `force_summary` | 更多建议、是否强制总结 |
| `deep_thinking` | 已弱化；更推荐在消息体中用 `&lt;enable_deep_thinking&gt;` 等约定控制 |

一次会话结束（含异常路径后的 `finally`）会关闭会话，详见 `SAgent.run_stream` 中 `close_session` 的调用。

**最小示例：**

```python
async for chunks in agent.run_stream(
    input_messages=[{"role": "user", "content": "你好"}],
    model=client,
    model_config={"model": "gpt-4o", "api_key": "...", "base_url": "https://..."},
    system_prefix="你是助手。",
    max_loop_count=10,
    sandbox_agent_workspace="/abs/path/to/agent/workspace",
    volume_mounts=[],
):
    for chunk in chunks:
        print(chunk.content)
```

## 3. 会话控制（`SAgent` 上的薄封装）

以下方法直接委托给 `session_manager`（`sagents/session_runtime.py` 的全局会话管理器）：

- `get_session_status(session_id)`
- `list_active_sessions()`
- `cleanup_session(session_id)` → 内部为 `close_session`
- `save_session(session_id)`
- `interrupt_session(session_id, message=...)`
- `get_tasks_status(session_id)`

### 运行中引导消息 helper

这些方法允许宿主代码在不中断会话的情况下，向 live session 追加用户引导。消息先进入 `SessionContext.pending_user_injections`；agent 在下一次请求 LLM 前 drain 队列，将其作为普通用户消息写入历史，并在流中带 `metadata.guidance_id` 回送。

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `inject_user_message(session_id, content, guidance_id=None, metadata=None)` | `str` | 排队一条引导消息，返回实际生效的 `guidance_id`。 |
| `list_pending_user_injections(session_id)` | `List[dict]` | 快照查询尚未消费的 pending 引导消息。 |
| `update_pending_user_injection(session_id, guidance_id, content)` | `bool` | 修改 pending 内容；`False` 表示不存在或已被消费。 |
| `delete_pending_user_injection(session_id, guidance_id)` | `bool` | 删除 pending 消息；`False` 表示不存在或已被消费。 |

示例：

```python
guidance_id = agent.inject_user_message(
    session_id="sess_123",
    content="请优先检查测试失败原因",
    guidance_id="ui-guidance-1",
    metadata={"source_ui": "guidance_area"},
)

pending = agent.list_pending_user_injections("sess_123")
agent.update_pending_user_injection(
    "sess_123",
    guidance_id,
    "请优先检查测试失败原因，并总结修复点",
)
agent.delete_pending_user_injection("sess_123", guidance_id)
```

`inject_user_message` 在目标会话不在线时抛 `LookupError`，在 `content` 为空时抛 `ValueError`。编辑/删除只作用于 pending 消息；一旦被消费，它就是正式持久化的用户消息。

## 4. 默认执行图与 `agent_mode`

未传 `custom_flow` 时，由 `_build_default_flow` 使用 `sagents/flow/schema.py` 中的 `SequenceNode`、`SwitchNode`、`LoopNode`、`IfNode` 等拼装（含深度思考分支、`agent_mode` 分岔、`query_suggest` 等）。概念说明见 [核心概念](CORE_CONCEPTS.md) 与 [Agent / Flow 架构](ARCHITECTURE_SAGENTS_AGENT_FLOW.md)。

## 5. 工具与技能

### 5.1 `ToolManager`

- 实现：`sagents/tool/tool_manager.py`。
- 默认可为**单例**；`isolated=True` 可得到独立实例。
- 自动发现：`discover_tools_from_path()` 扫描 `sagents/tool/impl`；`discover_builtin_mcp_tools_from_path()` 扫描 `mcp_servers` 包中注册的 MCP 工具。
- 常用方法：`register_tool`、`register_tools_from_object`、`list_tools` / `list_tools_simplified` / `get_openai_tools`、`run_tool_async` 等；MCP 侧含 `register_mcp_server`、异步 `remove_tool_by_mcp` 等。

### 5.2 `@tool` 装饰器

- 实现：`sagents/tool/tool_base.py`。
- 支持多语言描述、`param_schema` 等，详见源码 docstring。

### 5.3 `SkillManager`

- 实现：`sagents/skill/skill_manager.py`。
- 在**宿主机**上发现并加载 `SKILL.md` 等；沙箱内复制由 `SessionContext` 与沙箱实现配合完成。

## 6. 流式消息类型：`MessageChunk` / `MessageType`

- 定义：`sagents/context/messages/message.py`。
- `MessageChunk`：流式单块，含 `role`、`content`、`tool_calls`、`message_id`、`message_type` 等，与 OpenAI 风格消息对齐。
- `MessageType`：枚举了当前使用的 `user_input`、`assistant_text`、`task_analysis`、`tool_call` 等；历史字段 `type: "normal"` 会经兼容逻辑归一化。

## 7. 环境变量

| 变量 | 作用 |
|------|------|
| `SAGE_SANDBOX_MODE` | 默认沙箱模式：`local` / `remote` / `passthrough` |

## 8. 参考实现

- 独立流式服务示例：`examples/sage_server.py`（使用 `SAgent`）。
- 与本文档同级的 [HTTP API 参考](HTTP_API_REFERENCE.md) 仅描述 **App Server** 的 HTTP 面，不替代上述 Python API。
