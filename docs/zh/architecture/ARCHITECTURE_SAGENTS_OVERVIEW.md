---
layout: default
title: sagents 总览
parent: 架构
nav_order: 4
description: "sagents/ 核心运行时的分层、模块边界与一次 run_stream 的全链路"
lang: zh
ref: architecture-sagents-overview
---

{% include lang_switcher.html %}

# sagents 总览

`sagents/` 是 Sage 的核心运行时。所有应用形态（服务端、桌面、CLI、示例）最终都通过它来真正“跑一次会话”。这一节用图把 sagents 的分层、模块、以及一次 `run_stream` 的端到端调用关系讲清楚。

## 设计原则

```mermaid
flowchart LR
    P1[关注点分离<br/>逻辑/状态/能力/基础设施 分层]
    P2[状态中心化<br/>SessionContext 黑板模式]
    P3[可观测性优先<br/>事件钩子内建]
    P4[协议驱动扩展<br/>MCP / OpenAI 兼容]
    P5[沙箱抽象<br/>local/remote/passthrough 统一接口]
```



## 分层与模块

```mermaid
flowchart TB
    subgraph 入口层
        SAgent[SAgent · 运行时门面]
        SessRT[Session / SessionManager]
    end

    subgraph G_Flow ["编排层 flow/"]
        Flow[AgentFlow + FlowExecutor + Conditions]
    end

    subgraph G_Agent ["智能体层 agent/"]
        Agents[各类 *Agent]
        Fibre[fibre · 子智能体编排]
        Agents -.fibre 模式.-> Fibre
    end

    subgraph G_Ctx ["状态层 context/"]
        Ctx[SessionContext]
        Msg[MessageManager + ContextBudget]
        Mem[session_memory + user_memory]
        Wf[workflows]
    end

    subgraph 能力层
        LLM[llm · SageOpenAI / capabilities]
        Tools[tool · ToolManager + MCP]
        Skills[skill · SkillManager]
        Retr[retrieve_engine · RAG]
    end

    subgraph 基础设施
        Sandbox[utils/sandbox · 三种沙箱]
        Obs[observability · OpenTelemetry]
        Util[utils · logger/lock/prompt/...]
    end

    SAgent --> SessRT --> Flow --> Agents
    Agents --> Ctx
    Ctx --> Msg
    Ctx --> Mem
    Ctx --> Wf
    Agents --> LLM
    Agents --> Tools
    Agents --> Skills
    Agents --> Retr
    SessRT --> Sandbox
    SessRT --> Obs
```



## 一次 `SAgent.run_stream` 的全链路

```mermaid
sequenceDiagram
    participant Caller as 调用方<br/>(server/desktop/cli)
    participant SAgent as SAgent.run_stream
    participant SM as SessionManager
    participant Sess as Session
    participant Flow as FlowExecutor
    participant Agent as 某个 Agent
    participant LLM as SageAsyncOpenAI
    participant Tool as ToolManager
    participant Sandbox as Sandbox
    participant Obs as Observability

    Caller->>SAgent: run_stream(messages, model, ...)
    SAgent->>SAgent: 校验参数 / 推断 sandbox_type
    SAgent->>SM: get_or_create(session_id, sandbox_type)
    SM-->>SAgent: Session
    SAgent->>Sess: configure_runtime(model, sandbox, workspace, agent_id)
    SAgent->>Obs: on_chain_start
    SAgent->>SAgent: _build_default_flow(agent_mode) 或 custom_flow
    SAgent->>Sess: run_stream_safe(messages, flow, tools, skills, ...)
    Sess->>Flow: 执行 AgentFlow.root
    loop 每个节点
        Flow->>Agent: 实例化 + run_stream
        Agent->>LLM: chat_completion(messages, tools)
        LLM-->>Agent: 流式 chunks（含 tool_calls）
        opt 有工具调用
            Agent->>Tool: run_tool(name, args)
            Tool->>Sandbox: 命令/代码/文件操作
            Sandbox-->>Tool: 结果
            Tool-->>Agent: tool_message
        end
        Agent-->>Flow: yield MessageChunk(s)
    end
    Sess-->>SAgent: 异步生成器持续产出
    SAgent-->>Caller: yield [MessageChunk]
    SAgent->>Obs: 记录首屏耗时 / 消息时序
    SAgent->>SM: close_session
```



## 入口 API：`SAgent.run_stream` 的关键参数

```mermaid
flowchart TB
    Caller[调用方] --> Args{run_stream 入参}

    Args --> M[模型层<br/>model + model_config + system_prefix]
    Args --> SBX[沙箱<br/>sandbox_type + sandbox_agent_workspace<br/>+ volume_mounts + sandbox_id]
    Args --> CAP[能力<br/>tool_manager + skill_manager]
    Args --> ID[身份<br/>session_id + user_id + agent_id]
    Args --> MODE[模式<br/>agent_mode: simple/multi/fibre<br/>+ max_loop_count]
    Args --> EXT[扩展点<br/>custom_flow + custom_sub_agents<br/>+ available_workflows + system_context<br/>+ context_budget_config]
```



关键约束：

- `model` 与 `model_config` 必须给。
- `max_loop_count` 必须给，作为最终熔断。
- `sandbox_type` 优先级：参数 > `__init__` > `SAGE_SANDBOX_MODE` 环境变量 > 默认 `local`。
- 不同沙箱模式对 `sandbox_agent_workspace` 的要求不同（local/passthrough 必填，remote 可由默认 `/sage-workspace` 兜底）。

## 默认流程：显式 `agent_mode`

```mermaid
flowchart TB
    Start([输入 messages]) --> DT{is_deep_thinking?}
    DT -->|是| Analysis[task_analysis] --> Sw
    DT -->|否| Sw
    Sw{agent_mode}
    Sw -->|simple| Simple[simple body<br/>tool_suggestion ∥ memory_recall<br/>→ plan? → simple → summary?]
    Sw -->|multi| Multi[multi body<br/>memory_recall<br/>→ Loop 规划/执行/观察/判定<br/>→ task_summary]
    Sw -->|fibre| Fibre[fibre body<br/>Loop self_check_should_retry<br/>→ fibre 核心 → self_check]
    Simple --> More
    Multi --> More
    Fibre --> More
    More{enable_more_suggest?}
    More -->|是| Sug[query_suggest] --> End([输出])
    More -->|否| End
```



`agent_mode` 由调用方或 UI 显式选择，默认流程里不再有运行期自动路由步骤。逐节点细节见下一篇 [Agent 与 Flow 编排](ARCHITECTURE_SAGENTS_AGENT_FLOW.md)。

## 模块之间是怎么协作的

```mermaid
flowchart LR
    Sess[Session] -->|持有| Ctx[SessionContext]
    Flow[FlowExecutor] -->|按节点找 Agent| Agent
    Agent -->|读写状态| Ctx
    Agent -->|调用| LLM
    Agent -->|调用| ToolMgr
    ToolMgr -->|本地| Local[内置工具]
    ToolMgr -->|外部| MCP
    Local --> Sandbox
    SkillMgr -->|投影到沙箱| SandboxSkill[SandboxSkillManager]
    SandboxSkill --> Sandbox
    Obs[ObservabilityManager] -.事件.-> Sess
    Obs -.事件.-> Agent
    Obs -.事件.-> ToolMgr
    Obs -.事件.-> LLM
```



要点：

- **Agent 不持有状态**，状态全部走 `SessionContext`，方便复用与并发。
- **工具的执行最终落到 Sandbox**，工具层不直接接触本机环境。
- **可观测性是横向能力**，所有关键事件都通过 `ObservabilityManager` 分发。

## 接下来读什么

```mermaid
flowchart LR
    Here[sagents 总览] --> A[Agent + Flow] --> B[Session + Context] --> C[Tool + Skill] --> D[Sandbox + LLM + Obs]
```



- [Agent 与 Flow](ARCHITECTURE_SAGENTS_AGENT_FLOW.md)：智能体如何被定义和编排
- [Session 与 Context](ARCHITECTURE_SAGENTS_SESSION_CONTEXT.md)：状态层的细节
- [Tool 与 Skill](ARCHITECTURE_SAGENTS_TOOL_SKILL.md)：能力层
- [Sandbox / LLM / Obs](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)：基础设施层

## 二次开发：最小调用样板

把 `SAgent.run_stream` 当 SDK 用的最简形式，方便对照参数：

```python
import asyncio
from openai import AsyncOpenAI
from sagents.sagents import SAgent

async def main():
    agent = SAgent(session_root_space="/tmp/sage", sandbox_type="local")
    model = AsyncOpenAI(api_key="...", base_url="...")
    async for chunks in agent.run_stream(
        input_messages=[{"role": "user", "content": "你好"}],
        model=model,
        model_config={"model": "gpt-4o-mini"},
        system_prefix="你是一个助手",
        sandbox_agent_workspace="/tmp/sage/agents/demo",
        max_loop_count=8,
        agent_mode="simple",
    ):
        for c in chunks:
            print(c.role, c.content)

asyncio.run(main())
```

更复杂的扩展点（自定义 Flow、自定义子智能体、自定义条件）见下一篇。
