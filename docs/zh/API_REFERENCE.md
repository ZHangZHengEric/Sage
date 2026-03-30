---
layout: default
title: API 参考
nav_order: 9
description: "Sage多智能体框架完整API参考文档"
lang: zh
ref: api-reference
---

{% include lang_switcher.html %}

{: .note }
> 需要英文版本？请查看 [API Reference](../en/API_REFERENCE.md)

{: .warning }
> 本页恢复自历史 v0.9 文档，描述的是较早期的运行时 Python API。当前仓库里的服务端 HTTP 接口，请优先查看 [HTTP API 参考](HTTP_API_REFERENCE.md)。

## 目录
{: .no_toc .text-delta }

1. TOC
{:toc}

# 📖 API 参考文档

本文档提供 Sage 多智能体框架的全面 API 文档。

## 📋 目录

- [核心组件](#-核心组件)
- [智能体类](#-智能体类)
- [工具系统](#-工具系统)
- [配置](#-配置)
- [工具类](#-工具类)
- [异常处理](#-异常处理)
- [类型和接口](#-类型和接口)

## 🎯 核心组件

### AgentController

多智能体工作流的主要协调器。

```python
class AgentController:
    """
    智能体控制器
    
    负责协调多个智能体协同工作，管理任务执行流程，
    包括任务分析、规划、执行、观察和总结等阶段。
    """
```

#### 构造函数

```python
def __init__(self, model: Any, model_config: Dict[str, Any], system_prefix: str = ""):
    """
    初始化智能体控制器
    
    Args:
        model: 语言模型实例 (如 OpenAI 客户端)
        model_config: 模型配置参数字典
            - model: str - 模型名称 (如 "gpt-4")
            - temperature: float - 采样温度 (0-2)
            - max_tokens: int - 每次响应的最大token数
            - timeout: int - 请求超时时间(秒)
        system_prefix: 系统前缀提示 (可选)
    
    Example:
        >>> from openai import OpenAI
        >>> model = OpenAI(api_key="sk-...")
        >>> config = {"model": "gpt-4", "temperature": 0.7}
        >>> controller = AgentController(model, config)
    """
```

#### run()

```python
def run(self, 
        input_messages: List[Dict[str, Any]], 
        tool_manager: Optional[Any] = None, 
        session_id: Optional[str] = None, 
        deep_thinking: bool = True,
        summary: bool = True,
        max_loop_count: int = 10,
        deep_research: bool = True) -> Dict[str, Any]:
    """
    执行智能体工作流（非流式版本）
    
    Args:
        input_messages: 输入消息字典列表
            格式: [{"role": "user|assistant|tool", "content": str, "type": str}]
        tool_manager: 工具管理器实例 (可选)
        session_id: 会话标识符 (可选)
        deep_thinking: 是否进行任务分析 (默认: True)
        summary: 是否生成任务总结 (默认: True)
        max_loop_count: 最大规划-执行-观察循环次数 (默认: 10)
        deep_research: 是否进行深度研究（完整流程）vs直接执行 (默认: True)
    
    Returns:
        Dict[str, Any]: 包含以下字段的结果字典:
            - all_messages: 所有消息列表
            - new_messages: 新生成的消息列表
            - final_output: 最终响应消息
            - session_id: 会话ID
    
    Example:
        >>> messages = [{"role": "user", "content": "分析AI趋势", "type": "normal"}]
        >>> result = controller.run(messages, tool_manager, deep_thinking=True, deep_research=True)
        >>> print(result['final_output']['content'])
    """
```

#### run_stream()

```python
def run_stream(self, 
               input_messages: List[Dict[str, Any]], 
               tool_manager: Optional[Any] = None, 
               session_id: Optional[str] = None, 
               deep_thinking: bool = True, 
               summary: bool = True,
               max_loop_count: int = 10,
               deep_research: bool = True) -> Generator[List[Dict[str, Any]], None, None]:
    """
    执行智能体工作流并流式输出结果
    
    Args:
        input_messages: 输入消息字典列表
        tool_manager: 工具管理器实例 (可选)
        session_id: 会话标识符 (可选)
        deep_thinking: 是否进行任务分析 (默认: True)
        summary: 是否生成任务总结 (默认: True)
        max_loop_count: 最大循环次数 (默认: 10)
        deep_research: 是否进行深度研究（完整流程）(默认: True)
    
    Yields:
        List[Dict[str, Any]]: 自上次yield以来的新消息字典列表，每个消息包含：
        - message_id: 消息的唯一标识符
        - 其他标准消息字段（role、content、type等）
    
    Example:
        >>> for chunk in controller.run_stream(messages, tool_manager):
        ...     for message in chunk:
        ...         print(f"{message['role']}: {message['content']}")
    """
```

### ToolManager

管理工具注册、发现和执行。

```python
class ToolManager:
    """工具管理器"""
    
    def __init__(self, is_auto_discover=True):
        """
        初始化工具管理器
        
        Args:
            is_auto_discover: 是否自动发现工具 (默认: True)
        """
```

#### discover_tools_from_path()

```python
def discover_tools_from_path(self, path: Optional[str] = None) -> None:
    """
    自动导入模块并注册使用 tool() 装饰器的函数
    
    Args:
        path: 可选的自定义扫描路径
    
    Example:
        >>> tool_manager.discover_tools_from_path()
    """
```

#### run_tool()

```python
def run_tool(self, tool_name: str, **kwargs) -> Any:
    """
    执行指定的工具
    
    Args:
        tool_name: 工具名称
        **kwargs: 工具参数
    
    Returns:
        Any: 工具执行结果
    
    Example:
        >>> result = tool_manager.run_tool('calculate', expression="2+3")
    """
```

#### list_tools_simplified()

```python
def list_tools_simplified(self) -> List[Dict[str, str]]:
    """
    获取简化的工具列表
    
    Returns:
        List[Dict[str, str]]: 包含工具名称和描述的字典列表
    """
```

## 🤖 智能体类

### AgentBase

系统中所有智能体的基类。

```python
class AgentBase:
    """
    所有智能体的抽象基类
    
    提供智能体实现的通用功能和接口。
    所有具体的智能体都必须继承此类。
    """
```

#### run()

```python
def run(self, messages: List[Dict], tool_manager=None, **kwargs) -> List[Dict]:
    """
    执行智能体逻辑
    
    Args:
        messages: 对话历史
        tool_manager: 可用工具 (可选)
        **kwargs: 智能体特定参数
    
    Returns:
        List[Dict]: 生成的消息列表
    
    Note:
        此方法必须由子类实现
    """
```

### TaskAnalysisAgent

分析和分解复杂任务。

```python
class TaskAnalysisAgent(AgentBase):
    """任务分析智能体"""
```

### PlanningAgent

为任务创建执行计划。

```python
class PlanningAgent(AgentBase):
    """规划智能体"""
```

### ExecutorAgent

使用可用工具执行计划。

```python
class ExecutorAgent(AgentBase):
    """执行智能体"""
```

### ObservationAgent

观察和评估执行结果。

```python
class ObservationAgent(AgentBase):
    """观察智能体"""
```

### TaskSummaryAgent

生成已完成任务的综合总结。

```python
class TaskSummaryAgent(AgentBase):
    """任务总结智能体"""
```

### DirectExecutorAgent

提供直接执行，无需完整的多智能体流水线。

```python
class DirectExecutorAgent(AgentBase):
    """直接执行智能体"""
```

## 🛠️ 工具系统

### 工具装饰器

用于创建自定义工具的函数装饰器。

```python
from sagents.tool.tool_base import tool

class CustomTool:
    @tool()
    def my_function(self, param: str) -> dict:
        return {"result": param}
```

#### @tool() 装饰器

```python
from sagents.tool.tool_base import tool

class MyTool:
    @tool()
    def my_function(self, param: str) -> dict:
        return {"result": param}
```

### ToolSpec

工具规范数据类。

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Dict[str, Any]]
    required: List[str]
```

### McpToolSpec

MCP（模型上下文协议）工具规范。

```python
@dataclass
class McpToolSpec:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Dict[str, Any]]
    required: List[str]
    server_name: str
    server_params: Union[StdioServerParameters, SseServerParameters]
```

## ⚙️ 配置

### Settings

全局配置管理。

```python
@dataclass
class Settings:
    model: ModelConfig = field(default_factory=ModelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    tool: ToolConfig = field(default_factory=ToolConfig)
    debug: bool = False
    environment: str = "development"
```

#### get_settings()

```python
def get_settings() -> Settings:
    """
    获取全局配置实例
    
    Returns:
        Settings: 配置实例
    """
```

### ModelConfig

模型特定配置。

```python
@dataclass
class ModelConfig:
    model_name: str = "gpt-3.5-turbo"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 60
```

### AgentConfig

智能体特定配置。

```python
@dataclass  
class AgentConfig:
    max_loop_count: int = 10
    enable_deep_thinking: bool = True
    enable_summary: bool = True
    task_timeout: int = 300
```

### ToolConfig

工具特定配置。

```python
@dataclass
class ToolConfig:
    tool_timeout: int = 30
    max_concurrent_tools: int = 5
```

## 🔧 工具类

### Logger

结构化日志工具。

```python
from agents.utils.logger import logger

# 使用方法
logger.info("信息消息")
logger.error("错误消息")
logger.debug("调试消息")
```

## ⚠️ 异常处理

### SageException

框架的基础异常类。

```python
class SageException(Exception):
    """Sage框架基础异常类"""
    pass
```

### ToolExecutionError

工具执行特定错误。

```python
class ToolExecutionError(SageException):
    """工具执行错误"""
    def __init__(self, message: str, tool_name: str = None):
        super().__init__(message)
        self.tool_name = tool_name
```

### AgentTimeoutError

智能体超时错误。

```python
class AgentTimeoutError(SageException):
    """智能体超时错误"""
    pass
```

### 重试机制

```python
from agents.utils.exceptions import with_retry, exponential_backoff

@with_retry(exponential_backoff(max_attempts=3, base_delay=1.0, max_delay=60.0))
def risky_function():
    """带重试逻辑的函数"""
    pass
```

## 📝 类型和接口

### 消息格式

整个系统中使用的标准消息格式。

```python
{
    "role": str,           # "user" | "assistant" | "tool" | "system"
    "content": str,        # 消息内容
    "type": str,           # "normal" | "tool_call" | "tool_result" | "thinking" | "final_answer"
    "message_id": str,     # 唯一消息标识符 (可选)
    "tool_calls": List,    # 工具调用信息 (可选)
    "tool_call_id": str,   # 工具调用标识符 (可选)
}
```

### 工具调用格式

工具调用和结果的格式。

```python
# 工具调用
{
    "id": str,
    "type": "function",
    "function": {
        "name": str,
        "arguments": str  # JSON字符串
    }
}

# 工具结果
{
    "tool_call_id": str,
    "role": "tool",
    "content": str
}
```

## 📊 常量

### 默认值

```python
# AgentController 默认值
DEFAULT_MAX_LOOP_COUNT = 10
DEFAULT_MESSAGE_LIMIT = 10000

# 工作空间模板
WORKSPACE_TEMPLATE = "/tmp/sage/{session_id}"
```

### 消息类型

```python
MESSAGE_TYPES = [
    "normal",       # 常规对话
    "tool_call",    # 工具执行请求
    "tool_result",  # 工具执行结果
    "thinking",     # 内部推理
    "final_answer", # 最终响应
    "task_analysis",# 任务分析结果
    "planning",     # 规划结果
    "observation",  # 观察结果
    "summary"       # 任务总结
]
```

此API参考文档为Sage多智能体框架中的所有公共接口提供了全面的文档。有关更多示例和使用模式，请参阅[示例文档](EXAMPLES_CN.md)。 
