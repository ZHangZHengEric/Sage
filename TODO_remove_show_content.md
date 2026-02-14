# Show_Content 字段移除与迁移计划

## 进度 (Progress)
- [x] 创建移除分支 `refactor/remove-show-content`
- [x] 修正入口文件 (CLI/Demo/Server) 以优先使用 `content` (2025-02-14)
  - `app/sage_cli.py`: 替换 `show_content` 为 `content`
  - `app/sage_demo.py`: 替换 `show_content` 为 `content`
  - `app/sage_server.py`: 移除 `show_content` 清理逻辑
- [x] **第一阶段：逻辑迁移与数据重定向 (Logic Migration)**
  - [x] TaskDecomposeAgent 改造: 将任务数据迁移至 `SessionContext.audit_status`，流式输出重定向至 `content`。
  - [x] SimpleAgent / ReactAgent 改造: `reasoning_content` 重定向至 `content`。
  - [x] MessageManager 逻辑清理: 移除 `show_content` 相关合并与过滤逻辑。
  - [x] TaskObservationAgent 改造: 将流式 `delta_content` 重定向至 `content`。
- [x] **第二阶段：字段物理移除 (Field Removal)**
  - [x] 定义修改: 从 `MessageChunk` dataclass 中删除 `show_content` 字段。
  - [x] 全局实例化修正: 修正所有 Agent (`common_agent`, `agent_base`, `task_observation_agent`, etc.) 的实例化代码。

## 目标
移除 `MessageChunk` 中的 `show_content` 字段，将所有视觉展示逻辑迁移至 `content`，并将结构化数据迁移至 `SessionContext.audit_status`。

## 风险评估
1. **TaskDecomposeAgent**: 目前 `content` 存储结构化 JSON，`show_content` 存储 Markdown 列表。直接合并会丢失结构化数据。
   - **解决方案**: 已将 JSON 数据移入 `SessionContext.audit_status`。
2. **前端兼容性**: 前端高度依赖 `show_content` 进行渲染。
   - **解决方案**: 需同步修改前端 `MessageRenderer.vue` (目前暂停修改前端代码，待指示)。

## 详细执行步骤

### 第一阶段：逻辑迁移与数据重定向 (Logic Migration) - 已完成

#### 1. TaskDecomposeAgent 改造 (Completed)
- **文件**: `sagents/agent/task_decompose_agent.py`
- **修改点**:
  - **流式输出**: 在 `run_stream` 方法中，将 `yield MessageChunk(..., show_content=...)` 改为 `content=...`。
  - **最终结果处理**: 在 `_finalize_decomposition_result` 方法中：
    - 不再生成包含 JSON 的 `content` 覆盖原有内容。
    - 将解析后的 `tasks` (List[Dict]) 存储到 `session_context.audit_status['task_decomposition_results']`。
    - 最终返回的 Message 保持为人类可读的规划文本 (Markdown)。

#### 2. SimpleAgent / ReactAgent 改造 (Completed)
- **文件**: `sagents/agent/simple_agent.py`, `sagents/agent/simple_react_agent.py`
- **修改点**:
  - **Reasoning/Thinking**: 将 `reasoning_content` 的赋值从 `show_content` 改为 `content`。这会将思维链保留在对话历史中。

#### 3. MessageManager 逻辑清理 (Completed)
- **文件**: `sagents/context/messages/message_manager.py`
- **修改点**:
  - `merge_new_message_old_messages`: 删除 `if new_message.show_content is not None` 的合并逻辑。
  - `add_messages`: 修改空消息过滤条件，移除对 `show_content` 的检查。

---

### 第二阶段：字段物理移除 (Field Removal) - 已完成

#### 1. 定义修改 (Completed)
- **文件**: `sagents/context/messages/message.py`
- **修改点**:
  - 从 `MessageChunk` dataclass 中删除 `show_content: Optional[str] = None` 字段。

#### 2. 全局实例化修正 (Completed)
- **搜索范围**: 全局搜索 `MessageChunk` 和 `show_content`。
- **涉及文件列表** (需逐一修正实例化代码):
  - `sagents/agent/task_analysis_agent.py` (Checked - Clean)
  - `sagents/agent/task_executor_agent.py` (Checked - Clean)
  - `sagents/agent/task_router_agent.py` (Checked - Clean)
  - `sagents/agent/task_rewrite_agent.py` (Checked - Clean)
  - `sagents/agent/common_agent.py` (Fixed)
  - `sagents/agent/simple_agent_v2.py` (Checked - Clean/Commented out)
  - `sagents/agent/agent_base.py` (Fixed)
  - `sagents/agent/task_observation_agent.py` (Fixed)
  - 以及其他所有 Agent 的 `run_stream` 或 `yield` 部分。

---

### 第三阶段：前端适配 (Frontend Adaptation) - 暂停 (Paused)

#### 1. 渲染组件修改
- **文件**: `app/web/src/components/chat/MessageRenderer.vue`
- **修改点**:
  - 将所有 `message.show_content` 替换为 `message.content`。
  - 检查 `v-if` 判断逻辑，确保没有遗漏的显示逻辑。

---

### 第四阶段：验证 (Verification) - 待进行 (Pending)

1. **单元测试**: 运行现有测试确保 Agent 实例化不报错。
2. **集成测试**:
   - 运行 `TaskDecomposeAgent`，确保前端能看到流式生成的任务列表。
   - 检查 `SessionContext.audit_status` 是否正确包含任务数据。
   - 检查 `SimpleAgent` 的思维链是否正常显示。
