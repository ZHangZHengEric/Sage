# 用户记忆管理系统

这是 Reagent 框架的用户记忆管理模块，提供跨会话的用户个人记忆存储、检索和管理功能。

## 功能特性

- 🧠 **智能记忆管理**：支持偏好、经验、上下文等多种记忆类型
- 🔍 **智能搜索**：根据关键词和类型快速检索相关记忆
- 💾 **多种存储后端**：支持本地文件、MCP工具、混合模式
- 🛠️ **工具化接口**：提供大模型可调用的记忆工具
- 📊 **统计分析**：记忆使用统计和分析功能
- 🔒 **数据安全**：支持备份和恢复功能

## 快速开始

### 基础使用

```python
from sagents.context.user_memory import UserMemoryManager, MemoryType

# 创建记忆管理器
memory_manager = UserMemoryManager(
    user_id="eric_zz",
    memory_root="user_memories"
)

# 设置用户偏好
memory_manager.set_preference("language", "zh-CN")
memory_manager.set_preference("response_style", "详细")

# 添加经验记录
memory_manager.add_memory(
    content="Docker容器启动失败：检查端口占用，重启Docker服务",
    memory_type=MemoryType.EXPERIENCE,
    tags=["docker", "故障排除"],
    importance=0.8
)

# 搜索相关记忆
results = memory_manager.search_memories("docker")
for result in results:
    print(f"找到记忆: {result['content']}")
```

### 在 SessionContext 中使用

```python
from sagents.context.session_context import init_session_context
from sagents.context.user_memory import MemoryBackend

# 创建带记忆功能的会话
session_context = init_session_context(
    session_id="session_123",
    user_id="eric_zz",
    workspace_root="/path/to/workspace",
    memory_backend=MemoryBackend.LOCAL_FILE,
    memory_config={
        "memory_root": "user_memories",
        "auto_backup": True,
        "max_memories": 5000
    }
)

# 使用记忆功能
session_context.user_memory.set_preference("coding_style", "简洁")
session_context.save_user_experience(
    title="解决Python导入问题",
    content="检查PYTHONPATH环境变量设置",
    tags=["python", "环境配置"]
)
```

### Agent 中使用记忆工具

```python
from sagents.context.user_memory import create_memory_tools_for_agent

class MyAgent:
    def __init__(self, session_context):
        self.session_context = session_context
        self.memory_tools = create_memory_tools_for_agent(
            session_context.user_memory
        )
    
    def process_user_input(self, user_input):
        # 大模型可以主动调用记忆工具
        if "我喜欢" in user_input:
            # 记录用户偏好
            self.memory_tools["remember_user_preference"](
                "preference_key", "preference_value", "描述"
            )
        
        if "问题" in user_input:
            # 搜索相似经验
            similar = self.memory_tools["recall_similar_experience"](user_input)
            return similar
```

## 记忆类型

- **PREFERENCE**: 用户偏好（语言、风格、习惯等）
- **EXPERIENCE**: 个人经验（解决方案、学习记录等）
- **PATTERN**: 行为模式（操作习惯、工作流程等）
- **CONTEXT**: 个人上下文（项目信息、目标等）
- **NOTE**: 个人备注（重要信息、提醒等）
- **BOOKMARK**: 个人书签（有用链接、资源等）

## 存储后端

### 本地文件存储 (LOCAL_FILE)

```python
memory_manager = UserMemoryManager(
    user_id="user_id",
    memory_root="user_memories",
    backend=MemoryBackend.LOCAL_FILE
)
```

存储结构：
```
user_memories/
├── eric_zz/
│   ├── profile.json      # 用户配置
│   ├── memories.json     # 记忆数据
│   ├── index.json        # 索引文件
│   └── backup/           # 备份文件
└── global_index.json     # 全局索引
```

### MCP 工具存储 (MCP_TOOL)

```python
memory_manager = UserMemoryManager(
    user_id="user_id",
    backend=MemoryBackend.MCP_TOOL
)
```

### 混合模式 (HYBRID)

```python
memory_manager = UserMemoryManager(
    user_id="user_id",
    backend=MemoryBackend.HYBRID
)
```

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

#### 基础操作
- `get(key, default=None)`: 获取记忆值
- `set(key, value, memory_type)`: 设置记忆值
- `delete(key)`: 删除记忆
- `exists(key)`: 检查记忆是否存在

#### 便捷方法
- `get_preference(key, default=None)`: 获取用户偏好
- `set_preference(key, value)`: 设置用户偏好
- `add_memory(content, memory_type, tags, importance)`: 添加新记忆
- `search_memories(query, memory_type=None)`: 搜索记忆

#### 管理功能
- `get_memory_stats()`: 获取统计信息
- `backup_memories(backup_path=None)`: 备份记忆
- `restore_memories(backup_path)`: 恢复记忆

### MemoryTools

大模型可调用的工具方法：

- `remember_user_preference(key, value, description)`: 记住用户偏好
- `save_solution(problem, solution, tags, importance)`: 保存解决方案
- `recall_similar_experience(situation, limit)`: 回忆相似经验
- `note_user_context(context_type, context_info)`: 记录用户上下文
- `get_user_preference(key, default)`: 获取用户偏好
- `search_memories_by_tags(tags, memory_type, limit)`: 按标签搜索
- `get_memory_summary()`: 获取记忆摘要
- `backup_user_memories()`: 备份用户记忆

## 测试

运行测试以验证功能：

```python
from sagents.context.user_memory.test_memory import run_all_tests

run_all_tests()
```

## 配置选项

```python
# 记忆配置示例
memory_config = {
    "memory_root": "user_memories",     # 存储根目录
    "auto_backup": True,                # 自动备份
    "max_memories": 10000,              # 最大记忆数量
    "compression_enabled": False,       # 是否启用压缩
    "backup_interval": 86400            # 备份间隔（秒）
}
```

## 最佳实践

1. **合理设置重要性评分**：重要的记忆设置较高的 importance 值
2. **使用有意义的标签**：便于后续搜索和分类
3. **定期备份**：启用自动备份或定期手动备份
4. **控制记忆数量**：设置合理的 max_memories 限制
5. **结构化存储**：使用层级键名组织相关记忆

## 注意事项

- 记忆数据以 JSON 格式存储，确保内容可序列化
- 大量记忆可能影响搜索性能，建议定期清理
- 备份文件包含敏感信息，注意安全保护
- MCP 工具后端需要相应的 MCP 服务器支持

## 作者

Eric ZZ - 2024年12月21日