---
layout: default
title: API Reference
nav_order: 8
description: "Complete API reference for the Sage Multi-Agent Framework"
---

{: .note }
> Looking for the Chinese version? Check out [API 参考](API_REFERENCE_CN.html)

## Table of Contents
{: .no_toc .text-delta }

1. TOC
{:toc}

# 📖 API Reference

This document provides comprehensive API documentation for Sage Multi-Agent Framework.

## 📋 Table of Contents

- [Core Components](#-core-components)
- [Agent Classes](#-agent-classes)
- [Tool System](#-tool-system)
- [Configuration](#-configuration)
- [Utilities](#-utilities)
- [Exception Handling](#-exception-handling)
- [Types and Interfaces](#-types-and-interfaces)

## 🎯 Core Components

### AgentController

The main orchestrator for multi-agent workflows.

```python
class AgentController:
    """
    智能体控制器
    
    负责协调多个智能体协同工作，管理任务执行流程，
    包括任务分析、规划、执行、观察和总结等阶段。
    """
```

#### Constructor

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
        >>> messages = [{"role": "user", "content": "Analyze AI trends", "type": "normal"}]
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

### ComponentManager

Manages system components initialization and configuration.

```python
class ComponentManager:
    """
    Manages component initialization and lifecycle
    
    Handles initialization of models, agents, and tools with
    proper error handling and retry logic.
    """
```

#### initialize_model()

```python
def initialize_model(self, api_key: str, model_name: str, base_url: str = None) -> OpenAI:
    """
    Initialize LLM model client
    
    Args:
        api_key: API key for the model provider
        model_name: Name of the model to use
        base_url: Custom API base URL (optional)
    
    Returns:
        OpenAI: Configured model client
    
    Raises:
        ModelInitializationError: If model initialization fails
        AuthenticationError: If API key is invalid
    
    Example:
        >>> manager = ComponentManager()
        >>> model = manager.initialize_model("sk-...", "gpt-4")
    """
```

#### initialize_tool_manager()

```python
def initialize_tool_manager(self, tools_folders: List[str] = None) -> ToolManager:
    """
    Initialize tool manager with tool discovery
    
    Args:
        tools_folders: List of directories to scan for tools
    
    Returns:
        ToolManager: Configured tool manager
    
    Example:
        >>> manager = ComponentManager()
        >>> tool_manager = manager.initialize_tool_manager(["./custom_tools"])
    """
```

## 🤖 Agent Classes

### AgentBase

Base class for all agents in the system.

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

#### run_stream()

```python
def run_stream(self, messages: List[Dict], tool_manager=None, **kwargs) -> Generator:
    """
    Execute agent logic with streaming
    
    Args:
        messages: Conversation history
        tool_manager: Available tools (optional)
        **kwargs: Agent-specific parameters
    
    Yields:
        Dict: Individual message chunks
    """
```

### TaskAnalysisAgent

Analyzes and decomposes complex tasks.

```python
class TaskAnalysisAgent(AgentBase):
    """任务分析智能体"""
```

### PlanningAgent

Creates execution plans for tasks.

```python
class PlanningAgent(AgentBase):
    """规划智能体"""
```

### ExecutorAgent

Executes plans using available tools.

```python
class ExecutorAgent(AgentBase):
    """执行智能体"""
```

### ObservationAgent

Observes and evaluates execution results.

```python
class ObservationAgent(AgentBase):
    """观察智能体"""
```

### TaskSummaryAgent

Generates comprehensive summaries of completed tasks.

```python
class TaskSummaryAgent(AgentBase):
    """任务总结智能体"""
```

### DirectExecutorAgent

Provides direct execution without full multi-agent pipeline.

```python
class DirectExecutorAgent(AgentBase):
    """直接执行智能体"""
```

## 🛠️ Tool System

### ToolManager

Manages tool registration, discovery, and execution.

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

#### register_tool_class()

```python
def register_tool_class(self, tool_class: Type[ToolBase]) -> bool:
    """
    从ToolBase子类注册所有工具
    
    Args:
        tool_class: ToolBase的子类
    
    Returns:
        bool: 注册是否成功
    
    Example:
        >>> from agents.tool.calculation_tool import Calculator
        >>> tool_manager.register_tool_class(Calculator)
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

### ToolBase

Base class for creating custom tools.

```python
class ToolBase:
    """工具基类"""
    
    def __init__(self):
        """初始化工具实例"""
```

#### @tool() decorator

```python
@classmethod
def tool(cls):
    """
    用于注册工具方法的装饰器工厂
    
    Example:
        >>> class MyTool(ToolBase):
        ...     @ToolBase.tool()
        ...     def my_function(self, param: str) -> dict:
        ...         '''Function description'''
        ...         return {"result": param}
    """
```

### ToolSpec

Tool specification data class.

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

MCP (Model Context Protocol) tool specification.

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

## ⚙️ Configuration

### Settings

Global configuration management.

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

Model-specific configuration.

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

Agent-specific configuration.

```python
@dataclass  
class AgentConfig:
    max_loop_count: int = 10
    enable_deep_thinking: bool = True
    enable_summary: bool = True
    task_timeout: int = 300
```

### ToolConfig

Tool-specific configuration.

```python
@dataclass
class ToolConfig:
    tool_timeout: int = 30
    max_concurrent_tools: int = 5
```

## 🔧 Utilities

### Logger

Structured logging utilities.

```python
from agents.utils.logger import logger

# Usage
logger.info("Information message")
logger.error("Error message")
logger.debug("Debug message")
```

## ⚠️ Exception Handling

### SageException

Base exception class for the framework.

```python
class SageException(Exception):
    """Sage框架基础异常类"""
    pass
```

### ToolExecutionError

Tool execution specific errors.

```python
class ToolExecutionError(SageException):
    """工具执行错误"""
    def __init__(self, message: str, tool_name: str = None):
        super().__init__(message)
        self.tool_name = tool_name
```

### AgentTimeoutError

Agent timeout errors.

```python
class AgentTimeoutError(SageException):
    """智能体超时错误"""
    pass
```

### Retry Mechanisms

```python
from agents.utils.exceptions import with_retry, exponential_backoff

@with_retry(exponential_backoff(max_attempts=3, base_delay=1.0, max_delay=60.0))
def risky_function():
    """Function with retry logic"""
    pass
```

## 📝 Types and Interfaces

### Message Format

Standard message format used throughout the system.

```python
{
    "role": str,           # "user" | "assistant" | "tool" | "system"
    "content": str,        # Message content
    "type": str,           # "normal" | "tool_call" | "tool_result" | "thinking" | "final_answer"
    "message_id": str,     # Unique message identifier (optional)
    "show_content": str,   # Content for display (optional)
    "tool_calls": List,    # Tool call information (optional)
    "tool_call_id": str,   # Tool call identifier (optional)
}
```

### Tool Call Format

Format for tool calls and results.

```python
# Tool Call
{
    "id": str,
    "type": "function",
    "function": {
        "name": str,
        "arguments": str  # JSON string
    }
}

# Tool Result
{
    "tool_call_id": str,
    "role": "tool",
    "content": str
}
```

## 📊 Constants

### Default Values

```python
# AgentController defaults
DEFAULT_MAX_LOOP_COUNT = 10
DEFAULT_MESSAGE_LIMIT = 10000

# Workspace template
WORKSPACE_TEMPLATE = "/tmp/sage/{session_id}"
```

### Message Types

```python
MESSAGE_TYPES = [
    "normal",       # Regular conversation
    "tool_call",    # Tool execution request
    "tool_result",  # Tool execution result
    "thinking",     # Internal reasoning
    "final_answer", # Final response
    "task_analysis",# Task analysis result
    "planning",     # Planning result
    "observation",  # Observation result
    "summary"       # Task summary
]
```

This API reference provides comprehensive documentation for all public interfaces in the Sage Multi-Agent Framework. For more examples and usage patterns, see the [Examples documentation](EXAMPLES.md). 