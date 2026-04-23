---
layout: default
title: Session & Context
parent: Architecture
nav_order: 6
description: "Session, SessionContext, message manager, session/user memory and Workflow"
lang: en
ref: architecture-sagents-session-context
---

{% include lang_switcher.html %}

# Session & Context

`sagents/session_runtime.py` and `sagents/context/` together form the "state layer". Agents are stateless processors; everything stateful lives here.

## 1. Session Lifecycle: `Session` and `SessionManager`

```mermaid
flowchart LR
    SAgent --> SM[SessionManager · process-wide singleton]
    SM --> Map[(session_id → Session map)]
    SM --> S1[Session]
    SM --> S2[Session]
    SM --> S3[...]
    S1 --> Ctx1[SessionContext]
    S2 --> Ctx2[SessionContext]
    S1 --> Lock1[lock_manager cross-session locks]
    SM --> CV[_session_id_var · ContextVar<br/>fetch current session_id anywhere]
```



`SessionManager` provides:

- `get_or_create(session_id, sandbox_type)`
- `save_session / interrupt_session / close_session`
- `get_live_session(session_id)`: get a live Session reference from anywhere
- Cooperates with `lock_manager` so one session is not driven concurrently

### Session State Machine

```mermaid
stateDiagram-v2
    [*] --> IDLE
    IDLE --> RUNNING: run_stream_safe acquires lock & starts
    RUNNING --> COMPLETED: flow ended normally
    RUNNING --> INTERRUPTED: user/system interrupt
    RUNNING --> ERROR: exception
    COMPLETED --> [*]
    INTERRUPTED --> [*]
    ERROR --> [*]
```



`FlowExecutor` checks the session status before/after every node and bails out on `INTERRUPTED` / `ERROR` to avoid burning tokens halfway.

## 2. `SessionContext`: the Blackboard

```mermaid
flowchart TB
    subgraph SessionContext
        ID[Identity<br/>session_id · user_id · agent_id · parent_session_id]
        Sys[system_context · extra info injected into prompt]
        WS[Workspace<br/>session_root_space · sandbox_agent_workspace · volume_mounts]
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

    Agents -->|read/write| SessionContext
```



It is a **Blackboard**: agents collaborate by reading/writing it, with no direct dependency on each other.

### Two-step Explicit Init

```mermaid
sequenceDiagram
    participant Sess as Session
    participant Ctx as SessionContext
    participant Sandbox
    participant SkillProj as SandboxSkillManager

    Sess->>Ctx: __init__(session_id, user_id, ...)
    Note right of Ctx: placeholder, sandbox=None
    Sess->>Ctx: configure_runtime(model, sandbox cfg, agent_id)
    Sess->>Ctx: await init_more()
    Ctx->>Sandbox: SandboxProviderFactory.create(...)
    Sandbox-->>Ctx: ISandboxHandle
    Ctx->>SkillProj: project visible skills into sandbox
    Ctx-->>Sess: ready
```



`init_more()` moves heavy resources (sandbox boot, skill projection) out of the constructor so a half-initialized context cannot leak.

## 3. Messages: `MessageChunk` + `MessageManager`

### 3.1 The Chunk Unit

```mermaid
flowchart LR
    Chunk[MessageChunk] --> ID[message_id · session_id]
    Chunk --> Role[role · user/assistant/tool/system]
    Chunk --> Type[message_type · text/tool_call/tool_result/token_usage/...]
    Chunk --> Content[content · tool_calls · tool_call_id]
    Chunk --> Meta[timing & extension metadata]
```



The whole runtime streams `List[MessageChunk]`.

### 3.2 MessageManager: Source of Truth for History

```mermaid
flowchart TB
    Inputs[chunks in] --> MM[MessageManager]
    MM --> Merge[merge same message_id pieces]
    MM --> Filter[filter system messages<br/>system is built per-call by agents]
    MM --> Compress[compress / trim by token budget]
    MM --> Estimate[token estimation<br/>global ratio sample pool]
    MM --> Out1[agents fetch budget-fitting history before LLM call]
    MM --> Out2[stream out to caller]
    MM --> CB[ContextBudgetManager<br/>window / priority / buffer]
    CB --> Compress
```



Highlights:

- System messages do not enter history; agents assemble them at call time.
- Context budgeting is centralized in `ContextBudgetManager`; all agents share the same rules.
- Token estimation uses a global sampled ratio (heuristic) to avoid running the tokenizer per message.

## 4. Memory: Session-level + User-level

```mermaid
flowchart LR
    subgraph Short term
        SMM[SessionMemoryManager<br/>valid for the session lifetime]
    end

    subgraph Long term
        UMM[UserMemoryManager · indexed by user_id]
        UMM --> Iface[IMemoryDriver abstraction]
        Iface --> Drv[ToolMemoryDriver / others]
        UMM --> Ext[Extractor · LLM extracts persistent entries]
        UMM --> Path[(MEMORY_ROOT_PATH<br/>or workspace/user_memory)]
    end

    Recall[memory_recall agent] -->|recall| SMM
    Recall -->|recall| UMM
    Tool[memory_tool] -->|read/write| UMM
    Obs -. events .-> UMM
```



Memory is optional for agents — invoked explicitly by `MemoryRecallAgent` and similar — not forced into every session.

## 5. Workflow: `context/workflows/`

```mermaid
flowchart LR
    AvailWF[run_stream available_workflows arg] --> WM[WorkflowManager]
    WM --> WfList[(registered workflow templates)]
    WfSel[workflow_select agent] -->|pick on demand| WM
    WM -->|currently usable steps| Agent
```



A `Workflow` is a "reusable task template" — a predefined sequence of steps. Note the naming overlap but distinct purposes:

- `flow/`: which agents to run (orchestration)
- `workflows/`: fixed operational steps for a class of business tasks (business template)

## 6. State Evolution During One Session

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
    Sess->>Ctx: build or reuse SessionContext
    Ctx->>Ctx: init_more() boots sandbox/skill projection
    Sess->>Ctx: write audit_status (agent_mode, deep_thinking ...)
    Sess->>MM: ingest input messages
    loop each FlowExecutor step
        Sess->>MM: fetch budget-fitting history
        Sess->>Mem: recall session/user memory
        Sess-->>Caller: yield streaming chunks
        Sess->>MM: append assistant/tool chunks
    end
    SAgent->>SM: close_session(session_id)
    SM->>Mem: trigger user memory extraction (on demand)
```



## 7. Relation to External Storage

```mermaid
flowchart LR
    Ctx[SessionContext · pure runtime memory] --> AppLayer[App layer]
    AppLayer --> Server[(app/server: multi-tenant DB / object storage)]
    AppLayer --> Desktop[(app/desktop: local SQLite / user dir)]
    AppLayer --> CLI[(app/cli / examples: files or in-memory)]
```



`SessionContext` itself does not bind to any database. **"Pure in-memory runtime + persistence in the app layer"** is one of the reasons sagents can be reused across so many app shapes.