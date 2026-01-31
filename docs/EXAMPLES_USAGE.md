---
layout: default
title: Examples Usage Guide
nav_order: 12
description: "Sage Examples Application Usage Guide (CLI, Web, Server)"
---

# Sage Examples Usage Guide

## Introduction

This directory contains three main example applications of the Sage intelligent agent framework, each providing different interaction methods and usage scenarios:

- **sage_cli.py** - Command Line Interaction Tool
- **sage_demo.py** - Web Interface Demo Application
- **sage_server.py** - HTTP API Server

Each example demonstrates the core features of the Sage framework, including intelligent dialogue, tool calling, multi-agent collaboration, etc.

## Features

- 🤖 **Intelligent Dialogue**: Supports natural language dialogue with AI agents
- 🔧 **Tool Integration**: Integrates MCP tools, supports file operations, web search, etc.
- 🧠 **Deep Thinking**: Optional deep thinking mode, providing more detailed reasoning processes
- 👥 **Multi-Agent**: Supports multi-agent collaboration to handle complex tasks
- ⚡ **Streaming Output**: Real-time display of AI responses, providing smooth interaction experience
- 🎨 **Beautiful Interface**: Different UI presentation methods adapting to different usage scenarios

## Installation Requirements

Ensure the following dependencies are installed:

```bash
pip install rich openai asyncio streamlit fastapi uvicorn
```

## Configuration Files

### 1. MCP Settings File (mcp_setting.json)

Configure MCP tool servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["@modelcontextprotocol/server-filesystem", "/path/to/workspace"],
      "env": {}
    },
    "web_search": {
      "sse_url": "http://127.0.0.1:20042/sse",
      "disabled": false,
      "api_key": "your-api-key"
    }
  }
}
```

### 2. Preset Running Configuration (preset_running_config.json)

This configuration file defines the running parameters and behavior settings of the agent:

```json
{
  "llmConfig": {
    "model": "deepseek/deepseek-chat",
    "maxTokens": 4096,
    "temperature": 0.2
  },
  "deepThinking": false,
  "multiAgent": false,
  "availableTools": [],
  "systemPrefix": "You are a helpful AI assistant.",
  "maxLoopCount": 10,
  "available_workflows": {},
  "system_context": {}
}
```

## Example Applications Details

### 1. sage_cli.py - Command Line Interaction Tool

**Features:**
- 🎨 Beautiful colored message frame display
- ⚡ Streaming output, real-time display of AI responses
- 🔧 Supports tool calling and result display
- 📊 Displays available tool list
- 💬 Supports continuous dialogue and session management

**Usage:**

```bash
# Basic Usage
python sage_cli.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com

## 📉 Stress Test Scripts

Sage provides stress test scripts to evaluate system performance under high concurrency scenarios.

### Script Location
`tests/stress_test.py`

### Usage
```bash
python tests/stress_test.py --concurrency 10 --requests 100 --url http://localhost:8000
```

### Monitoring Metrics
- RPS (Requests Per Second)
- Average Response Time
- Error Rate

# Complete Parameter Example
python sage_cli.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com \
  --max_tokens 4096 \
  --temperature 0.2 \
  --workspace ./workspace \
  --mcp_setting_path ./mcp_setting.json \
  --preset_running_agent_config_path ./preset_running_config.json
```

**Main Parameters:**
- `--api_key` (Required): API Key
- `--model` (Required): Model Name
- `--base_url` (Required): API Base URL
- `--no-deepthink`: Disable deep thinking mode
- `--no-multi-agent`: Disable multi-agent mode
- `--workspace`: Workspace directory path
- `--user_id`: User ID
- `--memory_type`: Memory Type (session | user)

### 2. sage_demo.py - Web Interface Demo Application

**Features:**
- 🌐 Modern Web interface based on Streamlit
- 📊 Real-time display of system information and tool list
- ⚙️ Visual configuration of deep thinking and multi-agent options
- 💬 Supports dialogue history management
- 🎯 Streaming message display and real-time updates

**Usage:**

```bash
# Basic Startup
python sage_demo.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com

# Specify Port and Host
python sage_demo.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com \
  --host 0.0.0.0 \
  --port 8502

# Complete Configuration
python sage_demo.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com \
  --workspace ./workspace \
  --mcp_config ./mcp_setting.json \
  --preset_running_config ./preset_running_config.json \
  --memory_type user
```

**Main Parameters:**
- `--api_key` (Required): API Key
- `--model` (Required): Model Name
- `--base_url` (Required): API Base URL
- `--host`: Server Host Address (Default: localhost)
- `--port`: Server Port (Default: 8501)
- `--workspace`: Workspace Directory
- `--mcp_config`: MCP Configuration File Path
- `--preset_running_config`: Preset Configuration File Path

### 3. sage_server.py - HTTP API Server

**Features:**
- 🚀 High-performance HTTP server based on FastAPI
- 📡 Supports Server-Sent Events (SSE) streaming communication
- 🔄 RESTful API interface design
- 🎛️ Supports session management and interrupt control
- 📊 Provides system status and tool information query
- 🔧 Supports dynamic configuration and multi-user sessions

**Usage:**

```bash
# Basic Startup
python sage_server.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com \
  --default_llm_model_name deepseek/deepseek-chat

# Complete Configuration Startup
python sage_server.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com \
  --default_llm_model_name deepseek/deepseek-chat \
  --default_llm_max_tokens 4096 \
  --default_llm_temperature 0.3 \
  --host 0.0.0.0 \
  --port 8001 \
  --workspace ./sage_workspace \
  --mcp-config ./mcp_setting.json \
  --preset_running_config ./preset_running_config.json \
  --memory_type user \
  --logs-dir ./logs

# Daemon Mode
python sage_server.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com \
  --default_llm_model_name deepseek/deepseek-chat \
  --pid-file sage_server.pid
```

**Main Parameters:**
- `--default_llm_api_key` (Required): Default LLM API Key
- `--default_llm_api_base_url` (Required): Default LLM API Base URL
- `--default_llm_model_name` (Required): Default LLM Model Name
- `--host`: Server Host Address (Default: 0.0.0.0)
- `--port`: Server Port (Default: 8001)
- `--workspace`: Workspace Directory
- `--mcp-config`: MCP Configuration File Path
- `--preset_running_config`: Preset Running Configuration File Path
- `--pid-file`: PID File Path

**API Interfaces:**

```bash
# Streaming Chat Interface
POST /chat/stream
Content-Type: application/json

{
  "messages": [{"role": "user", "content": "Hello"}],
  "session_id": "optional-session-id",
  "deep_thinking": true,
  "multi_agent": true
}

# Interrupt Session
POST /session/{session_id}/interrupt

# Get Session Status
GET /session/{session_id}/status

# Get System Info
GET /system/info

# Get Available Tools
GET /tools/list
```

## Interaction Interface Display

### CLI Interface Message Types

The program displays different types of messages, each with unique colors and icons:

- 🔧 **Tool Call** (Yellow)
- ⚙️ **Tool Result** (Yellow)
- 🎯 **Subtask Result** (Red)
- ❌ **Error** (Red)
- ⚙️ **System** (Black)
- 💬 **Normal Message** (Blue)

### Web Interface Features

- 📊 Sidebar displays system configuration and tool list
- 🎛️ Visual toggle for deep thinking and multi-agent modes
- 💬 Streaming dialogue display, supports history records
- 🗑️ One-click clear dialogue history

## Usage Scenarios

### 1. Development & Debugging - Using CLI
Suitable for developers for quick testing and debugging:
```bash
python sage_cli.py --api_key KEY --model MODEL --base_url URL
```

### 2. Demonstration - Using Web Interface
Suitable for showing features to clients or teams:
```bash
python sage_demo.py --api_key KEY --model MODEL --base_url URL --port 8502
```

### 3. Production Deployment - Using API Server
Suitable for integration into existing systems or providing API services:
```bash
python sage_server.py --default_llm_api_key KEY --default_llm_api_base_url URL --default_llm_model_name MODEL
```

## Troubleshooting

### Common Issues

1. **API Key Error**
   - Check if API Key is correct
   - Confirm API service is available

2. **Model Not Found**
   - Verify model name is correct
   - Check model list supported by API provider

3. **Tool Call Failed**
   - Check MCP settings file configuration
   - Confirm tool server is running normally

4. **Configuration File Error**
   - Verify JSON format is correct
   - Check if file path exists

5. **Port Occupied**
   - Change port number or stop process occupying the port
   - Use `lsof -i :port_number` to check port occupation

### Debug Mode

If you encounter issues, you can view detailed error information:

```bash
# The program will automatically display error stack trace
# Check log output for more debug information
```

## Development Instructions

### Code Structure

- `sage_cli.py`: Command line interaction tool main program
- `sage_demo.py`: Streamlit Web interface demo application
- `sage_server.py`: FastAPI HTTP server
- `mcp_setting.json`: MCP tool configuration file
- `preset_running_config.json`: Preset running configuration file

### Custom Configuration

You can customize by modifying configuration files:

- Default model parameters
- System prompts
- Available tool list
- Workflow configuration
- System context

### Extension Development

Each example can be used as a base for extension:

- **CLI Extension**: Add new command line parameters and interaction features
- **Web Extension**: Add new pages and visual components
- **API Extension**: Add new interface endpoints and features

## Changelog

- Support three different interaction methods
- Unified configuration file format
- Optimized streaming message display
- Improved error handling and debug information
- Support session management and status control

## License

This project follows the corresponding open source license.
