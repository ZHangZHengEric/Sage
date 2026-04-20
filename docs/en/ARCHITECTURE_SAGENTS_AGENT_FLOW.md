---

## layout: default
title: Agent & Flow Orchestration
parent: Architecture
nav_order: 5
description: "AgentBase, the specialized agents, AgentFlow / FlowExecutor and the three agent_modes"
lang: en
ref: architecture-sagents-agent-flow

{% include lang_switcher.html %}

# Agent & Flow Orchestration

This page covers `sagents/agent/` and `sagents/flow/`. **An agent is the unit of work; a flow defines the relationships between agents.** They are decoupled: changing the flow does not change the agents, and vice versa.

## 1. The Agent Layer

### 1.1 What `AgentBase` Provides

```mermaid
flowchart LR
    Base[AgentBase] --> RunStream[run_stream<br/>uniform async stream interface]
    Base --> Model[holds model + model_config]
    Base --> SafeCall[LLM call: retry + fallback + sanitize]
    Base --> PromptCache[prompt cache control]
    Base --> Schema[tool schema conversion]
    Base --> Stream[streaming chunk assembly]
    Base --> Live[read Session/SessionContext]
```



Agents own no per-conversation state — that lives in `SessionContext` — so agents can be reused concurrently.

### 1.2 Specialized Agents

```mermaid
flowchart TB
    subgraph Routing & analysis
        Router[task_router]
        Analysis[task_analysis]
    end

    subgraph Recall & suggestion
        Recall[memory_recall]
        ToolSug[tool_suggestion]
        WfSel[workflow_select]
        QSug[query_suggest]
    end

    subgraph Simple mode
        Plan[plan]
        Simple[simple]
    end

    subgraph Multi-agent mode
        TPlan[task_planning]
        TDecomp[task_decompose]
        TExec[task_executor]
        TObs[task_observation]
        TJudge[task_completion_judge]
        TSum[task_summary]
    end

    subgraph Fibre mode
        Fibre[fibre]
        SelfCheck[self_check]
    end
```



Each agent's `agent_key` is how flow nodes reference it (e.g. `task_router`, `simple`, `task_planning`).

### 1.3 `FibreAgent` and Sub-agent Orchestration

```mermaid
flowchart TB
    Main[Main Session] --> FA[FibreAgent.run_stream]
    FA --> Orch[FibreOrchestrator]
    Orch --> Defs[(AgentDefinition registry<br/>sub-agent configs)]
    Orch --> Backend[FibreBackendClient<br/>fetch/manage sub-agents)]
    Orch --> SubMgr[shared SessionManager]
    Orch -->|delegated tool call| Sub[Sub-session 1..N]
    Sub -->|result| Orch
    Orch -->|aggregate| FA
```



In short: **in fibre mode, the main agent delegates work to sub-agents via tool calls; each sub-agent runs in its own sub-session and the result flows back to the main session.**

## 2. The Flow Layer

### 2.1 Node Types

```mermaid
flowchart LR
    Flow[AgentFlow.root] --> N1[AgentNode<br/>run a single agent]
    Flow --> N2[SequenceNode<br/>run steps in order]
    Flow --> N3[ParallelNode<br/>concurrent + max_concurrency]
    Flow --> N4[LoopNode<br/>condition + max_loops circuit breaker]
    Flow --> N5[IfNode<br/>true_body / false_body]
    Flow --> N6[SwitchNode<br/>variable + cases + default]
```



The whole flow is wrapped by `AgentFlow(name, root)`. `run_stream` also accepts `custom_flow` to fully replace the default orchestration.

### 2.2 Condition Registry `flow/conditions.py`

```mermaid
flowchart LR
    Reg[ConditionRegistry] --> C1[is_deep_thinking]
    Reg --> C2[enable_more_suggest]
    Reg --> C3[enable_plan]
    Reg --> C4[plan_should_start_execution]
    Reg --> C5[task_not_completed]
    Reg --> C6[self_check_should_retry]
    Reg --> C7[need_summary]

    Reg -.referenced by.-> If[IfNode.condition]
    Reg -.referenced by.-> Loop[LoopNode.condition]
```



Callers can register custom conditions and reference them from `custom_flow` (see end of this page).

### 2.3 Executor `flow/executor.py`

```mermaid
flowchart TB
    Start([execute AgentFlow.root]) --> Dispatch{node type?}

    Dispatch -->|AgentNode| Run[get agent → run_stream<br/>pass chunks through]
    Dispatch -->|SequenceNode| Seq[run steps in order]
    Dispatch -->|ParallelNode| Par[asyncio gather + semaphore]
    Dispatch -->|LoopNode| L1[check condition + max_loops]
    Dispatch -->|IfNode| If1[check condition]
    Dispatch -->|SwitchNode| Sw1[read variable → cases]

    Run --> Check{Session status?}
    Seq --> Check
    Par --> Check
    L1 --> Check
    If1 --> Check
    Sw1 --> Check

    Check -->|RUNNING| NextNode[next node]
    Check -->|INTERRUPTED / ERROR| Stop([stop])

    NextNode --> Dispatch
```



The executor only decides "how to walk the graph"; what happens inside an agent is the agent's own concern.

## 3. Default Flow: simple / multi / fibre

What `SAgent._build_default_flow(agent_mode, max_loop_count)` actually builds:

```mermaid
flowchart TB
    Start([input messages]) --> R[task_router]
    R --> DT{is_deep_thinking?}
    DT -->|yes| Ana[task_analysis] --> Sw
    DT -->|no| Sw
    Sw{Switch agent_mode}
    Sw -->|simple| SimpleBody
    Sw -->|multi| MultiBody
    Sw -->|fibre| FibreBody
    SimpleBody --> More
    MultiBody --> More
    FibreBody --> More
    More{enable_more_suggest?}
    More -->|yes| QS[query_suggest]
    More -->|no| End
    QS --> End([done])
```



### simple_agent_body

```mermaid
flowchart TB
    S0([enter simple]) --> Par1{parallel}
    Par1 --> ToolSug1[tool_suggestion]
    Par1 --> Recall1[memory_recall]
    ToolSug1 --> If1
    Recall1 --> If1
    If1{enable_plan?}
    If1 -->|yes| Plan1[plan]
    Plan1 --> If2{plan_should_start_execution?}
    If2 -->|yes| SimpleAgent1[simple]
    If2 -->|no| Need
    If1 -->|no| SimpleAgent2[simple]
    SimpleAgent1 --> Need
    SimpleAgent2 --> Need
    Need{need_summary?}
    Need -->|yes| Sum[task_summary] --> EndS
    Need -->|no| EndS([end simple])
```



### multi_agent_full

```mermaid
flowchart TB
    M0([enter multi]) --> Recall2[memory_recall]
    Recall2 --> Loop[Loop: task_not_completed<br/>up to max_loop_count]
    Loop --> P[task_planning]
    P --> TS[tool_suggestion]
    TS --> E[task_executor]
    E --> O[task_observation]
    O --> J[task_completion_judge]
    J -.task_not_completed.-> Loop
    J -->|done| Sum2[task_summary]
    Sum2 --> EndM([end multi])
```



### fib_agent_body

```mermaid
flowchart TB
    F0([enter fibre]) --> Loop2[Loop: self_check_should_retry<br/>up to 3]
    Loop2 --> Core[fibre core]
    Core --> Par2{parallel}
    Par2 --> TS2[tool_suggestion]
    Par2 --> R2[memory_recall]
    TS2 --> If3
    R2 --> If3
    If3{enable_plan?}
    If3 -->|yes| Plan2[plan] --> If4{plan_should_start_execution?}
    If4 -->|yes| FibA[fibre]
    If4 -->|no| SC
    If3 -->|no| FibB[fibre]
    FibA --> SC
    FibB --> SC
    SC[self_check]
    SC -.should_retry.-> Loop2
    SC -->|stop| EndF([end fibre])
```



## 4. Extending: Custom Flow & Sub-agents

The runtime exposes three extension points that, combined, can build arbitrary orchestration **without touching sagents source**.

### 4.1 Register a custom condition

```python
from sagents.flow.conditions import ConditionRegistry

@ConditionRegistry.register("user_paid")
def _user_paid(session_context, session=None) -> bool:
    return session_context.system_context.get("plan") == "pro"
```

### 4.2 Custom Flow

```python
from sagents.flow.schema import (
    AgentFlow, SequenceNode, AgentNode, IfNode, LoopNode,
)

custom_flow = AgentFlow(
    name="My Pipeline",
    root=SequenceNode(steps=[
        AgentNode(agent_key="task_router"),
        IfNode(
            condition="user_paid",
            true_body=LoopNode(
                condition="task_not_completed",
                max_loops=10,
                body=SequenceNode(steps=[
                    AgentNode(agent_key="task_planning"),
                    AgentNode(agent_key="task_executor"),
                    AgentNode(agent_key="task_completion_judge"),
                ]),
            ),
            false_body=AgentNode(agent_key="simple"),
        ),
        AgentNode(agent_key="task_summary"),
    ]),
)

async for chunks in agent.run_stream(
    ...,
    custom_flow=custom_flow,
):
    ...
```

When `custom_flow` is provided, `agent_mode` / `_build_default_flow` are bypassed.

### 4.3 Custom sub-agents (fibre)

`custom_sub_agents=[...]` injects extra sub-agent definitions without rewriting the flow, primarily for fibre orchestration:

```python
async for chunks in agent.run_stream(
    ...,
    agent_mode="fibre",
    custom_sub_agents=[
        {
            "agent_key": "data_fetcher",
            "description": "Pulls data from internal BI",
            "system_prompt": "...",
            "available_tools": ["http_fetcher", "sql_runner"],
        },
        # more sub-agent definitions...
    ],
):
    ...
```

The main fibre agent recognizes these as valid delegation targets.