---
layout: default
title: 架构指南
nav_order: 5
description: "当前 Sage 架构总览"
---

# 架构指南

本文档只描述当前仓库里能直接对应到代码的架构。

## 1. 顶层目录结构

当前代码主要分布在这些区域：

- `sagents/`：核心运行时、流程执行、会话状态、工具、技能、沙箱、可观测性
- `app/server/`：FastAPI 后端和 Vue Web 应用
- `app/desktop/`：桌面端后端、Vue UI、Tauri 壳
- `examples/`：独立 CLI、Streamlit demo、示例服务
- `mcp_servers/`：内置 MCP Server 实现

## 2. 核心运行时模型

当前运行时入口是 [`sagents/sagents.py`](../sagents/sagents.py) 中的 `SAgent`。

`SAgent` 本身保持很薄，主要职责是：

- 校验运行参数
- 解析或生成 session_id
- 配置 `Session`
- 构建或接收一个 `AgentFlow`
- 把可见的 `MessageChunk` 流式返回给调用方

真正的运行时状态不保存在 `SAgent` 里，而在 `SessionContext` 中。

## 3. 主要架构分层

可以把当前 Sage 看成四层：

1. 入口层
2. 会话 / 状态层
3. 执行 / 流程层
4. 能力层

### 入口层

- `examples/sage_cli.py`
- `examples/sage_server.py`
- `app/server/main.py`
- `app/desktop/core/main.py`

这些只是不同外壳，底层都围绕 `sagents` 运行时。

### 会话 / 状态层

关键文件：

- [`sagents/session_runtime.py`](../sagents/session_runtime.py)
- [`sagents/context/session_context.py`](../sagents/context/session_context.py)
- [`sagents/context/messages/`](../sagents/context/messages)
- [`sagents/context/user_memory/`](../sagents/context/user_memory)

职责：

- 创建或恢复会话
- 合并落盘的 `system_context` 和本次传入的上下文
- 管理工作区与文件权限
- 保存消息历史、任务状态、用户记忆、工作流数据和运行元信息

### 执行 / 流程层

流程系统主要由这些模块组成：

- [`sagents/flow/schema.py`](../sagents/flow/schema.py)
- [`sagents/flow/executor.py`](../sagents/flow/executor.py)
- [`sagents/agent/`](../sagents/agent)

当没有传入 `custom_flow` 时，`SAgent` 会构造默认的 `AgentFlow`。

### 能力层

核心能力管理器包括：

- [`sagents/tool/tool_manager.py`](../sagents/tool/tool_manager.py)
- [`sagents/skill/skill_manager.py`](../sagents/skill/skill_manager.py)
- [`sagents/utils/sandbox/`](../sagents/utils/sandbox)
- [`sagents/observability/`](../sagents/observability)

## 4. 默认执行流程

默认 flow 在 [`sagents/sagents.py`](../sagents/sagents.py) 中组装。

高层顺序是：

1. `task_router`
2. 如果启用了 `deep_thinking`，进入 `task_analysis`
3. 根据 `agent_mode` 切换执行分支
4. 可选地生成后续建议

### `agent_mode = simple`

默认路径：

- 并行执行 `tool_suggestion` 和 `memory_recall`
- `simple`
- 按需执行 `task_summary`

### `agent_mode = multi`

默认路径：

- `memory_recall`
- 循环执行 `task_planning` -> `tool_suggestion` -> `task_executor` -> `task_observation` -> `task_completion_judge`
- `task_summary`

### `agent_mode = fibre`

默认路径：

- 并行执行 `tool_suggestion` 和 `memory_recall`
- `fibre`

这是当前仓库里的并行 / 委派编排路径。

## 5. 会话生命周期

会话生命周期由 [`sagents/session_runtime.py`](../sagents/session_runtime.py) 中的 `Session` 和 `SessionManager` 负责。

高层流程：

1. 将运行时配置绑定到 session
2. 如有必要，从磁盘加载已保存的 `system_context`
3. 创建并初始化 `SessionContext`
4. 使用该上下文执行 flow
5. 把可见 chunk 向外流式输出
6. 支持查询、保存、中断和清理 session

## 6. Tool、Skill 与 MCP

### Tool

`ToolManager` 负责：

- 发现普通 Python Tool
- 发现内置 MCP 风格 Tool
- 初始化外部 MCP Tool

### Skill

`SkillManager` 从宿主机目录加载 `SKILL.md` 技能包，并把技能元数据和说明暴露给运行时。

### MCP

仓库内置的 MCP Server 实现在 [`mcp_servers/`](../mcp_servers)。

## 7. 沙箱与工作区

沙箱实现位于 [`sagents/utils/sandbox/`](../sagents/utils/sandbox)。

当前支持的主要模式：

- `local`
- `remote`
- `passthrough`

其中 `local` 和 `passthrough` 模式下，`SAgent.run_stream()` 要求必须传 `sandbox_agent_workspace`。

## 8. 服务端与桌面端架构

### 服务端

[`app/server/main.py`](../app/server/main.py) 创建 FastAPI 应用，并注册 [`app/server/routers/`](../app/server/routers) 下的路由。

主要能力面包括：

- chat / stream
- agent 管理
- tools / skills / MCP 管理
- knowledge base
- auth 与 OAuth2
- observability 代理

### 桌面端

[`app/desktop/core/main.py`](../app/desktop/core/main.py) 负责桌面本地后端。UI 位于 [`app/desktop/ui`](../app/desktop/ui)，Tauri 打包层位于 [`app/desktop/tauri`](../app/desktop/tauri)。

## 9. 架构要点

- `SAgent` 是编排入口，不是长期状态容器
- `SessionContext` 是主要状态边界
- `AgentFlow` 是运行时控制图
- `ToolManager`、`SkillManager`、沙箱、可观测性是围绕该控制图工作的能力层

## 10. 兼容性说明

旧资料里可能会出现 `AgentController`、`agents.*` 或旧版多智能体流水线命名。当前架构应以 `sagents/`、`app/server/`、`app/desktop/` 和 `examples/` 为准。
