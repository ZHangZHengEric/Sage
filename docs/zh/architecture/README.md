---
layout: default
title: 架构
nav_order: 4
has_children: true
description: "Sage 仓库与子系统架构总览，含应用与 sagents 核心运行时的二级文档"
lang: zh
ref: architecture
---

{% include lang_switcher.html %}

# 架构

Sage 不是一个单一二进制，而是一个分层的代码库。架构这一章被拆成两条主线：

- **应用架构**：每一个面向使用者的入口（Web 服务端、桌面端、CLI、示例与浏览器扩展等）各自的形态、启动路径与边界。
- **核心运行时 `sagents/` 架构**：所有应用都共享的会话与智能体引擎，是真正承载“跑一次对话/一次任务”的中枢。

这一章下面有多篇二级文档，分别拆开讲。本页只提供大图与索引，细节请进入对应子页。

## 仓库分层全景

```mermaid
flowchart TB
    subgraph G_App ["应用层 app/"]
        Server[server<br/>主 FastAPI + Vue 3 Web]
        Desktop[desktop<br/>桌面入口 + 本地后端 + UI]
        CLI[cli<br/>sage 命令]
        Ext[chrome-extension<br/>侧边栏插件]
        Skills[skills<br/>内置技能包]
        Wiki[wiki<br/>静态站点]
    end

    subgraph G_Ex ["入口示例 examples/"]
        DemoCLI[sage_cli.py]
        DemoUI[sage_demo.py · Streamlit]
        DemoSrv[sage_server.py · FastAPI]
    end

    subgraph G_Sagents ["核心运行时 sagents/"]
        Runtime[Session · Agent · Flow · Tool · Skill · Sandbox · Obs]
    end

    subgraph 外部能力
        MCP[mcp_servers · 内置 MCP]
        Common[common · 共享基础设施]
        Docs[docs · 当前文档]
    end

    Server --> Runtime
    Desktop --> Runtime
    CLI --> Runtime
    DemoCLI --> Runtime
    DemoUI --> Runtime
    DemoSrv --> Runtime
    Ext -->|HTTP| Server
    Runtime --> MCP
    Runtime -.基础.-> Common
```



## 一次会话的高层数据流

```mermaid
flowchart LR
    UserIn((用户输入)) --> EntryApp[某个应用入口]
    EntryApp -->|run_stream 调用| SAgent[SAgent 入口]
    SAgent --> Sess[Session/SessionContext]
    Sess --> Flow[FlowExecutor + AgentFlow]
    Flow --> Agents[各类 Agent]
    Agents --> LLM[模型层]
    Agents --> Tools[工具/技能]
    Tools --> Sandbox[沙箱]
    Sess --> Obs[可观测性]
    Agents -->|流式 MessageChunk| EntryApp
    EntryApp -->|SSE/JSON| UserIn
```



## 这一章包含哪些二级文档

应用架构（不同 app 的形态与边界）：

1. [服务端与 Web 应用架构](ARCHITECTURE_APP_SERVER.md)：`app/server/` 的 FastAPI、路由、服务、启动与 Web 客户端结构
2. [桌面应用架构](ARCHITECTURE_APP_DESKTOP.md)：`app/desktop/` 的本地后端、UI、Tauri 壳与与 sagents 的关系
3. [CLI、示例与外部入口架构](ARCHITECTURE_APP_OTHERS.md)：`app/cli/`、`examples/`、`app/chrome-extension/`、`app/wiki/` 等轻量入口

核心运行时 `sagents/` 架构（这一章的核心）：

1. [sagents 总览](ARCHITECTURE_SAGENTS_OVERVIEW.md)：分层、模块边界与典型一次 `run_stream` 的全链路
2. [智能体（Agent）与流程（Flow）编排](ARCHITECTURE_SAGENTS_AGENT_FLOW.md)：`AgentBase`、各专用 Agent、`AgentFlow` / `FlowExecutor`、三种 `agent_mode`
3. [会话与上下文（Session & Context）](ARCHITECTURE_SAGENTS_SESSION_CONTEXT.md)：`Session`、`SessionContext`、消息管理、会话/用户记忆与 workflow
4. [工具与技能（Tool & Skill）系统](ARCHITECTURE_SAGENTS_TOOL_SKILL.md)：`ToolManager` / `ToolProxy`、内置工具、MCP 代理、`SkillManager` / `SkillProxy`、沙箱内技能
5. [沙箱、LLM 适配与可观测性](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)：`SandboxProviderFactory` 三种沙箱、`SageAsyncOpenAI` 模型层与 OpenTelemetry 链路

## 阅读建议

```mermaid
flowchart TD
    Want[你想做什么]

    Want --> A[理解一次对话怎么被驱动]
    A --> A1[sagents 总览] --> A2[Agent + Flow] --> A3[Session + Context]

    Want --> B[做服务端集成或部署]
    B --> B1[服务端与 Web 应用架构] --> B2[配置 + HTTP API 参考]

    Want --> C[做扩展<br/>自定义工具/MCP/技能/子智能体]
    C --> C1[工具与技能系统] --> C2[Agent + Flow 的扩展点]

    Want --> D[做桌面打包]
    D --> D1[桌面应用架构] --> D2[app/desktop/scripts]
```

