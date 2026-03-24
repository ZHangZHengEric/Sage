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

# 📚 Sage API Reference

Complete API reference for Sage Multi-Agent Framework v0.9.

## 🚀 Core Classes

### AgentController

The main orchestration class for multi-agent workflows.

```python
from agents.agent.agent_controller import AgentController

controller = AgentController(model, model_config, system_prefix="")
```

#### Constructor Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `model` | `Any` | OpenAI-compatible model instance |
| `model_config` | `Dict[str, Any]` | Model configuration parameters |
| `system_prefix` | `str` | Optional system prefix for all agents |

#### Methods

##### `run()`

Execute a complete multi-agent workflow (non-streaming).

```python
def run(self, 
        input_messages: List[Dict[str, Any]], 
        tool_manager: Optional[Any] = None, 
        session_id: Optional[str] = None, 
        deep_thinking: bool = True,
        summary: bool = True,
        max_loop_count: int = 10,
        deep_research: bool = True,
        system_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `input_messages` | `List[Dict[str, Any]]` | Required | Input conversation messages |
| `tool_manager` | `ToolManager` | `None` | Tool manager instance |
| `session_id` | `str` | `None` | Optional session identifier |
| `deep_thinking` | `bool` | `True` | Enable task analysis phase |
| `summary` | `bool` | `True` | Generate final summary |
| `max_loop_count` | `int` | `10` | Maximum planning-execution loops |
| `deep_research` | `bool` | `True` | Enable full 6-agent pipeline |
| `system_context` | `Dict[str, Any]` | `None` | **NEW** Unified system context |

**Returns:**
```python
{
    'all_messages': List[Dict[str, Any]],     # Complete conversation
    'new_messages': List[Dict[str, Any]],     # New messages from agents
    'final_output': Dict[str, Any],           # Final result message
    'session_id': str,                        # Session identifier
    'token_usage': Dict[str, Any],            # Token usage statistics
    'execution_time': float                   # Total execution time
}
```

##### `run_stream()`

Execute a multi-agent workflow with real-time streaming.

```python
def run_stream(self, 
               input_messages: List[Dict[str, Any]], 
               tool_manager: Optional[Any] = None, 
               session_id: Optional[str] = None, 
               deep_thinking: bool = True, 
               summary: bool = True,
               max_loop_count: int = 10,
               deep_research: bool = True,
               system_context: Optional[Dict[str, Any]] = None) -> Generator[List[Dict[str, Any]], None, None]:
```

**Parameters:** Same as `run()` method

**Yields:**
```python
List[Dict[str, Any]]  # Message chunks for real-time processing
```

Each message chunk contains:
```python
{
    'message_id': str,           # Unique message identifier
    'role': str,                 # Agent role ('assistant', 'user', etc.)
    'content': str,              # Message content
    'type': str,                 # Message type (e.g., 'task_analysis', 'final_answer')
    'usage': Dict[str, Any]      # Token usage for this message (optional)
}
```

## 🔧 System Context API

### Overview

The `system_context` parameter (new in v0.9) provides unified context management across all agents. It allows you to pass runtime information that will be consistently available to all agents in the workflow.

### Usage

```python
system_context = {
    # Standard fields (automatically added by AgentController)
    "session_id": "unique_session_id",
    "current_time": "2024-01-15 Monday 14:30:00", 
    "file_workspace": "/tmp/sage/session_id",
    
    # Custom fields (user-provided)
    "project_context": "AI research project on neural networks",
    "constraints": ["time_limit: 2 hours", "budget: $100", "resources: limited"],
    "preferences": {
        "output_format": "detailed_report",
        "language": "english",
        "technical_level": "expert"
    },
    "domain_knowledge": {
        "field": "machine_learning",
        "specialization": "deep_learning",
        "experience_level": "senior"
    }
}

result = controller.run(
    messages,
    tool_manager,
    system_context=system_context
)
```

### Standard Context Fields

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | Unique session identifier |
| `current_time` | `str` | Current timestamp in readable format |
| `file_workspace` | `str` | Working directory for file operations |

### Custom Context Fields

You can add any custom fields to provide context-specific information:

```python
system_context = {
    # Task-specific context
    "task_priority": "high",
    "deadline": "2024-01-20",
    "target_audience": "technical_team",
    
    # Project context
    "project_name": "AI Assistant Development",
    "project_phase": "research",
    "stakeholders": ["engineering", "product", "research"],
    
    # Resource constraints
    "computational_budget": "limited",
    "time_constraints": "strict",
    "quality_requirements": "high",
    
    # User preferences
    "communication_style": "technical",
    "detail_level": "comprehensive",
    "format_preference": "structured"
}
```

## 🤖 Agent Classes

### Task Analysis Agent

Analyzes and understands user requests with deep context awareness.

```python
from agents.agent.task_analysis_agent import TaskAnalysisAgent

agent = TaskAnalysisAgent(model, model_config, system_prefix="")
```

**Key Features:**
- Deep task understanding with context awareness
- Unified system prompt management via `SYSTEM_PREFIX_DEFAULT`
- Enhanced reasoning capabilities

### Task Decompose Agent (NEW in v0.9)

Intelligently breaks down complex tasks into manageable subtasks.

```python
from agents.agent.task_decompose_agent import TaskDecomposeAgent

agent = TaskDecomposeAgent(model, model_config, system_prefix="")
```

**Key Features:**
- Intelligent task breakdown
- Dependency analysis and mapping
- Parallel execution planning
- Integration with planning agent

### Planning Agent

Creates strategic execution plans with optimal tool selection.

```python
from agents.agent.planning_agent import PlanningAgent

agent = PlanningAgent(model, model_config, system_prefix="")
```

**Key Features:**
- Strategic decomposition based on task decomposition
- Dependency management
- Optimal tool selection
- Resource allocation planning

### Executor Agent

Executes tasks using available tools and resources.

```python
from agents.agent.executor_agent import ExecutorAgent

agent = ExecutorAgent(model, model_config, system_prefix="")
```

**Key Features:**
- Intelligent tool execution
- Error recovery and retry mechanisms
- Parallel processing capabilities
- Resource optimization

### Observation Agent

Monitors execution progress and assesses completion status.

```python
from agents.agent.observation_agent import ObservationAgent

agent = ObservationAgent(model, model_config, system_prefix="")
```

**Key Features:**
- Advanced progress monitoring
- Completion detection
- Quality assessment
- Feedback generation

### Summary Agent

Synthesizes results into comprehensive summaries.

```python
from agents.agent.task_summary_agent import TaskSummaryAgent

agent = TaskSummaryAgent(model, model_config, system_prefix="")
```

**Key Features:**
- Comprehensive result synthesis
- Structured output generation
- Actionable insights
- Multi-format support

## 🛠️ Tool Management

### ToolManager

Manages tool discovery, registration, and execution.

```python
from agents.tool.tool_manager import ToolManager

tool_manager = ToolManager(is_auto_discover=True)
```

#### Methods

##### `register_tool()`

Register a single tool.

```python
def register_tool(self, tool_spec: Union[ToolSpec, McpToolSpec, AgentToolSpec]) -> bool:
```

##### `discover_tools_from_path()`

Auto-import modules and register functions decorated with tool().

```python
def discover_tools_from_path(self, path: Optional[str] = None) -> None:
```

##### `run_tool()`

Execute a tool by name.

```python
def run_tool(self, 
             tool_name: str, 
             messages: list, 
             session_id: str, 
             **kwargs) -> Any:
```

##### `list_tools()`

Get all available tools with metadata.

```python
def list_tools(self) -> List[Dict[str, Any]]:
```

##### `get_openai_tools()`

Get tool specifications in OpenAI-compatible format.

```python
def get_openai_tools(self) -> List[Dict[str, Any]]:
```

## 🔧 Tool Development

### Tool Decorator

Function decorator for creating custom tools without inheritance.

```python
from sagents.tool.tool_base import tool

class CustomTool:
    @tool()
    def my_tool(self, param1: str, param2: int = 10) -> Dict[str, Any]:
        return {"result": f"Processed {param1} with {param2}"}
```

### Tool Specifications

#### ToolSpec

Standard tool specification for local functions.

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any]
    required: List[str]
```

#### McpToolSpec

MCP (Model Context Protocol) server tool specification.

```python
@dataclass
class McpToolSpec:
    name: str
    description: str
    func: None  # Not used for MCP tools
    parameters: Dict[str, Any]
    required: List[str]
    server_name: str
    server_params: Union[StdioServerParameters, SseServerParameters]
```

#### AgentToolSpec

Agent-based tool specification for delegating to other agents.

```python
@dataclass
class AgentToolSpec:
    name: str
    description: str
    func: Callable
    parameters: Dict[str, Any]
    required: List[str]
```

## 📊 Token Tracking & Analytics

### Get Token Statistics

```python
# Get comprehensive token statistics
stats = controller.get_comprehensive_token_stats()

# Example output
{
    'total_tokens': 1500,
    'total_input_tokens': 800,
    'total_output_tokens': 700,
    'total_cached_tokens': 200,
    'total_reasoning_tokens': 300,
    'estimated_cost': 0.025,
    'agent_breakdown': {
        'TaskAnalysisAgent': {'tokens': 300, 'cost': 0.005},
        'TaskDecomposeAgent': {'tokens': 200, 'cost': 0.003},
        'PlanningAgent': {'tokens': 250, 'cost': 0.004},
        # ... other agents
    },
    'execution_time': 15.5,
    'efficiency_score': 0.92
}
```

### Print Token Statistics

```python
# Print detailed token usage report
controller.print_comprehensive_token_stats()
```

## 🔄 Execution Modes

### Deep Research Mode

Full 6-agent pipeline with comprehensive analysis:

```python
result = controller.run(
    messages,
    tool_manager,
    deep_thinking=True,     # Enable task analysis
    deep_research=True,     # Full pipeline: Analysis → Decompose → Plan → Execute → Observe → Summarize
    summary=True,           # Generate final summary
    system_context=context
)
```

**Agent Flow:**
1. Task Analysis Agent
2. Task Decompose Agent  
3. Planning Agent
4. Executor Agent
5. Observation Agent (with loop back to Planning if needed)
6. Summary Agent

### Standard Mode

Simplified workflow without task decomposition:

```python
result = controller.run(
    messages,
    tool_manager,
    deep_thinking=True,     # Enable task analysis
    deep_research=False,    # Skip decomposition: Analysis → Plan → Execute → Observe → Summarize
    summary=True,
    system_context=context
)
```

**Agent Flow:**
1. Task Analysis Agent
2. Planning Agent
3. Executor Agent  
4. Observation Agent (with loop back to Planning if needed)
5. Summary Agent

### Rapid Mode

Direct execution for maximum speed:

```python
result = controller.run(
    messages,
    tool_manager,
    deep_thinking=False,    # Skip task analysis
    deep_research=False,    # Direct execution only
    system_context=context
)
```

**Agent Flow:**
1. Direct Executor Agent (bypasses full pipeline)

## 🔌 MCP Integration

### Server Parameters

#### StdioServerParameters

For process-based MCP servers:

```python
from mcp import StdioServerParameters

server_params = StdioServerParameters(
    command="python",
    args=["server.py", "--port", "8001"],
    env={"API_KEY": "your_key"}
)
```

#### SseServerParameters

For HTTP-based MCP servers:

```python
from sagents.tool.tool_schema import SseServerParameters

server_params = SseServerParameters(
    url="https://your-mcp-server.com/sse"
)
```

### Register MCP Server

```python
# Automatic registration from config
tool_manager = ToolManager()  # Auto-discovers from mcp_servers/mcp_setting.json

# Manual registration
await tool_manager.register_mcp_server("weather_server", {
    "command": "python weather_server.py",
    "args": ["--api-key", "your_key"],
    "env": {"DEBUG": "true"}
})
```

## 🔍 Error Handling

### Exception Types

```python
from agents.utils.exceptions import (
    SageException,           # Base exception
    ToolExecutionError,      # Tool execution failures
    AgentTimeoutError,       # Agent timeout errors
    ValidationError          # Input validation errors
)
```

### Retry Mechanisms

```python
from agents.utils.exceptions import with_retry, exponential_backoff

@with_retry(exponential_backoff(max_attempts=3, base_delay=1.0))
def robust_execution():
    return controller.run(messages, tool_manager)
```

## 🎛️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SAGE_DEBUG` | Enable debug logging | `False` |
| `SAGE_MAX_LOOP_COUNT` | Maximum agent loops | `10` |
| `OPENAI_API_KEY` | OpenAI API key | `None` |
| `SAGE_TOOL_TIMEOUT` | Tool execution timeout | `30` |

### Runtime Configuration

```python
from agents.config.settings import get_settings, update_settings

# Update settings at runtime
update_settings(
    debug=True,
    max_loop_count=5,
    tool_timeout=60
)

# Get current settings
settings = get_settings()
```

## 📈 Performance Monitoring

### Enable Performance Tracking

```python
# Enable detailed performance monitoring
controller.enable_performance_monitoring()

# Execute with monitoring
result = controller.run(messages, tool_manager)

# Get performance statistics
perf_stats = controller.get_performance_stats()
```

### Performance Metrics

```python
{
    'total_time': 25.5,
    'agent_times': {
        'TaskAnalysisAgent': 3.2,
        'TaskDecomposeAgent': 2.1,
        'PlanningAgent': 4.5,
        # ... other agents
    },
    'tool_stats': {
        'calculator': {'count': 3, 'avg_time': 0.1},
        'web_search': {'count': 1, 'avg_time': 2.5}
    },
    'bottlenecks': ['PlanningAgent', 'web_search'],
    'optimization_suggestions': [
        'Consider caching web search results',
        'Optimize planning algorithm'
    ]
}
```

## 🌐 Web Integration

### Streamlit Integration

```python
import streamlit as st
from agents.utils.streamlit_helpers import (
    display_agent_conversation,
    create_sidebar_controls,
    format_token_usage
)

# Display conversation with agent role indicators
display_agent_conversation(messages)

# Create control sidebar
controls = create_sidebar_controls()

# Format token usage for display
usage_display = format_token_usage(token_stats)
```

### FastAPI Integration

```python
from fastapi import FastAPI
from agents.web.fastapi_routes import create_sage_routes

app = FastAPI()

# Add Sage routes
sage_routes = create_sage_routes(controller, tool_manager)
app.include_router(sage_routes, prefix="/api/sage")
```

## 🔐 Security Considerations

### Input Validation

```python
from agents.utils.validation import (
    validate_messages,
    sanitize_system_context,
    check_permissions
)

# Validate input messages
validated_messages = validate_messages(input_messages)

# Sanitize system context
safe_context = sanitize_system_context(system_context)

# Check user permissions
if not check_permissions(user_id, action="execute_agent"):
    raise PermissionError("Insufficient permissions")
```

### Safe Execution

```python
# Execute with safety checks
result = controller.run(
    messages,
    tool_manager,
    system_context={
        "security_level": "high",
        "sandboxed": True,
        "allowed_tools": ["calculator", "text_processor"],
        "restricted_domains": ["file_system", "network"]
}
)
```

## 📊 Monitoring & Logging

### Enable Logging

```python
import logging
from agents.utils.logger import setup_logging

# Setup structured logging
setup_logging(
    level=logging.INFO,
    format="json",
    output="file",
    filename="sage.log"
)
```

### Custom Monitoring

```python
from agents.utils.monitoring import SageMonitor

monitor = SageMonitor()

# Track custom metrics
monitor.track_execution_time("agent_workflow", 25.5)
monitor.track_token_usage("gpt-4", 1500)
monitor.track_tool_usage("calculator", success=True)

# Export metrics
metrics = monitor.export_metrics()
```

---

For more app and advanced usage patterns, see the [Examples Guide](EXAMPLES.md).

**Built with ❤️ by Eric ZZ and the Sage community** 
