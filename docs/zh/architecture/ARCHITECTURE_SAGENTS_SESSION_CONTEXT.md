---
layout: default
title: 会话与上下文
parent: 架构
nav_order: 6
description: "Session、SessionContext、消息管理、会话/用户记忆与 Workflow"
lang: zh
ref: architecture-sagents-session-context
---

{% include lang_switcher.html %}

# 会话与上下文

`sagents/session_runtime.py` 与 `sagents/context/` 一起承担“状态层”。智能体本身是无状态的处理器，所有状态都集中在这里。

## 1. 会话生命周期：`Session` 与 `SessionManager`

```mermaid
flowchart LR
    SAgent --> SM[SessionManager · 进程级单例]
    SM --> Map[(session_id → Session 映射)]
    SM --> S1[Session]
    SM --> S2[Session]
    SM --> S3[...]
    S1 --> Ctx1[SessionContext]
    S2 --> Ctx2[SessionContext]
    S1 --> Lock1[lock_manager 跨会话锁]
    SM --> CV[_session_id_var · ContextVar<br/>任意位置拿当前 session_id]
```

`SessionManager` 提供：

- `get_or_create(session_id, sandbox_type)`
- `save_session / interrupt_session / close_session`
- `get_live_session(session_id)`：跨模块拿到正在跑的 Session 引用
- 与 `lock_manager` 协作，保证同一 session 不被并发跑两次

### 会话状态机

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> RUNNING: run_stream_safe 加锁后启动
    RUNNING --> COMPLETED: 流程正常结束
    RUNNING --> INTERRUPTED: 用户/系统主动中断
    RUNNING --> ERROR: 异常
    COMPLETED --> [*]
    INTERRUPTED --> [*]
    ERROR --> [*]
```

`FlowExecutor` 在每个节点前后都检查 Session 状态，进入 `INTERRUPTED` / `ERROR` 时立即退出循环，避免“跑一半还在烧 token”。

## 2. `SessionContext`：黑板

```mermaid
flowchart TB
    subgraph SessionContext
        ID[身份<br/>session_id · user_id · agent_id · parent_session_id]
        Sys[system_context · 注入到 Prompt 的额外信息]
        WS[工作空间<br/>session_root_space · sandbox_agent_workspace · volume_mounts]
        SBX[sandbox · ISandboxHandle]
        TM[tool_manager]
        SM[skill_manager + sandbox_skill_manager]
        ST[status · audit_status]
        MM[MessageManager]
        SMM[SessionMemoryManager]
        UMM[UserMemoryManager]
        WF[WorkflowManager]
        CB[ContextBudgetManager]
    end

    Agents -->|读写| SessionContext
```

它是一个**黑板（Blackboard）**：多个 Agent 通过读写它来协同，但互相之间没有直接依赖。

### 显式两阶段初始化

```mermaid
sequenceDiagram
    participant Sess as Session
    participant Ctx as SessionContext
    participant Sandbox
    participant SkillProj as SandboxSkillManager

    Sess->>Ctx: __init__(session_id, user_id, ...)
    Note right of Ctx: 仅占位，sandbox=None
    Sess->>Ctx: configure_runtime(model, sandbox cfg, agent_id)
    Sess->>Ctx: await init_more()
    Ctx->>Sandbox: SandboxProviderFactory.create(...)
    Sandbox-->>Ctx: ISandboxHandle
    Ctx->>SkillProj: 把可见技能投影进沙箱
    Ctx-->>Sess: 就绪
```

`init_more()` 把耗时资源（沙箱启动、技能投影）从构造函数里挪出来，避免“半初始化”的上下文被误用。

## 3. 消息：`MessageChunk` + `MessageManager`

### 3.1 MessageChunk 单元

```mermaid
flowchart LR
    Chunk[MessageChunk] --> ID[message_id · session_id]
    Chunk --> Role[role · user/assistant/tool/system]
    Chunk --> Type[message_type · text/tool_call/tool_result/token_usage/...]
    Chunk --> Content[content · tool_calls · tool_call_id]
    Chunk --> Meta[时序与扩展元数据]
```

整个运行时的流式输出都是 `List[MessageChunk]`。

### 3.2 MessageManager：消息历史的真理之源

```mermaid
flowchart TB
    Inputs[chunk 流入] --> MM[MessageManager]
    MM --> Merge[合并同 message_id 的多段]
    MM --> Filter[过滤 system 消息<br/>system 由 Agent 单独拼]
    MM --> Compress[大模型持久摘要<br/>与覆盖锚点]
    MM --> Estimate[完整请求 token 投影<br/>Provider usage 动态校准]
    MM --> Out1[Agent 构造完整 Provider 请求]
    MM --> Out2[流式输出给上游]
    MM --> CB[ContextBudgetManager<br/>辅助 Agent 临时 prompt 限长]
```

要点：

- system 消息不进历史，由 Agent 在调用时单独拼。
- 主会话历史不再按规则截断，也不再创建新 artifact。完整输入超过窗口的 85% 时，只用大模型生成的持久摘要替换旧历史；Provider 真实上下文超限时直接进入同一摘要恢复链。
- 最新 user 与近期活跃消息受保护，assistant 工具调用必须与所有对应 tool result 成对保留。多次摘要通过覆盖锚点串联，推理视图只保留最新有效摘要。
- 完整请求 token 投影只是主动触发信号，并使用 Provider prompt usage 动态校准；不扣除最大输出 token。Provider 拒绝始终是权威结果。
- 辅助 Agent 仍可构造临时的预算限长 prompt 视图，但不会回写主会话 ledger。

## 4. 记忆：会话级 + 用户级

```mermaid
flowchart LR
    subgraph 短期
        SMM[SessionMemoryManager<br/>会话生命周期内有效]
    end

    subgraph 长期
        UMM[UserMemoryManager · 以 user_id 索引]
        UMM --> Iface[IMemoryDriver 抽象]
        Iface --> Drv[ToolMemoryDriver / 其他]
        UMM --> Ext[Extractor · 用 LLM 抽取持久条目]
        UMM --> Path[(MEMORY_ROOT_PATH<br/>或 workspace/user_memory)]
    end

    Recall[memory_recall Agent] -->|召回| SMM
    Recall -->|召回| UMM
    Tool[memory_tool] -->|读写| UMM
    Obs -. 事件 .-> UMM
```

记忆系统对 Agent 是“可有可无”的能力，由 `MemoryRecallAgent` 等显式调用，不强制塞进每一次会话。

## 5. Workflow：`context/workflows/`

```mermaid
flowchart LR
    AvailWF[run_stream 入参 available_workflows] --> WM[WorkflowManager]
    WM --> WfList[(已注册 Workflow 模板)]
    WM -->|当前可用步骤| Agent
```

`Workflow` 是“可重用任务模板”——一段预定义的步骤说明。注意它和 `flow/` 名字相近但定位完全不同：

- `flow/`：跑哪些 Agent（编排）
- `workflows/`：某一类业务任务的固定操作步骤说明（业务模板）

## 6. 一次会话中状态如何演进

```mermaid
sequenceDiagram
    participant Caller
    participant SAgent
    participant SM as SessionManager
    participant Sess as Session
    participant Ctx as SessionContext
    participant MM as MessageManager
    participant Mem as Memory Managers

    Caller->>SAgent: run_stream(messages, ...)
    SAgent->>SM: get_or_create(session_id)
    SM-->>SAgent: Session
    SAgent->>Sess: configure_runtime(...)
    Sess->>Ctx: 构造或复用 SessionContext
    Ctx->>Ctx: init_more() 初始化沙箱/技能投影
    Sess->>Ctx: 写入 audit_status (agent_mode, deep_thinking ...)
    Sess->>MM: 写入输入 messages
    loop FlowExecutor 每步
        Sess->>MM: 读取符合预算的历史
        Sess->>Mem: 召回会话/用户记忆
        Sess-->>Caller: yield 流式 chunk
        Sess->>MM: 增量写入 assistant/tool chunk
    end
    SAgent->>SM: close_session(session_id)
    SM->>Mem: 触发用户记忆抽取（按需）
```

## 7. 与外部存储的关系

```mermaid
flowchart LR
    Ctx[SessionContext · 纯运行时内存] --> AppLayer[应用层]
    AppLayer --> Server[(app/server: 多租户 DB / 对象存储)]
    AppLayer --> Desktop[(app/desktop: 本地 SQLite / 用户目录)]
    AppLayer --> CLI[(app/cli / examples: 文件或纯内存)]
```

`SessionContext` 自身不直接绑定任何具体数据库。**“运行时纯内存 + 应用层负责持久化”**，正是 sagents 能被多种应用形态复用的关键之一。
