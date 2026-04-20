---

## layout: default

title: 智能体与流程编排
parent: 架构
nav_order: 5
description: "AgentBase、各专用 Agent、AgentFlow / FlowExecutor、三种 agent_mode"
lang: zh
ref: architecture-sagents-agent-flow

{% include lang_switcher.html %}

# 智能体与流程编排

这一篇覆盖 `sagents/agent/` 与 `sagents/flow/`。**Agent 是干活的单元，Flow 决定 Agent 之间的执行关系。** 两者解耦：换流程不改 Agent，换 Agent 也不改流程。

## 1. Agent 层

### 1.1 `AgentBase` 提供的能力

```mermaid
flowchart LR
    Base[AgentBase] --> RunStream[run_stream<br/>统一异步流接口]
    Base --> Model[持有 model + model_config]
    Base --> SafeCall[LLM 调用：<br/>重试 + 降级 + sanitize]
    Base --> PromptCache[prompt 缓存控制]
    Base --> Schema[工具 schema 转换]
    Base --> Stream[流式 chunk 拼装]
    Base --> Live[读取 Session/SessionContext]
```



Agent 自身不持有“这次会话的状态”，状态都在 `SessionContext` 里——Agent 因此可以并发复用。

### 1.2 已实现的专用 Agent

```mermaid
flowchart TB
    subgraph 路由与分析
        Router[task_router]
        Analysis[task_analysis]
    end

    subgraph 召回与建议
        Recall[memory_recall]
        ToolSug[tool_suggestion]
        WfSel[workflow_select]
        QSug[query_suggest]
    end

    subgraph 简单模式
        Plan[plan]
        Simple[simple]
    end

    subgraph 多智能体模式
        TPlan[task_planning]
        TDecomp[task_decompose]
        TExec[task_executor]
        TObs[task_observation]
        TJudge[task_completion_judge]
        TSum[task_summary]
    end

    subgraph fibre 模式
        Fibre[fibre]
        SelfCheck[self_check]
    end
```



各 Agent 的 `agent_key` 是流程中 `AgentNode` 引用它的标识，例如 `task_router`、`simple`、`task_planning` 等。

### 1.3 `FibreAgent` 与子智能体编排

```mermaid
flowchart TB
    Main[主 Session] --> FA[FibreAgent.run_stream]
    FA --> Orch[FibreOrchestrator]
    Orch --> Defs[(AgentDefinition 注册表<br/>子智能体配置)]
    Orch --> Backend[FibreBackendClient<br/>从后端取/管理子智能体]
    Orch --> SubMgr[SessionManager 复用]
    Orch -->|委派工具调用| Sub[Sub-session 1..N]
    Sub -->|结果| Orch
    Orch -->|汇总| FA
```



简单理解：**fibre 模式下，主 Agent 通过工具调用把任务委派给子 Agent，每个子 Agent 在自己的 sub-session 里跑，结果再回流到主 session。**

## 2. Flow 层

### 2.1 节点类型

```mermaid
flowchart LR
    Flow[AgentFlow.root] --> N1[AgentNode<br/>执行单个 Agent]
    Flow --> N2[SequenceNode<br/>顺序执行 steps]
    Flow --> N3[ParallelNode<br/>并行 + max_concurrency]
    Flow --> N4[LoopNode<br/>condition + max_loops 熔断]
    Flow --> N5[IfNode<br/>true_body / false_body]
    Flow --> N6[SwitchNode<br/>variable + cases + default]
```



整个 Flow 由 `AgentFlow(name, root)` 包装根节点。`run_stream` 也接受 `custom_flow` 参数，调用方可以完全自定义编排。

### 2.2 条件注册表 `flow/conditions.py`

```mermaid
flowchart LR
    Reg[ConditionRegistry] --> C1[is_deep_thinking]
    Reg --> C2[enable_more_suggest]
    Reg --> C3[enable_plan]
    Reg --> C4[plan_should_start_execution]
    Reg --> C5[task_not_completed]
    Reg --> C6[self_check_should_retry]
    Reg --> C7[need_summary]

    Reg -.被引用.-> If[IfNode.condition]
    Reg -.被引用.-> Loop[LoopNode.condition]
```



业务方可以注册自己的条件函数，让 `custom_flow` 用上（见本页末尾）。

### 2.3 执行器 `flow/executor.py`

```mermaid
flowchart TB
    Start([开始执行 AgentFlow.root]) --> Dispatch{节点类型?}

    Dispatch -->|AgentNode| Run[拿 Agent 实例 → run_stream<br/>透传 chunk]
    Dispatch -->|SequenceNode| Seq[顺序执行 steps]
    Dispatch -->|ParallelNode| Par[asyncio 并发 + 信号量]
    Dispatch -->|LoopNode| L1[检查 condition + max_loops]
    Dispatch -->|IfNode| If1[检查 condition]
    Dispatch -->|SwitchNode| Sw1[读 variable → cases]

    Run --> Check{Session 状态?}
    Seq --> Check
    Par --> Check
    L1 --> Check
    If1 --> Check
    Sw1 --> Check

    Check -->|RUNNING| NextNode[下一个节点]
    Check -->|INTERRUPTED / ERROR| Stop([停止])

    NextNode --> Dispatch
```



执行器只负责“怎么走”，不负责“走到 Agent 后做什么”——后者是 Agent 自己的责任。

## 3. 默认流程：simple / multi / fibre

`SAgent._build_default_flow(agent_mode, max_loop_count)` 拼出来的形状：

```mermaid
flowchart TB
    Start([输入 messages]) --> R[task_router]
    R --> DT{is_deep_thinking?}
    DT -->|是| Ana[task_analysis] --> Sw
    DT -->|否| Sw
    Sw{Switch agent_mode}
    Sw -->|simple| SimpleBody
    Sw -->|multi| MultiBody
    Sw -->|fibre| FibreBody
    SimpleBody --> More
    MultiBody --> More
    FibreBody --> More
    More{enable_more_suggest?}
    More -->|是| QS[query_suggest]
    More -->|否| End
    QS --> End([结束])
```



### simple_agent_body

```mermaid
flowchart TB
    S0([进入 simple]) --> Par1{并行}
    Par1 --> ToolSug1[tool_suggestion]
    Par1 --> Recall1[memory_recall]
    ToolSug1 --> If1
    Recall1 --> If1
    If1{enable_plan?}
    If1 -->|是| Plan1[plan]
    Plan1 --> If2{plan_should_start_execution?}
    If2 -->|是| SimpleAgent1[simple]
    If2 -->|否| Need
    If1 -->|否| SimpleAgent2[simple]
    SimpleAgent1 --> Need
    SimpleAgent2 --> Need
    Need{need_summary?}
    Need -->|是| Sum[task_summary] --> EndS
    Need -->|否| EndS([结束 simple])
```



### multi_agent_full

```mermaid
flowchart TB
    M0([进入 multi]) --> Recall2[memory_recall]
    Recall2 --> Loop[Loop: task_not_completed<br/>最多 max_loop_count 次]
    Loop --> P[task_planning]
    P --> TS[tool_suggestion]
    TS --> E[task_executor]
    E --> O[task_observation]
    O --> J[task_completion_judge]
    J -.task_not_completed.-> Loop
    J -->|完成| Sum2[task_summary]
    Sum2 --> EndM([结束 multi])
```



### fib_agent_body

```mermaid
flowchart TB
    F0([进入 fibre]) --> Loop2[Loop: self_check_should_retry<br/>最多 3 次]
    Loop2 --> Core[fibre core]
    Core --> Par2{并行}
    Par2 --> TS2[tool_suggestion]
    Par2 --> R2[memory_recall]
    TS2 --> If3
    R2 --> If3
    If3{enable_plan?}
    If3 -->|是| Plan2[plan] --> If4{plan_should_start_execution?}
    If4 -->|是| FibA[fibre]
    If4 -->|否| SC
    If3 -->|否| FibB[fibre]
    FibA --> SC
    FibB --> SC
    SC[self_check]
    SC -.should_retry.-> Loop2
    SC -->|不再重试| EndF([结束 fibre])
```



## 4. 二次开发：自定义流程与子智能体

调用方有三个扩展点，组合起来几乎可以拼出任意复杂的 Agent 编排，而**完全不修改 sagents 源码**。

### 4.1 注册自定义条件

```python
from sagents.flow.conditions import ConditionRegistry

@ConditionRegistry.register("user_paid")
def _user_paid(session_context, session=None) -> bool:
    return session_context.system_context.get("plan") == "pro"
```

### 4.2 自定义 Flow

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

# 传给 SAgent.run_stream
async for chunks in agent.run_stream(
    ...,
    custom_flow=custom_flow,
):
    ...
```

传了 `custom_flow` 之后，`agent_mode` / `_build_default_flow` 都会被绕过。

### 4.3 自定义子智能体（fibre）

`custom_sub_agents=[...]` 在不重写流程的前提下注入额外子智能体定义，主要服务 fibre 编排：

```python
async for chunks in agent.run_stream(
    ...,
    agent_mode="fibre",
    custom_sub_agents=[
        {
            "agent_key": "data_fetcher",
            "description": "负责从内部 BI 拉数据",
            "system_prompt": "...",
            "available_tools": ["http_fetcher", "sql_runner"],
        },
        # 更多子智能体定义...
    ],
):
    ...
```

主 fibre Agent 会把这些子智能体识别成可委派的目标。