---

## layout: default
title: sagents Overview
parent: Architecture
nav_order: 4
description: "Layering, module boundaries and the full path of one run_stream call inside sagents/"
lang: en
ref: architecture-sagents-overview

{% include lang_switcher.html %}

# sagents Overview

`sagents/` is the core runtime of Sage. Every app shape (server, desktop, CLI, examples) ultimately runs a conversation through it. This page uses diagrams to lay out its layering, modules and the end-to-end path of one `run_stream` call.

## Design Principles

```mermaid
flowchart LR
    P1[Separation of concerns<br/>logic / state / capabilities / infra]
    P2[Centralized state<br/>SessionContext blackboard]
    P3[Observability first<br/>built-in event hooks]
    P4[Protocol-driven<br/>MCP / OpenAI compatible]
    P5[Sandbox abstraction<br/>local/remote/passthrough behind one interface]
```



## Layering and Modules

```mermaid
flowchart TB
    subgraph Entry
        SAgent[SAgent · runtime façade]
        SessRT[Session / SessionManager]
    end

    subgraph G_Flow ["Orchestration (flow/)"]
        Flow[AgentFlow + FlowExecutor + Conditions]
    end

    subgraph G_Agent ["Agents (agent/)"]
        Agents[Specialized *Agents]
        Fibre[fibre · sub-agent orchestration]
        Agents -.fibre mode.-> Fibre
    end

    subgraph G_Ctx ["State (context/)"]
        Ctx[SessionContext]
        Msg[MessageManager + ContextBudget]
        Mem[session_memory + user_memory]
        Wf[workflows]
    end

    subgraph Capabilities
        LLM[llm · SageOpenAI / capabilities]
        Tools[tool · ToolManager + MCP]
        Skills[skill · SkillManager]
        Retr[retrieve_engine · RAG]
    end

    subgraph Infra
        Sandbox[utils/sandbox · 3 sandbox kinds]
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



## End-to-End: One `SAgent.run_stream`

```mermaid
sequenceDiagram
    participant Caller as Caller<br/>(server/desktop/cli)
    participant SAgent as SAgent.run_stream
    participant SM as SessionManager
    participant Sess as Session
    participant Flow as FlowExecutor
    participant Agent as Some Agent
    participant LLM as SageAsyncOpenAI
    participant Tool as ToolManager
    participant Sandbox as Sandbox
    participant Obs as Observability

    Caller->>SAgent: run_stream(messages, model, ...)
    SAgent->>SAgent: validate args / resolve sandbox_type
    SAgent->>SM: get_or_create(session_id, sandbox_type)
    SM-->>SAgent: Session
    SAgent->>Sess: configure_runtime(model, sandbox, workspace, agent_id)
    SAgent->>Obs: on_chain_start
    SAgent->>SAgent: _build_default_flow(agent_mode) or custom_flow
    SAgent->>Sess: run_stream_safe(messages, flow, tools, skills, ...)
    Sess->>Flow: execute AgentFlow.root
    loop each node
        Flow->>Agent: instantiate + run_stream
        Agent->>LLM: chat_completion(messages, tools)
        LLM-->>Agent: streaming chunks (incl. tool_calls)
        opt tool calls present
            Agent->>Tool: run_tool(name, args)
            Tool->>Sandbox: command/code/file ops
            Sandbox-->>Tool: result
            Tool-->>Agent: tool_message
        end
        Agent-->>Flow: yield MessageChunk(s)
    end
    Sess-->>SAgent: async generator keeps yielding
    SAgent-->>Caller: yield [MessageChunk]
    SAgent->>Obs: record TTFB / message timings
    SAgent->>SM: close_session
```



## Key Parameters of `SAgent.run_stream`

```mermaid
flowchart TB
    Caller[Caller] --> Args{run_stream args}

    Args --> M[Model layer<br/>model + model_config + system_prefix]
    Args --> SBX[Sandbox<br/>sandbox_type + sandbox_agent_workspace<br/>+ volume_mounts + sandbox_id]
    Args --> CAP[Capabilities<br/>tool_manager + skill_manager]
    Args --> ID[Identity<br/>session_id + user_id + agent_id]
    Args --> MODE[Mode<br/>agent_mode: simple/multi/fibre<br/>+ max_loop_count]
    Args --> EXT[Extension points<br/>custom_flow + custom_sub_agents<br/>+ available_workflows + system_context<br/>+ context_budget_config]
```



Constraints:

- `model` and `model_config` are required.
- `max_loop_count` is required as the final circuit breaker.
- `sandbox_type` precedence: argument > `__init__` > `SAGE_SANDBOX_MODE` env > default `local`.
- Sandbox modes have different `sandbox_agent_workspace` requirements (local/passthrough required; remote falls back to `/sage-workspace`).

## Default Flow: the Three `agent_mode`s

```mermaid
flowchart TB
    Start([input messages]) --> Router[task_router]
    Router --> DT{is_deep_thinking?}
    DT -->|yes| Analysis[task_analysis] --> Sw
    DT -->|no| Sw
    Sw{agent_mode}
    Sw -->|simple| Simple[simple body<br/>tool_suggestion ∥ memory_recall<br/>→ plan? → simple → summary?]
    Sw -->|multi| Multi[multi body<br/>memory_recall<br/>→ Loop plan/exec/observe/judge<br/>→ task_summary]
    Sw -->|fibre| Fibre[fibre body<br/>Loop self_check_should_retry<br/>→ fibre core → self_check]
    Simple --> More
    Multi --> More
    Fibre --> More
    More{enable_more_suggest?}
    More -->|yes| Sug[query_suggest] --> End([output])
    More -->|no| End
```



`task_router` may rewrite `audit_status.agent_mode` at runtime, so even if `simple` is passed initially, the router may switch to `multi` or `fibre`. See [Agent & Flow Orchestration](ARCHITECTURE_SAGENTS_AGENT_FLOW.md) for node-by-node detail.

## How the Modules Cooperate

```mermaid
flowchart LR
    Sess[Session] -->|owns| Ctx[SessionContext]
    Flow[FlowExecutor] -->|resolve agent per node| Agent
    Agent -->|read/write| Ctx
    Agent -->|call| LLM
    Agent -->|call| ToolMgr
    ToolMgr -->|local| Local[built-in tools]
    ToolMgr -->|external| MCP
    Local --> Sandbox
    SkillMgr -->|project to sandbox| SandboxSkill[SandboxSkillManager]
    SandboxSkill --> Sandbox
    Obs[ObservabilityManager] -.events.-> Sess
    Obs -.events.-> Agent
    Obs -.events.-> ToolMgr
    Obs -.events.-> LLM
```



Key points:

- **Agents own no state**; everything goes through `SessionContext`, enabling reuse and concurrency.
- **Tool execution lands on the Sandbox**; the tool layer never touches the host directly.
- **Observability is cross-cutting**; every key event flows through `ObservabilityManager`.

## What to Read Next

```mermaid
flowchart LR
    Here[sagents Overview] --> A[Agent + Flow] --> B[Session + Context] --> C[Tool + Skill] --> D[Sandbox + LLM + Obs]
```



- [Agent & Flow](ARCHITECTURE_SAGENTS_AGENT_FLOW.md)
- [Session & Context](ARCHITECTURE_SAGENTS_SESSION_CONTEXT.md)
- [Tool & Skill](ARCHITECTURE_SAGENTS_TOOL_SKILL.md)
- [Sandbox / LLM / Obs](ARCHITECTURE_SAGENTS_SANDBOX_OBS.md)

## Extending: Minimal Caller Template

The minimal way to use `SAgent.run_stream` as an SDK, useful for cross-checking parameters:

```python
import asyncio
from openai import AsyncOpenAI
from sagents.sagents import SAgent

async def main():
    agent = SAgent(session_root_space="/tmp/sage", sandbox_type="local")
    model = AsyncOpenAI(api_key="...", base_url="...")
    async for chunks in agent.run_stream(
        input_messages=[{"role": "user", "content": "Hello"}],
        model=model,
        model_config={"model": "gpt-4o-mini"},
        system_prefix="You are an assistant",
        sandbox_agent_workspace="/tmp/sage/agents/demo",
        max_loop_count=8,
        agent_mode="simple",
    ):
        for c in chunks:
            print(c.role, c.content)

asyncio.run(main())
```

For more advanced extension points (custom flow, sub-agents, conditions), see the next page.