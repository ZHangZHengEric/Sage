# 纤维智能体架构 (Fibre Agent Architecture) 设计文档 v2.2
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
| **Signaling (信号)** | `FibreTools` | 提供的系统级工具 (`sys_spawn`, `sys_send`, `sys_complete`)。 |

---

## 2. 状态与并发管理 (State & Concurrency)

这是本架构最核心的设计挑战。为了解决并发冲突和上下文污染问题，我们采用 **“物理共享，思维隔离” (Physically Shared, Mentally Isolated)** 的策略。

### 2.1 物理空间：完全共享 (Shared Workspace)
所有的子智能体 (Sub-Agents) 都运行在 **同一个文件系统工作区** 中。
*   **原因**: 协作的基础。子 Agent A 写的代码，子 Agent B 需要能读取和测试。
*   **实现**: `SubSessionContext.workspace_root` 指向与父节点相同的路径。

### 2.2 思维空间：会话分支 (Session Branching)
为了支持并发并避免 Race Condition，子智能体 **不能** 复用父智能体的 `session_id` 来存储消息历史。

*   **会话隔离**:
    *   父智能体运行在 `session_id = "main_sess_123"`。
    *   当分裂出子智能体 `sub_worker_1` 时，系统为其创建一个 **子会话 (Sub-Session)**。
    *   子会话 ID: `"main_sess_123/sub_worker_1"` (逻辑上)。

*   **数据结构 (Folder Structure)**:
    > 基于现有项目结构修正

    ```text
    workspace_root/
    ├── {main_session_id}/
    │   ├── messages.json              # [主] 主智能体的思维链 (只包含关键决策和子任务摘要)
    │   ├── session_status.json        # [主] 主会话状态
    │   ├── agent_workspace/           # [共享] 所有文件的物理存储位置 (代码、数据等)
    │   │   ├── code.py
    │   │   └── data.csv
    │   └── sub_sessions/              # [新增] 子智能体存档区
    │       ├── {sub_agent_id_1}/      # 子会话目录
    │       │   ├── messages.json      # [子] 子智能体1的完整思维过程 (Debug/Audit用)
    │       │   ├── session_status.json
    │       │   └── agent_workspace -> ../../agent_workspace  # [软链或逻辑指向] 共享上层
    │       └── {sub_agent_id_2}/
    │           └── ...
    ```

### 2.3 Context 传递规则 (Inheritance Rules)

我们需要明确 `SessionContext` 中哪些属性是传递给子智能体的，哪些是隔离的。

| SessionContext 属性 | 行为 | 说明 |
| :--- | :--- | :--- |
| `session_id` | **隔离** | 子智能体生成新的 ID (e.g., `{parent_id}_{sub_id}`) |
| `user_id` | **继承** | 归属于同一个用户 |
| `workspace_root` | **继承** | 指向同一个物理根目录 |
| `memory_root` | **继承** | 共享长期记忆 (RAG) |
| `agent_workspace` | **共享** | 指向同一个 `agent_workspace` 目录 |
| `message_manager` | **隔离** | 必须隔离，否则并发写入会冲突 |
| `system_context` | **混合** | 基础环境信息继承；Agent 特定信息隔离 |
| `workflow_manager` | **继承** | 子智能体可以复用已加载的工作流 |
| `session_memory_manager` | **隔离** | 短期记忆独立 |
| `agent_config` | **隔离** | 子智能体可能有不同的模型配置 |

#### System Context 传递细节
在创建子智能体时，Orchestrator 会将以下信息注入子智能体的 `system_context`:
1.  **Inherited (继承项)**: 
    *   `current_time`: 当前时间
    *   `file_workspace`: 文件工作区路径
    *   `file_permission`: 文件权限描述
    *   `user_id`: 用户ID
    *   **含义**: 这些是直接从父 Session 的 `system_context` 复制过来的值。
2.  **Injected (注入项)**:
    *   `available_agents`: 当前系统中可用的 Agent 列表 (避免重复创建，直接复用)。
    *   `parent_task`: 父智能体指派的具体任务描述。
    *   `parent_session_id`: 父会话 ID (用于追溯)。
    *   **含义**: 这些是 Orchestrator 在创建子 Agent 时**额外添加**的信息，父 Session 中可能没有或值不同。

### 2.4 消息返回结构 (Message Chunk Structure)

`FibreAgent.run_stream` 会返回一个生成器，产出 `MessageChunk`。
**注意**: 这里不仅返回主 Agent 的消息，**也会返回子 Agent 的执行过程消息**。

**如何区分不同 Agent 的消息?**
前端或调用方通过以下字段进行区分：

| 字段 | 说明 | 示例 |
| :--- | :--- | :--- |
| `session_id` | **核心区分字段**。 | 主 Agent: `main_123`<br>子 Agent: `main_123/sub_coder` |
| `agent_name` | Agent 的名称。 | `FibreAgent`, `CoderSubAgent` |
| `role` | 消息角色。 | `assistant`, `tool` |

**示例场景**:
1.  用户提问。
2.  `FibreAgent` (session=`main`) 思考: "我需要让 Coder 写代码。" -> **yield Chunk (session=main)**
3.  `FibreOrchestrator` 启动 `Coder` 子 Agent (session=`main/coder`)。
4.  `Coder` (session=`main/coder`) 思考: "开始编写 hello.py" -> **yield Chunk (session=main/coder)**
5.  `Coder` 调用工具 `write_file` -> **yield Chunk (session=main/coder)**
6.  `Coder` 完成任务 -> **yield Chunk (session=main/coder)**
7.  `FibreAgent` (session=`main`) 总结: "代码已生成。" -> **yield Chunk (session=main)**

这样前端可以根据 `session_id` 将消息渲染在不同的 Tab 或气泡中，展示清晰的层级结构。

### 2.5 消息存储策略 (Message Persistence Strategy)

为了保持主智能体上下文的纯净，我们实行 **“流式全量，存储隔离”** 的策略：

1.  **流式展示 (Yield)**:
    *   所有层级的消息（主 Agent + 子 Agent 的所有思考/工具调用）都会被实时 `yield` 给前端。
    *   **目的**: 让用户看到完整的“思维链”和执行细节。

2.  **历史存储 (History Persistence)**:
    *   **主 Agent (`messages.json`)**: **只存储** 属于主会话的消息 (`session_id == main_session_id`)。
        *   对于子 Agent 的工作，主 Agent 只记录 **Tool Call (委派任务)** 和 **Tool Output (子 Agent 的最终报告)**。
        *   **不存储** 子 Agent 的中间思考过程 (`Thinking`) 或内部工具调用。
    *   **子 Agent (`sub_sessions/.../messages.json`)**: 存储该子 Agent 的完整执行历史，用于调试和审计。

**实现机制**:
`AgentFlow` 在接收到流式消息块时，会根据 `session_id` 进行过滤，只有匹配当前 Context 的消息才会被 `add_messages` 到内存和磁盘。

---

## 3. 运行流程 (Runtime Flow)

1.  **启动**: `AgentFlow` 调用 `FibreAgent.run_stream()`。
2.  **初始化**: 初始化 `FibreOrchestrator`。
3.  **循环**:
    *   Orchestrator 调度处于 `Active` 状态的 Agent (可能是 Root，也可能是并发的 Subs)。
    *   **并发执行**: 如果有多个子 Agent 处于 Active 状态，Orchestrator 使用 `asyncio.gather` 或 `TaskGroup` 并发驱动它们。
    *   由于它们拥有独立的 `MessageManager` (内存实例) 和 `messages.json` (磁盘文件)，并发执行是安全的。
4.  **通信**:
    *   Agent 之间通过 `sys_send_message(target_id, content)` 通信。
    *   消息由 Orchestrator 路由，直接插入目标 Agent 的 `Input Queue`。
    *   **Yield**: 所有 Agent 产生的 `MessageChunk` 都会通过 `Orchestrator` 汇聚并 `yield` 给 `AgentFlow`。
5.  **收敛**:
    *   Root Agent 决定任务结束。
    *   Orchestrator 终止所有子进程。
    *   返回最终流。

---

## 4. 关键接口更新

### 4.1 `FibreOrchestrator`
*   `create_sub_session(parent_context, agent_config)`: 创建子会话上下文。
*   `tick()`: 事件循环的主脉搏，负责 tick 所有活跃的 Agent。

### 4.2 `FibreTools`
*   `sys_spawn_agent(role, goal)`: 分裂。
*   `sys_wait_agent(agent_id)`: (可选) 挂起自己，直到子 Agent 返回。

---

## 5. 实现路线图 (Updated)

1.  **重构设计文档**: 完成 v2.2 设计 (当前步骤)。
2.  **实现 `FibreOrchestrator`**:
    *   重点实现 **Sub-Session Manager**: 负责创建子目录、初始化子 Context。
    *   实现基于 `asyncio` 的并发调度器。
3.  **实现 `FibreAgent`**: 封装 Orchestrator。
4.  **验证**:
    *   测试并发写文件 (共享 Workspace)。
    *   测试消息隔离 (主 Timeline 干净，子 Timeline 详细)。

---

## 6. FibreAgent Core Prompt (Mandatory)

无论 `FibreAgent` 的具体角色是什么，以下 Prompt **必须** 包含在系统提示词中，以确保其正确理解自身的架构特性。

### 6.1 System Prompt Injection (English)

> **System Prompt Injection:**
>
> You are an **Autonomous Agent** capable of **Dynamic Multi-Agent Orchestration**.
>
> **Core Capabilities:**
> 1.  **Multi-Agent Collaboration**: You are not limited to working alone. You can dynamically create and manage a team of sub-agents to handle complex tasks.
> 2.  **Parallel Execution**: Do not execute sequential tasks yourself if they can be parallelized. Spawn multiple sub-agents to work simultaneously.
> 3.  **Workspace Sharing**: You and all your sub-agents share the **SAME** physical workspace (file system).
>     *   If Sub-Agent A writes a file, Sub-Agent B can read it immediately.
>     *   **Warning**: Coordinate carefully to avoid overwriting files at the same time.
>
> **Workforce Management Tools & Protocols:**
> You have access to special system tools to manage your workforce:
>
> 1.  **`sys_spawn_agent(agent_name, role_description, system_instruction, task_goal) -> agent_id`**
>     *   **Usage**: Create a new sub-agent.
>     *   **Parameters Explanation**:
>         *   `agent_name`: A unique identifier (e.g., "sql_expert_1").
>         *   `role_description`: A one-line summary of what this agent does (e.g., "Handles all database queries"). Used for your own tracking.
>         *   `system_instruction`: **THE MOST IMPORTANT PARAMETER**. This string becomes the **System Prompt** of the new sub-agent. It defines the sub-agent's persona, constraints, and specific capabilities.
>             *   *Example*: "You are a SQL expert. You only write read-only SELECT queries. Always format output as CSV."
>         *   `task_goal`: The first instruction/message sent to this new agent to start its work.
>
> 2.  **`sys_send_message(agent_id, content)`**
>     *   **Usage**: Send a new instruction or feedback to an *existing* sub-agent.
>     *   **Protocol**: Use this to guide the agent if its initial output was insufficient, or to assign a new task to an idle agent.
>
> 3.  **`sys_finish_task(status, summary, details)`**
>     *   **Usage**: (As a sub-agent) Report your final result back to your parent agent.
>     *   **Protocol**:
>         *   `status`: "success" or "failed".
>         *   `summary`: A concise conclusion for the parent's memory.
>         *   `details`: Detailed execution report, file paths generated, or error logs.
>
> **Memory & Communication:**
> *   **Isolation**: Your thought process (context) is ISOLATED from your sub-agents. You do NOT see their step-by-step thinking unless they explicitly report it using `sys_finish_task`.
> *   **Workflow**:
>     1.  Spawn a sub-agent (`sys_spawn_agent`) with a specific `system_instruction` (Persona) and `task_goal` (Task).
>     2.  Wait for its report (Tool Output).
>     3.  If satisfied, proceed. If not, send feedback (`sys_send_message`).
>
> **Your Golden Rule**:
> Be a conductor, not just a player. When the task is complex, **DELEGATE**—break it down, spawn agents, and orchestrate the flow.

### 6.2 System Prompt Injection (Chinese / 中文版)

> **系统提示词注入:**
>
> 你是一个具备 **动态多智能体编排能力** 的 **自主智能体 (Autonomous Agent)**。
>
> **核心能力:**
> 1.  **多智能体协作 (Multi-Agent Collaboration)**: 你不必孤军奋战。你可以动态地创建和管理一个子智能体团队来处理复杂任务。
> 2.  **并行执行 (Parallel Execution)**: 如果任务可以并行化，不要自己顺序执行。分裂出多个子智能体同时工作。
> 3.  **工作区共享 (Workspace Sharing)**: 你和所有子智能体共享 **同一个** 物理工作区 (文件系统)。
>     *   子智能体 A 写入的文件，子智能体 B 可以立即读取。
>     *   **警告**: 需小心协调，避免同时写入同一文件导致冲突。
>
> **劳动力管理工具与协议 (Workforce Management Tools & Protocols):**
> 你拥有特殊的系统级工具来管理你的劳动力：
>
> 1.  **`sys_spawn_agent(agent_name, role_description, system_instruction, task_goal) -> agent_id`**
>     *   **用途**: 创建一个新的子智能体。
>     *   **参数详解**:
>         *   `agent_name`: 唯一的标识符 (例如 "sql_expert_1")。
>         *   `role_description`: 一句话的角色摘要 (例如 "负责所有数据库查询")。这仅用于你自己的记录和跟踪。
>         *   `system_instruction`: **最重要的参数**。这个字符串将直接成为新子智能体的 **系统提示词 (System Prompt)**。它定义了子智能体的人设、限制和具体能力。
>             *   *示例*: "你是一名 SQL 专家。你只能编写只读的 SELECT 查询。永远将输出格式化为 CSV。"
>         *   `task_goal`: 发送给该新智能体的第一条指令/任务，用于启动它的工作。
>
> 2.  **`sys_send_message(agent_id, content)`**
>     *   **用途**: 向一个 *已存在* 的子智能体发送新的指令或反馈。
>     *   **协议**: 当子智能体的产出不符合要求需要修正，或需要给空闲的智能体指派新任务时使用此工具。
>
> 3.  **`sys_finish_task(status, summary, details)`**
>     *   **用途**: (作为子智能体) 向父智能体汇报最终结果。
>     *   **协议**:
>         *   `status` (状态): "success" (成功) 或 "failed" (失败)。
>         *   `summary` (摘要): 给父智能体记忆留存的简明结论。
>         *   `details` (详情): 详细的执行报告、生成的文件路径列表或错误日志，供父智能体查阅。
>
> **记忆与通信:**
> *   **隔离性**: 你的思维过程 (Context) 与子智能体是 **隔离** 的。除非它们通过 `sys_finish_task` 显式汇报，否则你无法看到它们的逐步思考过程。
> *   **工作流**:
>     1.  分裂子智能体 (`sys_spawn_agent`)，并赋予其特定的 `system_instruction` (人设) 和 `task_goal` (任务)。
>     2.  等待其汇报 (作为工具调用结果返回)。
>     3.  如果满意，继续流程。如果不满意，发送反馈 (`sys_send_message`)。
>
> **黄金法则**:
> 做一个指挥家，而不仅仅是演奏者。当面对复杂任务时，**委派 (DELEGATE)** 它——拆解任务，分裂智能体，并编排整个工作流。

## 7. 提示词组装示例 (Prompt Assembly Example)

为了更直观地理解 `sys_spawn_agent` 的作用，以下展示了当父智能体创建一个子智能体时，该子智能体最终接收到的 **完整 System Prompt** 是如何组装的。

### 7.1 调用场景

假设 **父智能体 (Parent)** 决定创建一个专门处理数据的子智能体。请注意 **System Instruction (岗位原则)** 与 **Task Goal (具体工单)** 的区别：

```python
# 父智能体调用工具
sys_spawn_agent(
    agent_name="data_cleaner_01",
    role_description="数据清洗专家",
    # System Instruction: 定义能力边界、工具偏好、代码风格等“岗位原则”
    system_instruction="""
    你是一个专注于数据清洗的 Python 专家。
    原则与能力：
    1. 必须使用 Pandas 库进行处理。
    2. 代码风格必须符合 PEP8。
    3. 对于任何缺失值，默认策略是使用平均值填充，除非任务另有说明。
    4. 永远不要覆盖原始数据文件，必须保存为新文件。
    """,
    # Task Goal: 当前具体的执行目标
    task_goal="请读取 ./data/raw_sales.csv，清洗数据，去除异常值，保存到 ./data/cleaned_sales.csv"
)
```

### 7.2 子智能体 ("data_cleaner_01") 的最终 System Prompt

系统会将 **Mandatory Fibre Prompt (架构层注入)** 与 **Specific Instruction (父智能体定义)** 进行拼接。即便子智能体只是一个“工人”，它依然继承了架构层赋予的“分形扩展”能力。

**注意**: `task_goal` **不会** 出现在 System Prompt 中，而是作为第一条 **User Message** 发送给 Agent。

**最终 System Prompt 组装结果如下**:

```text
=== SYSTEM CAPABILITIES (IMMUTABLE) ===

你是一个具备 **动态多智能体编排能力** 的 **自主智能体 (Autonomous Agent)**。
... (省略架构层通用 Prompt，同 6.2 节) ...
**黄金法则**:
做一个指挥家，而不仅仅是演奏者。当面对复杂任务时，**委派 (DELEGATE)** 它——拆解任务，分裂智能体，并编排整个工作流。

=== SPECIFIC ROLE INSTRUCTIONS ===

你是一个专注于数据清洗的 Python 专家。
原则与能力：
1. 必须使用 Pandas 库进行处理。
2. 代码风格必须符合 PEP8。
3. 对于任何缺失值，默认策略是使用平均值填充，除非任务另有说明。
4. 永远不要覆盖原始数据文件，必须保存为新文件。
```

### 7.3 启动后的对话状态

当 Agent 启动时，它的上下文 (Context) 将包含：
1.  **System Message**: 上述组装好的 Prompt。
2.  **User Message (第一条)**: "请读取 ./data/raw_sales.csv，清洗数据，去除异常值，保存到 ./data/cleaned_sales.csv"

## 8. 工程风险与缓解策略 (Risks & Mitigations)

在实际执行复杂任务时，完全依赖 LLM 的“自觉”存在较高风险。本章节定义了系统层面的强制约束。

### 8.1 "传声筒"效应 (The "Telephone Game" Risk)
*   **风险**: 子 Agent 发生幻觉（Hallucination），明明任务失败却向父 Agent 汇报 "success"，或者遗漏了生成文件的具体路径。父 Agent 基于错误信息继续执行，导致错误级联。
*   **缓解策略**:
    1.  **强制结构化汇报**: `sys_finish_task` 的 `details` 字段**必须**包含机器可读的关键信息（如 `created_files: List[str]`）。
    2.  **父级验货 (Parent Verification)**: 父 Agent 在收到 `success` 报告后，**不应盲目信任**。必须调用 `list_files` 或 `read_file` 确认子 Agent 声称生成的文件确实存在。
    3.  **Orchestrator 介入**: 系统层可以在 `sys_finish_task` 被调用时，自动扫描子 Agent 的工作区变动，并将差异报告附加到 Tool Output 中，作为“客观事实”补充给父 Agent。

### 8.2 文件系统竞态 (File System Race Conditions)
*   **风险**: 尽管 Prompt 警告了“小心协调”，但两个子 Agent 同时写入 `result.csv` 仍可能发生，导致数据丢失。
*   **缓解策略**:
    1.  **命名空间隔离**: 强制建议子 Agent 使用 `{agent_name}_{filename}` 的格式命名输出文件。
    2.  **原子写入**: 系统提供的 `write_file` 工具应实现原子写入（写临时文件 -> 重命名）。
    3.  **文件锁 (File Locks)**: (高阶) 引入 `sys_lock_file(path)` 工具，允许 Agent 显式锁定关键资源。

### 8.3 僵尸进程与死循环 (Zombies & Infinite Loops)
*   **风险**: 子 Agent 遇到报错 -> 尝试修复 -> 修复失败 -> 再次报错。陷入死循环，消耗大量 Token 和时间，而父 Agent 一直在等待。
*   **缓解策略**:
    1.  **最大轮数限制 (Max Turns)**: 每个子 Agent 启动时必须设定 `max_turns` (e.g., 10轮)。超过限制强制终止并返回 `Failed`。
    2.  **父级超时 (Parent Timeout)**: `sys_spawn_agent` 应该支持 `timeout` 参数。
    3.  **健康监控**: Orchestrator 监控子 Agent 的输出。如果检测到连续重复的 Tool Call 或报错，判定为 Stuck，强制杀掉。

### 8.4 上下文过载 (Context Overload)
*   **风险**: 如果任务层级过深，父 Agent 的上下文会被大量的 `sys_spawn_agent` 和 `sys_finish_task` 填满，导致遗忘最早的 User Instruction。
*   **缓解策略**:
    1.  **摘要压缩**: 当父 Agent 上下文过长时，将已完成的子任务记录压缩为一句话摘要。
    2.  **深度限制**: 建议最大递归深度限制为 2 层 (Root -> Child -> Grandchild)，避免过于复杂的调用树。
