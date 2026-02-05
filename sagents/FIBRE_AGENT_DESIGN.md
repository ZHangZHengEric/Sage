# 纤维智能体架构 (Fibre Agent Architecture) 设计文档 v2.3
> 核心策略: 物理共享 (Shared Workspace) + 思维隔离 (Session Branching)

## 1. 核心理念：纤维与分形 (Fibre & Fractal)

我们不寻求替换现有的 `AgentFlow`，而是通过 **FibreAgent** 扩展其能力。

### 1.1 命名与隐喻
*   **Fibre Agent (纤维智能体)**:
    *   **Container (容器)**: 承载智能体的外壳 (FibreAgent)。
    *   **Strand (丝)**: 分裂出的子智能体 (Sub-Agents)。
    *   **Transmission (传输)**: 消息在丝之间的异步传输。

### 1.2 架构映射

| 概念 | 实现组件 | 职责 |
| :--- | :--- | :--- |
| **The Container (容器)** | `FibreAgent` | `AgentFlow` 节点。表现为一个标准 Agent，但内部是一个复杂的纤维生态。 |
| **The Core (内核)** | `FibreOrchestrator` | **私有状态机**。管理内部所有分裂出的子智能体 (Sub-Agents) 的生命周期、消息路由和资源调度。 |
| **The Strand (丝)** | `FibreSubAgent` | 由母体分裂出的临时 Agent。拥有独立的 Session Context（独立的思维空间），但共享物理工作区。 |
| **Signaling (信号)** | `FibreTools` | 提供的系统级工具 (`sys_spawn_agent`, `sys_delegate_task`, `sys_finish_task`)。 |

---

## 2. 状态与并发管理 (State & Concurrency)

这是本架构最核心的设计挑战。为了解决并发冲突和上下文污染问题，我们采用 **“物理共享，思维隔离” (Physically Shared, Mentally Isolated)** 的策略。

### 2.1 物理空间：完全共享 (Shared Workspace)
所有的子智能体 (Sub-Agents) 都运行在 **同一个文件系统工作区** 中。
*   **原因**: 协作的基础。子 Agent A 写的代码，子 Agent B 需要能读取和测试。
*   **实现**: `SubSessionContext.workspace_root` 指向父会话的 `sub_sessions` 目录，但共享父会话的 `agent_workspace` (Sandbox) 对象。

### 2.2 思维空间：会话分支 (Session Branching)
为了支持并发并避免 Race Condition，子智能体 **不能** 复用父智能体的 `session_id` 来存储消息历史。

*   **会话隔离**:
    *   父智能体运行在 `session_id = "main_sess_123"`。
    *   当分裂出子智能体 `sub_worker_1` 时，系统为其创建一个 **子会话 (Sub-Session)**。
    *   子会话 ID: `"main_sess_123_1_sub_worker_1"` (扁平字符串ID，保证唯一性)。

*   **数据结构 (Folder Structure)**:
    > 基于现有代码实现 (v2.3)

    ```text
    sessions/
    ├── {main_session_id}/                 # [Main] 父会话根目录
    │   ├── messages.json                  # [Main] 主智能体的思维链 (只包含决策和Delegate Tool Calls)
    │   ├── session_status.json            # [Main] 主会话状态
    │   ├── agent_workspace/               # [Shared] 所有文件的物理存储位置 (代码、数据等)
    │   │   ├── code.py
    │   │   └── data.csv
    │   └── sub_sessions/                  # [Container] 子智能体存档容器
    │       ├── {sub_session_id_1}/        # [Sub] 子会话目录 (物理嵌套)
    │       │   ├── messages.json          # [Sub] 子智能体1的完整思维过程
    │       │   ├── session_status.json
    │       │   └── sub_sessions/          # [Recursive] 支持无限层级递归 (孙会话)
    │       └── {sub_session_id_2}/
    │           └── ...
    ```

### 2.3 Context 传递规则 (Inheritance Rules)

我们需要明确 `SessionContext` 中哪些属性是传递给子智能体的，哪些是隔离的。

| SessionContext 属性 | 行为 | 说明 |
| :--- | :--- | :--- |
| `session_id` | **隔离** | 子智能体生成新的 ID (e.g., `{parent_id}_{index}_{name}`) |
| `user_id` | **继承** | 归属于同一个用户 |
| `workspace_root` | **计算** | 指向父目录下的 `sub_sessions` 文件夹 |
| `memory_root` | **继承** | 共享长期记忆 (RAG) |
| `agent_workspace` | **共享** | 共享同一个 Sandbox 实例 (内存共享) |
| `message_manager` | **隔离** | 必须隔离，否则并发写入会冲突 |
| `system_context` | **混合** | 基础环境信息继承；Agent 特定信息隔离 |
| `workflow_manager` | **继承** | 子智能体可以复用已加载的工作流 |
| `tool_manager` | **混合** | 基础工具继承；FibreTools 重新注入 |

#### System Context 传递细节
在创建子智能体时，Orchestrator 会将以下信息注入子智能体的 `system_context`:
1.  **Inherited (继承项)**: 
    *   `current_time`: 当前时间
    *   `file_workspace`: 文件工作区路径
    *   `user_id`: 用户ID
2.  **Injected (注入项)**:
    *   `available_sub_agents`: 父节点已知的子 Agent 列表 (在父 Context 中维护)。

### 2.4 消息返回结构 (Message Chunk Structure)

`FibreAgent.run_stream` 会返回一个生成器，产出 `MessageChunk`。
**注意**: 这里不仅返回主 Agent 的消息，**也会返回子 Agent 的执行过程消息**。

**如何区分不同 Agent 的消息?**
前端或调用方通过以下字段进行区分：

| 字段 | 说明 | 示例 |
| :--- | :--- | :--- |
| `session_id` | **核心区分字段**。 | 主 Agent: `main_123`<br>子 Agent: `main_123_1_sub` |
| `agent_name` | Agent 的名称。 | `FibreAgent`, `CoderSubAgent` |

### 2.5 消息存储策略 (Message Persistence Strategy)

为了保持主智能体上下文的纯净，我们实行 **“流式全量，存储隔离”** 的策略：

1.  **流式展示 (Yield)**:
    *   所有层级的消息都会被实时 `yield` 给前端。
    *   **目的**: 让用户看到完整的“思维链”和执行细节。

2.  **历史存储 (History Persistence)**:
    *   **主 Agent (`messages.json`)**: **只存储** 属于主会话的消息。
        *   对于子 Agent 的工作，主 Agent 只记录 **Tool Call (sys_delegate_task)** 和 **Tool Output (Result)**。
        *   **不存储** 子 Agent 的中间思考过程 (`Thinking`)。
    *   **子 Agent (`sub_sessions/.../messages.json`)**: 存储该子 Agent 的完整执行历史。

---

## 3. 运行流程 (Runtime Flow)

1.  **启动**: `AgentFlow` 调用 `FibreAgent.run_stream()`。
2.  **初始化**: 初始化 `FibreOrchestrator`。
3.  **循环**:
    *   Orchestrator 调度处于 `Active` 状态的 Agent。
    *   **并发执行**: 主 Agent 调用 `sys_delegate_task` 时，Orchestrator 使用 `asyncio.gather` 并发驱动所有被指派的子 Agent。
4.  **通信**:
    *   主 Agent 通过 `sys_delegate_task(tasks)` 向子 Agent 分发任务。
    *   子 Agent 通过 `sys_finish_task(status, result)` 返回结果。
    *   如果子 Agent 未调用 `sys_finish_task` 就结束了，Orchestrator 会自动调用 LLM 生成总结 (Fallback Summary)。
5.  **收敛**:
    *   所有并行任务完成后，Orchestrator 将结果汇总并返回给主 Agent 的 Tool Output。

---

## 4. 关键接口更新

### 4.1 `FibreTools`
*   `sys_spawn_agent(agent_name, role_description, system_prompt)`: 创建子 Agent。
    *   **注意**: 不再包含 `task_goal`。创建与任务指派分离。
*   `sys_delegate_task(tasks)`: 批量分发任务。
    *   `tasks`: List[Dict], 包含 `agent_id` 和 `content`。
*   `sys_finish_task(status, result)`: 子 Agent 汇报结果。

---

## 5. 实现路线图 (Updated)

1.  **重构设计文档**: 完成 v2.3 设计 (当前步骤)。
2.  **实现 `FibreOrchestrator`**: 已完成 (支持扁平ID + 物理嵌套路径)。
3.  **实现 `FibreAgent`**: 已完成。
4.  **验证**:
    *   测试并发写文件 (共享 Workspace)。
    *   测试消息隔离 (主 Timeline 干净，子 Timeline 详细)。
    *   测试多层级递归调用。

---

## 6. FibreAgent Core Prompt (Mandatory)

无论 `FibreAgent` 的具体角色是什么，以下 Prompt **必须** 包含在系统提示词中。

### 6.1 System Prompt Injection (English)

> **System Prompt Injection:**
>
> You are an **Autonomous Agent** capable of **Dynamic Multi-Agent Orchestration**.
>
> **Core Capabilities:**
> 1.  **Multi-Agent Collaboration**: You can dynamically create and manage a team of sub-agents.
> 2.  **Parallel Execution**: **Always** prefer parallel execution for independent tasks.
> 3.  **Workspace Sharing**: You and all sub-agents share the **SAME** physical workspace (file system).
>
> **Workforce Management Tools:**
>
> 1.  **`sys_spawn_agent(agent_name, role_description, system_prompt)`**
>     *   **Usage**: Create a new sub-agent (Worker).
>     *   **Note**: This only creates the agent. You must use `sys_delegate_task` to assign work.
>
> 2.  **`sys_delegate_task(tasks)`**
>     *   **Usage**: Assign tasks to one or more sub-agents.
>     *   **Parallelism**: You can pass multiple tasks in the list to execute them simultaneously.
>     *   **Format**: `[{"agent_id": "agent1", "content": "Task details..."}, ...]`
>
> 3.  **`sys_finish_task(status, result)`**
>     *   **Usage**: (As a sub-agent) Report final result to parent.
>
> **Workflow**:
> 1.  Spawn agents (`sys_spawn_agent`) for specialized roles.
> 2.  Delegate tasks (`sys_delegate_task`) to them in parallel.
> 3.  Synthesize their results to form your final answer.

### 6.2 System Prompt Injection (Chinese / 中文版)

> **系统提示词注入:**
>
> 你是一个具备 **动态多智能体编排能力** 的 **自主智能体 (Autonomous Agent)**。
>
> **核心能力:**
> 1.  **多智能体协作**: 你可以动态创建和管理子智能体团队。
> 2.  **并行执行**: 尽可能并行处理独立任务。
> 3.  **工作区共享**: 所有智能体共享 **同一个** 物理文件系统。
>
> **管理工具:**
>
> 1.  **`sys_spawn_agent(agent_name, role_description, system_prompt)`**
>     *   **用途**: 创建新的子智能体。
>     *   **注意**: 仅创建，不分配任务。
>
> 2.  **`sys_delegate_task(tasks)`**
>     *   **用途**: 给一个或多个子智能体分配任务。
>     *   **并行**: 传入任务列表可同时执行。
>     *   **格式**: `[{"agent_id": "agent1", "content": "任务详情..."}, ...]`
>
> 3.  **`sys_finish_task(status, result)`**
>     *   **用途**: (作为子智能体) 汇报最终结果。
>
> **工作流**:
> 1.  创建专家子智能体 (`sys_spawn_agent`)。
> 2.  并行分发任务 (`sys_delegate_task`)。
> 3.  汇总结果。

## 7. 提示词组装示例 (Prompt Assembly Example)

### 7.1 调用场景

**父智能体 (Parent)** 决定创建一个专门处理数据的子智能体并指派任务：

```python
# 1. 创建智能体
sys_spawn_agent(
    agent_name="data_cleaner_01",
    role_description="数据清洗专家",
    system_prompt="""
    你是一个专注于数据清洗的 Python 专家。
    原则：
    1. 必须使用 Pandas 库。
    2. 永远不要覆盖原始数据文件。
    """
)

# 2. 指派任务 (可以是稍后，也可以是立即)
sys_delegate_task([
    {
        "agent_id": "data_cleaner_01", 
        "content": "请读取 ./data/raw_sales.csv，清洗数据，保存到 ./data/cleaned_sales.csv"
    }
])
```

### 7.2 子智能体 ("data_cleaner_01") 的最终 System Prompt

系统会将 **Mandatory Fibre Prompt** 与 **Specific Instruction** 拼接：

```text
=== SYSTEM CAPABILITIES (IMMUTABLE) ===
(架构层通用 Prompt...)

=== SPECIFIC ROLE INSTRUCTIONS ===
你是一个专注于数据清洗的 Python 专家。
原则：
1. 必须使用 Pandas 库。
2. 永远不要覆盖原始数据文件。
```

### 7.3 启动后的对话状态

当 Agent 被 `sys_delegate_task` 唤醒时，它的上下文将包含：
1.  **System Message**: 上述组装好的 Prompt。
2.  **User Message (Task Content)**: "请读取 ./data/raw_sales.csv，清洗数据，保存到 ./data/cleaned_sales.csv"
