# Agent as Tool 移除方案

## 概述

当前架构中，Agent 可以通过 `to_tool()` 方法转换为 `AgentToolSpec`，然后注册到 `ToolManager` 中作为工具使用。这种设计带来了以下问题：

1. **概念混淆**：Agent 和 Tool 是两个不同层次的概念
2. **复杂性增加**：ToolManager 需要特殊处理 `AgentToolSpec` 类型的流式响应
3. **维护困难**：Agent 的生命周期管理和工具执行逻辑耦合

本方案旨在完全移除 "Agent as Tool" 的设计，改为通过 `sys_spawn_agent` / `sys_delegate_task` / `sys_finish_task` 等 Fibre 工具来管理子 Agent。

## 现状分析

### 当前代码结构

```python
# sagents/agent/agent_base.py
class AgentBase(ABC):
    def to_tool(self) -> AgentToolSpec:
        """将智能体转换为工具格式"""
        tool_spec = AgentToolSpec(
            name=self.__class__.__name__,
            description=self.agent_description,
            func=self.run_stream,  # ← 流式执行方法
            parameters={},
            required=[]
        )
        return tool_spec
```

```python
# sagents/tool/tool_schema.py
@dataclass
class AgentToolSpec:
    """Agent 作为工具的规格定义"""
    name: str
    description: str
    description_i18n: Dict[str, str]
    func: Callable  # ← 指向 Agent.run_stream
    parameters: Dict[str, Dict[str, Any]]
    required: List[str]
    ...
```

```python
# sagents/tool/tool_manager.py
class ToolManager:
    async def run_tool_async(self, tool_name: str, ...):
        tool = self.get_tool(tool_name)
        
        if isinstance(tool, AgentToolSpec):
            # ← 特殊处理：返回流式生成器
            return self._execute_agent_tool_streaming_async(tool, ...)
        elif isinstance(tool, ToolSpec):
            return await self._execute_standard_tool_async(tool, ...)
```

### AgentToolSpec 使用场景

1. **注册 Agent 为工具**：
   ```python
   research_agent = ResearchAgent(...)
   tool_manager.register_tool(research_agent.to_tool())
   ```

2. **流式执行**：
   ```python
   # AgentToolSpec 返回的是 AsyncGenerator，需要特殊处理
   async for chunk in tool_manager.run_tool_async("ResearchAgent", ...):
       yield chunk
   ```

3. **优先级处理**：
   ```python
   # ToolManager 中的优先级
   priority_order = {
       McpToolSpec: 3, 
       AgentToolSpec: 2,  # ← Agent 工具有较高优先级
       SageMcpToolSpec: 1.5, 
       ToolSpec: 1
   }
   ```

## 移除方案

### 1. 目标架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           Tool Layer                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐ │
│  │   Basic     │  │    MCP      │  │   Fibre     │  │   (No Agent)    │ │
│  │    Tools    │  │   Tools     │  │   Tools     │  │                 │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         Agent Layer (独立)                               │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Agent Lifecycle Management (Orchestrator)                       │   │
│  │                                                                  │   │
│  │  • spawn_agent()        ← sys_spawn_agent 工具调用              │   │
│  │  • delegate_task()      ← sys_delegate_task 工具调用            │   │
│  │  • finish_task()        ← sys_finish_task 工具调用              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  Agent Implementations                                           │   │
│  │                                                                  │   │
│  │  • SimpleAgent      • TaskExecutorAgent    • ResearchAgent      │   │
│  │  • (其他业务Agent)                                               │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 2. 移除步骤

#### 步骤 1：删除 AgentToolSpec 类

**文件**：`sagents/tool/tool_schema.py`

```python
# 删除以下内容
@dataclass
class AgentToolSpec:
    name: str
    description: str
    description_i18n: Dict[str, str]
    func: Callable
    parameters: Dict[str, Dict[str, Any]]
    required: List[str]
    ...
```

**修改 `convert_spec_to_openai_format` 函数**：
```python
# 修改前
def convert_spec_to_openai_format(
    tool_spec: Union[McpToolSpec, ToolSpec, AgentToolSpec],
    ...
) -> Dict[str, Any]:
    ...

# 修改后
def convert_spec_to_openai_format(
    tool_spec: Union[McpToolSpec, ToolSpec],  # ← 移除 AgentToolSpec
    ...
) -> Dict[str, Any]:
    ...
```

#### 步骤 2：删除 AgentBase.to_tool() 方法

**文件**：`sagents/agent/agent_base.py`

```python
class AgentBase(ABC):
    # 删除整个 to_tool 方法
    # def to_tool(self) -> AgentToolSpec:
    #     ...
    
    # 保留 run_stream 方法，但不再作为工具入口
    @abstractmethod
    async def run_stream(self, session_context: SessionContext, ...) -> AsyncGenerator[...]:
        """流式处理消息"""
        ...
```

#### 步骤 3：修改 ToolManager

**文件**：`sagents/tool/tool_manager.py`

**3.1 修改导入**：
```python
# 修改前
from .tool_schema import (
    convert_spec_to_openai_format,
    ToolSpec,
    McpToolSpec,
    AgentToolSpec,  # ← 删除
    SageMcpToolSpec,
    ...
)

# 修改后
from .tool_schema import (
    convert_spec_to_openai_format,
    ToolSpec,
    McpToolSpec,
    SageMcpToolSpec,
    # AgentToolSpec,  # ← 已删除
)
```

**3.2 修改 tools 字典类型**：
```python
# 修改前
self.tools: Dict[str, Union[ToolSpec, McpToolSpec, AgentToolSpec, SageMcpToolSpec]] = {}

# 修改后
self.tools: Dict[str, Union[ToolSpec, McpToolSpec, SageMcpToolSpec]] = {}
```

**3.3 修改 register_tool 方法**：
```python
# 修改前
def register_tool(self, tool_spec: Union[ToolSpec, McpToolSpec, AgentToolSpec, SageMcpToolSpec]):
    priority_order = {McpToolSpec: 3, AgentToolSpec: 2, SageMcpToolSpec: 1.5, ToolSpec: 1}
    ...

# 修改后
def register_tool(self, tool_spec: Union[ToolSpec, McpToolSpec, SageMcpToolSpec]):  # ← 移除 AgentToolSpec
    priority_order = {McpToolSpec: 3, SageMcpToolSpec: 1.5, ToolSpec: 1}  # ← 移除 AgentToolSpec
    ...
```

**3.4 修改 list_tools_with_type 方法**：
```python
# 修改前
if isinstance(tool, McpToolSpec):
    tool_type = "mcp"
    source = f"MCP Server: {tool.server_name}"
elif isinstance(tool, AgentToolSpec):
    tool_type = "agent"
    source = "专业智能体"
elif isinstance(tool, SageMcpToolSpec):
    ...

# 修改后
if isinstance(tool, McpToolSpec):
    tool_type = "mcp"
    source = f"MCP Server: {tool.server_name}"
# elif isinstance(tool, AgentToolSpec):  # ← 删除此分支
#     tool_type = "agent"
#     source = "专业智能体"
elif isinstance(tool, SageMcpToolSpec):
    ...
```

**3.5 删除 _execute_agent_tool_streaming_async 方法**：
```python
# 删除整个方法
# async def _execute_agent_tool_streaming_async(self, tool: AgentToolSpec, ...):
#     ...
```

**3.6 修改 run_tool_async 方法**：
```python
# 修改前
if isinstance(tool, McpToolSpec):
    final_result = await self._execute_mcp_tool(tool, ...)
elif isinstance(tool, SageMcpToolSpec):
    final_result = await self._execute_standard_tool_async(tool, ...)
elif isinstance(tool, ToolSpec):
    final_result = await self._execute_standard_tool_async(tool, ...)
elif isinstance(tool, AgentToolSpec):  # ← 删除此分支
    return self._execute_agent_tool_streaming_async(tool, ...)

# 修改后
if isinstance(tool, McpToolSpec):
    final_result = await self._execute_mcp_tool(tool, ...)
elif isinstance(tool, SageMcpToolSpec):
    final_result = await self._execute_standard_tool_async(tool, ...)
elif isinstance(tool, ToolSpec):
    final_result = await self._execute_standard_tool_async(tool, ...)
# AgentToolSpec 处理已删除
```

**3.7 修改 get_tool 返回类型**：
```python
# 修改前
def get_tool(self, name: str) -> Optional[Union[ToolSpec, McpToolSpec, AgentToolSpec]]:
    ...

# 修改后
def get_tool(self, name: str) -> Optional[Union[ToolSpec, McpToolSpec]]:  # ← 移除 AgentToolSpec
    ...
```

#### 步骤 4：修改 ToolManager 中的 Agent 工具检测

**文件**：`sagents/tool/tool_manager.py`

在 `run_tool_async` 方法中，删除 Agent 工具的特殊处理：

```python
# 修改前（在 _execute_tool 中）
# 检查是否为流式响应（AgentToolSpec）
if hasattr(tool_response, '__iter__') and not isinstance(tool_response, (str, bytes)):
    tool_spec = tool_manager.get_tool(tool_name) if tool_manager else None
    is_agent_tool = isinstance(tool_spec, AgentToolSpec)  # ← 删除此检查
    
    if is_agent_tool:
        # 专业agent工具：直接返回原始结果
        ...

# 修改后
# 所有工具统一处理，不再区分 Agent 工具
if hasattr(tool_response, '__iter__') and not isinstance(tool_response, (str, bytes)):
    # 统一处理流式响应
    ...
```

#### 步骤 5：修改 AgentBase._execute_tool 方法

**文件**：`sagents/agent/agent_base.py`

```python
# 修改前
async def _execute_tool(self, ...):
    ...
    tool_response = await tool_manager.run_tool_async(...)
    
    # 检查是否为流式响应（AgentToolSpec）
    if hasattr(tool_response, '__iter__') and not isinstance(tool_response, (str, bytes)):
        tool_spec = tool_manager.get_tool(tool_name) if tool_manager else None
        is_agent_tool = isinstance(tool_spec, AgentToolSpec)  # ← 删除此检查
        ...

# 修改后
async def _execute_tool(self, ...):
    ...
    tool_response = await tool_manager.run_tool_async(...)
    
    # 所有工具统一处理，不再特殊判断 AgentToolSpec
    if hasattr(tool_response, '__iter__') and not isinstance(tool_response, (str, bytes)):
        # 统一处理流式响应
        async for chunk in tool_response:
            yield chunk
```

#### 步骤 6：修改 ToolManager 的导入导出

**文件**：`sagents/tool/__init__.py`

```python
# 修改前
if TYPE_CHECKING:
    from .tool_schema import AgentToolSpec

def __getattr__(name):
    ...
    elif name == "AgentToolSpec":
        from .tool_schema import AgentToolSpec
        return AgentToolSpec
    ...

__all__ = [
    'ToolManager',
    'ToolProxy',
    'AgentToolSpec',  # ← 删除
    'get_tool_manager',
]

# 修改后
# 删除所有 AgentToolSpec 相关代码

def __getattr__(name):
    if name == "ToolManager":
        from .tool_manager import ToolManager
        return ToolManager
    elif name == "ToolProxy":
        from .tool_proxy import ToolProxy
        return ToolProxy
    elif name == "get_tool_manager":
        from .tool_manager import get_tool_manager
        return get_tool_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'ToolManager',
    'ToolProxy',
    # 'AgentToolSpec',  # ← 已删除
    'get_tool_manager',
]
```

#### 步骤 7：更新文档

**文件**：`docs/API_REFERENCE.md`, `docs/ARCHITECTURE.md`, `docs/ARCHITECTURE_CN.md`

删除所有关于 `AgentToolSpec` 的文档内容。

#### 步骤 8：更新示例代码

**文件**：`docs/TOOL_DEVELOPMENT.md`, `docs/TOOL_DEVELOPMENT_CN.md`

删除以下示例：
```python
# 删除此示例
tool_manager.register_tool(research_agent.to_tool())
```

### 3. 替代方案

移除 "Agent as Tool" 后，使用 Fibre 架构来管理子 Agent：

```python
# 父 Agent 使用 sys_spawn_agent 创建子 Agent
async def parent_agent_run(self, session_context: SessionContext, ...):
    # 1. 创建子 Agent
    spawn_result = await tool_manager.run_tool_async(
        'sys_spawn_agent',
        session_context=session_context,
        name="ResearchExpert",
        description="研究专家",
        system_prompt="你是一个研究专家..."
    )
    
    # 2. 分配任务给子 Agent
    delegate_result = await tool_manager.run_tool_async(
        'sys_delegate_task',
        session_context=session_context,
        tasks=[{
            'agent_id': 'research_expert_1',
            'task_name': 'research_task',
            'original_task': '研究某个主题',
            'content': '请研究...'
        }]
    )
    
    # 3. 子 Agent 完成后通过 sys_finish_task 返回结果
    # 结果会自动传递给父 Agent
```

### 4. 需要修改的文件清单

| 文件路径 | 修改内容 |
|---------|---------|
| `sagents/tool/tool_schema.py` | 删除 `AgentToolSpec` 类，修改 `convert_spec_to_openai_format` |
| `sagents/tool/tool_manager.py` | 删除所有 `AgentToolSpec` 相关逻辑，删除 `_execute_agent_tool_streaming_async` |
| `sagents/tool/__init__.py` | 删除 `AgentToolSpec` 导出 |
| `sagents/agent/agent_base.py` | 删除 `to_tool()` 方法，修改 `_execute_tool` 中的 Agent 工具检测 |
| `docs/API_REFERENCE.md` | 删除 `AgentToolSpec` 文档 |
| `docs/ARCHITECTURE.md` | 更新架构图和说明 |
| `docs/ARCHITECTURE_CN.md` | 更新架构图和说明 |
| `docs/TOOL_DEVELOPMENT.md` | 删除 Agent as Tool 示例 |
| `docs/TOOL_DEVELOPMENT_CN.md` | 删除 Agent as Tool 示例 |

### 5. 迁移检查清单

- [ ] 删除 `AgentToolSpec` 类
- [ ] 删除 `AgentBase.to_tool()` 方法
- [ ] 修改 `ToolManager` 移除 AgentToolSpec 处理
- [ ] 删除 `_execute_agent_tool_streaming_async` 方法
- [ ] 修改 `ToolManager.list_tools_with_type` 移除 agent 类型
- [ ] 修改 `ToolManager.register_tool` 移除 AgentToolSpec 优先级
- [ ] 修改 `AgentBase._execute_tool` 移除 Agent 工具检测
- [ ] 修改 `sagents/tool/__init__.py` 移除导出
- [ ] 更新所有相关文档
- [ ] 运行测试确保无回归

## 影响分析

### 受影响的功能

| 功能 | 影响 | 替代方案 |
|-----|------|---------|
| `agent.to_tool()` | 完全移除 | 使用 `sys_spawn_agent` |
| Agent 流式执行 | 移除特殊处理 | 统一使用 Fibre 架构 |
| Agent 工具优先级 | 移除 | 不再需要 |

### 不受影响的功能

- 普通工具（`ToolSpec`）的执行
- MCP 工具（`McpToolSpec`, `SageMcpToolSpec`）的执行
- Agent 本身的 `run_stream` 方法（只是不再作为工具入口）
- Fibre 架构（`sys_spawn_agent`, `sys_delegate_task`, `sys_finish_task`）

## 回滚方案

如果需要回滚，可以通过 Git 恢复删除的代码。主要恢复点：

1. `AgentToolSpec` 类定义
2. `AgentBase.to_tool()` 方法
3. `ToolManager` 中的 Agent 工具处理逻辑

## 总结

移除 "Agent as Tool" 设计后：

1. **架构更清晰**：Agent 和 Tool 的职责分离
2. **维护更简单**：ToolManager 不再需要特殊处理 Agent 工具
3. **统一使用 Fibre**：所有子 Agent 管理通过 Fibre 工具完成
4. **减少概念负担**：开发者不需要理解 AgentToolSpec 的特殊性
