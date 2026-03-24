---
layout: default
title: Home
nav_order: 1
description: "Welcome to the comprehensive documentation for Sage Multi-Agent Framework"
permalink: /
---

# 📚 Sage Multi-Agent Framework Documentation

Welcome to the comprehensive documentation for Sage Multi-Agent Framework v0.9 - an advanced, production-ready multi-agent orchestration system.

## 🌐 Language Selection

| 🇺🇸 English Documentation | 🇨🇳 中文文档 |
|:---------------------------|:-------------|
| [🏃 Quick Start Guide](QUICK_START.html) | [🏃 快速开始指南](QUICK_START_CN.html) |
| [🏗️ Architecture Guide](ARCHITECTURE.html) | [🏗️ 架构指南](ARCHITECTURE_CN.html) |
| [🛠️ Tool Development](TOOL_DEVELOPMENT.html) | [🛠️ 工具开发指南](TOOL_DEVELOPMENT_CN.html) |
| [📖 API Reference](API_REFERENCE.html) | [📖 API 参考](API_REFERENCE_CN.html) |
| [🎯 Examples & Use Cases](EXAMPLES.html) | [🎯 示例和用例](EXAMPLES_CN.html) |
| [⚙️ Configuration Reference](CONFIGURATION.html) | [⚙️ 配置参考](CONFIGURATION_CN.html) |
| [🚀 Server Deployment Guide](SERVER_DEPLOYMENT.html) | [🚀 Server 部署指南](SERVER_DEPLOYMENT_CN.html) |
| [📖 Examples Usage Guide](EXAMPLES_USAGE.html) | [📖 示例使用指南](EXAMPLES_USAGE_CN.html) |
| [📅 Changelog](CHANGELOG.html) | [📅 更新日志](CHANGELOG_CN.html) |

{: .note }
> **选择语言 / Choose Language**: 所有文档都提供中英文双语版本。All documentation is available in both Chinese and English.

## 🚀 Quick Links

- **[Quick Start Guide](QUICK_START.md)** - Get up and running in 5 minutes
- **[Architecture Overview](ARCHITECTURE.md)** - Deep dive into system design  
- **[API Reference](API_REFERENCE.md)** - Complete API documentation
- **[Tool Development](TOOL_DEVELOPMENT.md)** - Create custom tools
- **[Configuration Guide](CONFIGURATION.md)** - Advanced configuration
- **[Examples](EXAMPLES.md)** - Real-world usage app

## 📖 Documentation Overview

### Getting Started
- [Quick Start Guide](QUICK_START.md) - Essential setup and first steps
- [Installation Guide](QUICK_START.md#installation) - Detailed installation instructions
- [Basic Usage](QUICK_START.md#basic-usage) - Your first Sage application

### Core Concepts
- [Architecture Overview](ARCHITECTURE.md) - Multi-agent system design
- [Agent Types](ARCHITECTURE.md#agent-types) - Understanding different agent roles
- [Tool System](TOOL_DEVELOPMENT.md) - Extensible tool architecture
- [System Context](API_REFERENCE.md#system-context) - Unified context management

### Development
- [API Reference](API_REFERENCE.md) - Complete API documentation
- [Tool Development](TOOL_DEVELOPMENT.md) - Creating custom tools
- [Agent Development](ARCHITECTURE.md#custom-agents) - Building custom agents
- [Configuration](CONFIGURATION.md) - Advanced configuration options

### Examples & Tutorials
- [Basic Examples](EXAMPLES.md#basic-app) - Simple use cases
- [Advanced Examples](EXAMPLES.md#advanced-app) - Complex scenarios
- [Integration Examples](EXAMPLES.md#integration-app) - Third-party integrations
- [Web Application](../app/fastapi_react_demo/README.md) - Modern React + FastAPI demo

## 🔥 What's New in v0.9

### 🎯 Enhanced Multi-Agent Pipeline
- **Task Decompose Agent**: New specialized agent for intelligent task breakdown
- **Unified System Context**: `system_context` parameter for consistent context management
- **Improved Workflow**: Enhanced task decomposition → planning → execution flow

### 🔧 Key Interface Updates
- **System Context API**: New `system_context` parameter in `run()` and `run_stream()` methods
- **Unified System Prompts**: All agents now use `SYSTEM_PREFIX_DEFAULT` constants
- **Enhanced Streaming**: Better real-time updates and WebSocket reliability

### 📊 Advanced Features  
- **Comprehensive Token Tracking**: Detailed usage analytics and cost optimization
- **Modern Web Application**: Complete FastAPI + React application with TypeScript
- **MCP Integration**: Enhanced Model Context Protocol server support

## 🏗️ Multi-Agent Architecture

Sage v0.9 features a sophisticated 6-agent pipeline:

1. **Task Analysis Agent** - Deep understanding and context analysis
2. **Task Decompose Agent** - Intelligent task breakdown and dependency mapping  
3. **Planning Agent** - Strategic execution planning and tool selection
4. **Executor Agent** - Tool execution and task completion
5. **Observation Agent** - Progress monitoring and quality assessment
6. **Summary Agent** - Result synthesis and actionable insights

## 🛠️ Core Components

### AgentController
```python
from agents.agent.agent_controller import AgentController

controller = AgentController(model, model_config)

# Enhanced with system_context support
result = controller.run(
    messages,
    tool_manager,
    system_context={
        "project_info": "AI research",
        "constraints": ["time: 2h", "budget: $100"],
        "preferences": {"output_format": "structured"}
    }
)
```

### ToolManager
```python
from agents.tool.tool_manager import ToolManager

tool_manager = ToolManager()
# Auto-discovers tools from agents/tool/ directory
# Supports MCP servers and custom tool registration
```

### System Context Management
```python
# Unified context across all agents
system_context = {
    "session_id": "unique_session",
    "current_time": "2024-01-15 14:30:00",
    "file_workspace": "/tmp/workspace",
    "custom_data": {"priority": "high", "domain": "research"}
}

# All agents receive consistent context
for chunk in controller.run_stream(messages, tool_manager, system_context=system_context):
    # Process streaming results
    pass
```

## 📱 Execution Modes

### Deep Research Mode
Complete multi-agent pipeline with task decomposition:
```python
result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,
    deep_research=True,  # Full 6-agent pipeline
    summary=True,
    system_context=context
)
```

### Standard Mode  
Simplified workflow without decomposition:
```python
result = controller.run(
    messages,
    tool_manager, 
    deep_thinking=True,
    deep_research=False,  # Skip decomposition
    system_context=context
)
```

### Rapid Mode
Direct execution for maximum speed:
```python
result = controller.run(
    messages,
    tool_manager,
    deep_thinking=False,
    deep_research=False,
    system_context=context
)
```

## 🌐 Web Applications

### Streamlit Demo
Beautiful interactive web interface:
```bash
streamlit run app/sage_demo.py -- \
  --api_key YOUR_API_KEY \
  --model deepseek-chat \
  --base_url https://api.deepseek.com/v1
```

### FastAPI + React Application
Modern web application with TypeScript:
```bash
cd app/fastapi_react_demo
python start_backend.py

# New terminal
cd frontend  
npm install && npm run dev
```

## 📊 Performance & Monitoring

### Token Tracking
```python
# Comprehensive usage analytics
stats = controller.get_comprehensive_token_stats()
print(f"Total tokens: {stats['total_tokens']}")
print(f"Cost: ${stats['estimated_cost']:.4f}")
print(f"Agent breakdown: {stats['agent_breakdown']}")
```

### Real-time Monitoring
```python
# Enhanced streaming with monitoring
for chunk in controller.run_stream(
    messages, 
    tool_manager,
    system_context={
        "monitoring_level": "detailed",
        "performance_tracking": True
    }
):
    # Process real-time updates
    pass
```

## 🔌 Integration & Extensions

### MCP Server Integration
```python
# Automatic MCP server discovery
tool_manager = ToolManager()  # Auto-discovers from mcp_servers/

# Manual registration
await tool_manager.register_mcp_server("custom_server", {
    "command": "python server.py",
    "args": ["--port", "8001"]
})
```

### Custom Tool Development
```python
from sagents.tool.tool_base import tool

class CustomTool:
    @tool()
    def analyze_data(self, data: str, format: str = "json") -> dict:
        """Custom data analysis tool"""
        return {"result": "analysis_complete"}
```

## 🤝 Contributing

We welcome contributions! See our development guides:

- [Contributing Guidelines](../CONTRIBUTING.md)
- [Development Setup](QUICK_START.md#development-setup)
- [Testing Guide](../tests/README.md)

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/ZHangZHengEric/Sage/issues)
- **Discussions**: [GitHub Discussions](https://github.com/ZHangZHengEric/Sage/discussions)
- **Documentation**: This documentation site
- **Examples**: [Examples Directory](../app/)

## 📄 License

Sage is released under the MIT License. See [LICENSE](../LICENSE) for details.

---

**Built with ❤️ by Eric ZZ and the Sage community**

## 🎯 Popular Topics

- **🚀 Getting Started**: New to Sage? Start here!
- **🛠️ Custom Tools**: Learn how to extend Sage with your own tools
- **🏗️ Architecture**: Understand how Sage works under the hood
- **⚙️ Configuration**: Customize Sage for your specific needs
- **📊 Real-world Examples**: See Sage in action with practical use cases

## 💡 Tips for Navigation

{: .highlight }
- **Beginners**: Follow the documentation in order: Quick Start → Examples → Configuration
- **Developers**: Jump to Architecture and API Reference for technical details
- **Tool Builders**: Focus on Tool Development guide and API Reference
- **Language Preference**: All documentation is available in both English and Chinese

## 🤝 Contributing to Documentation

Found an issue or want to improve the docs? 

1. Check the source files in the `docs/` directory
2. Submit issues or pull requests to help us improve
3. Follow our documentation style guide for consistency

---

**Need help?** Check our [Examples](EXAMPLES.html) / [示例](EXAMPLES_CN.html) or open an issue on GitHub! 
