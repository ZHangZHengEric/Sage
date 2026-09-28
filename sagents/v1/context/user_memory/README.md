# 用户记忆管理系统

这是 Reagent 框架的用户记忆管理模块，提供跨会话的用户个人记忆存储、检索和管理功能。

## 功能特性

- 🧠 **智能记忆管理**：支持偏好、经验、上下文等多种记忆类型
- � **自动提取与更新**：
    - **异步提取**：在对话过程中后台异步提取潜在记忆，不阻塞主流程
    - **智能去重**：自动检测重复记忆，合并更新，保持记忆库精简
- �🔍 **智能搜索**：根据关键词和类型快速检索相关记忆
- 💾 **多种存储后端**：
    - **本地文件**：轻量级 JSON 存储（默认）
    - **向量数据库**：基于 Embedding 的语义检索（支持 Chroma, Milvus 等，需适配 VectorStore 接口）
    - **MCP 工具**：通过 MCP 协议集成的外部记忆服务
- 🛠️ **工具化接口**：提供大模型可调用的记忆工具
- 📊 **统计分析**：记忆使用统计和分析功能
- 🔒 **数据安全**：支持备份和恢复功能

## 架构说明

模块采用分层架构设计：

```
sagents/v1/context/user_memory/
├── __init__.py          # 统一导出模块
├── manager.py           # UserMemoryManager：核心业务逻辑
├── interfaces.py        # IMemoryDriver：驱动接口定义
├── schemas.py           # MemoryEntry, MemoryType：数据模型
├── extractor.py         # MemoryExtractor：记忆提取与去重服务
└── drivers/             # 存储后端实现
    ├── tool.py          # ToolMemoryDriver：本地文件/MCP工具驱动
    └── vector.py        # VectorMemoryDriver：向量数据库驱动
```

## 核心流程

### 1. 记忆调用链路 (以 ToolMemoryDriver 为例)

1.  **环境配置 (SessionContext)**：
    *   `SessionContext` 初始化时，若提供 `workspace`，将自动推导 `MEMORY_ROOT_PATH`（`workspace/user_memory`），或优先使用 `MEMORY_ROOT_PATH` 环境变量。
    *   初始化 `UserMemoryManager` 并注入 `SessionContext`。

2.  **可用性检查**：
    *   `ToolMemoryDriver.is_available()` 检查 `MEMORY_ROOT_PATH` 及必需工具是否存在。

3.  **系统记忆注入**：
    *   `SessionContext` 启动时自动调用 `UserMemoryManager.get_system_memories()`。
    *   加载 `preference`, `requirement`, `persona`, `constraint` 等关键记忆并注入 `system_context`。

4.  **业务触发**：
    *   **Agent** 通过 `remember/recall/forget` 工具主动操作。
    *   **UserMemoryManager** 统一调度 Driver 执行操作。

```mermaid
sequenceDiagram
    participant Agent
    participant UserMemoryManager
    participant ToolMemoryDriver
    participant ToolManager
    participant MemoryTool
    participant FileSystem

    Agent->>UserMemoryManager: recall(query)
    UserMemoryManager->>ToolMemoryDriver: recall(query)
    ToolMemoryDriver->>ToolManager: run_tool_async('recall_user_memory', ...)
    ToolManager->>MemoryTool: recall_user_memory(...)
    MemoryTool->>FileSystem: read memories.json
    FileSystem-->>MemoryTool: data
    MemoryTool-->>ToolManager: result
    ToolManager-->>ToolMemoryDriver: result
    ToolMemoryDriver-->>UserMemoryManager: MemoryEntry[]
    UserMemoryManager-->>Agent: formatted string
```

### 2. 自动记忆提取流程

系统会在对话过程中（通常在流式响应结束后）触发异步记忆提取任务：

1.  **触发**：`SAgent` 在主流程结束后调用 `UserMemoryManager.extract_and_save()`。
2.  **提取**：`MemoryExtractor` 获取最近对话历史（默认10轮）。
3.  **分析**：调用 LLM (`gpt-4o`) 分析对话，提取新的记忆点。
4.  **去重与保存**：
    *   对新提取的记忆进行内部去重。
    *   调用 `remember` 保存新记忆。
    *   **冲突检测**：检查新记忆与现有系统记忆是否重复，自动删除旧的重复记忆。

## 快速开始

### 基础使用

```python
from sagents.v1.context.user_memory import UserMemoryManager, MemoryType

# 1. 自动使用 ToolMemoryDriver (需配合 ToolManager)
# memory_manager = UserMemoryManager(workspace="/path/to/workspace")

# 2. 或者注入自定义 Driver (例如向量存储)
# from sagents.v1.context.user_memory import VectorMemoryDriver
# driver = VectorMemoryDriver(vector_store, embedding_model)
# memory_manager = UserMemoryManager(driver=driver)

# 添加经验记录
await memory_manager.remember(
    user_id="eric_zz",
    memory_key="docker_issue_001",
    content="Docker容器启动失败：检查端口占用，重启Docker服务",
    memory_type="experience",
    tags="docker,故障排除"
)

# 搜索相关记忆
result_str = await memory_manager.recall(user_id="eric_zz", query="docker")
print(result_str)
```

### 在 SessionContext 中集成

在 Reagent 框架中，通常通过 `SessionContext` 初始化记忆管理。

```python
from sagents.v1.context.session_context import init_session_context
from sagents.v1.context.user_memory import UserMemoryManager

# 全局初始化 Manager
global_memory_manager = UserMemoryManager(memory_root="/path/to/user_memories")

# 创建带记忆功能的会话
session_context = init_session_context(
    session_id="session_123",
    user_id="eric_zz",
    workspace_root="/path/to/workspace",
    user_memory_manager=global_memory_manager, # 注入管理器
    context_budget_config={...}
)

# 访问记忆管理器
if session_context.user_memory_manager:
    # 获取系统级记忆摘要
    summary = await session_context.user_memory_manager.get_system_memories_summary(
        user_id="eric_zz", 
        session_id="session_123"
    )
    print(summary)
```

## 存储后端配置

### 1. 本地文件存储 (ToolMemoryDriver)

这是默认的存储方式，适用于单机环境。

*   **配置方式**：初始化 `UserMemoryManager` 时传入 `memory_root`。
*   **存储结构**：
    ```
    {memory_root}/
    └── {user_id}/
        └── memories.json     # 记忆数据文件
    ```
*   **工作原理**：通过 `sagents.v1.tool.memory_tool` 进行文件读写。

### 2. 向量数据库存储 (VectorMemoryDriver)

适用于需要大规模语义检索的场景。

*   **配置方式**：手动实例化 `VectorMemoryDriver` 并注入到 `UserMemoryManager`。
*   **依赖**：需要实现 `sagents.v1.retrieve_engine` 中的 `VectorStore` 和 `EmbeddingModel` 接口。

## 记忆类型

- **preference**: 用户偏好（语言、风格、习惯等）
- **experience**: 个人经验（解决方案、学习记录等）
- **requirement**: 用户明确要求
- **persona**: 用户人设/背景
- **constraint**: 约束条件
- **pattern**: 行为模式
- **context**: 个人上下文
- **note**: 个人备注
- **bookmark**: 个人书签

## 智能搜索策略

系统会根据用户输入智能判断是否需要搜索记忆：

| 输入类型 | 是否搜索 | 搜索内容 | 示例 |
|---------|---------|---------|------|
| 错误/问题 | ✅ 必搜索 | 经验记录 | "Docker启动失败" |
| 操作询问 | ✅ 必搜索 | 经验+偏好 | "怎么部署React应用" |
| 偏好相关 | ✅ 必搜索 | 偏好记录 | "我喜欢什么编程语言" |
| 技术讨论 | 🔍 智能判断 | 经验+上下文 | "Python性能优化" |
| 简单对话 | ❌ 不搜索 | - | "你好"、"谢谢" |

## API 参考

### UserMemoryManager

*   `remember(user_id, memory_key, content, ...)`: 记住记忆
*   `recall(user_id, query, limit, ...)`: 语义检索记忆
*   `forget(user_id, memory_key, ...)`: 删除记忆
*   `get_system_memories(user_id, ...)`: 获取系统级记忆（偏好、人设等）
*   `extract_and_save(session_context, session_id)`: 触发异步记忆提取

## 作者

Eric ZZ - 2024年12月21日
