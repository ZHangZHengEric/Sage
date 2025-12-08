# Sage 示例使用指南

## 简介

本目录包含了 Sage 智能代理框架的三个主要示例应用，分别提供不同的交互方式和使用场景：

- **sage_cli.py** - 命令行交互工具
- **sage_demo.py** - Web界面演示应用  
- **sage_server.py** - HTTP API服务器

每个示例都展示了 Sage 框架的核心功能，包括智能对话、工具调用、多智能体协作等特性。

## 功能特性

- 🤖 **智能对话**：支持与AI智能体进行自然语言对话
- 🔧 **工具集成**：集成MCP工具，支持文件操作、网络搜索等功能
- 🧠 **深度思考**：可选启用深度思考模式，提供更详细的推理过程
- 👥 **多智能体**：支持多智能体协作，处理复杂任务
- ⚡ **流式输出**：实时显示AI响应，提供流畅的交互体验
- 🎨 **美观界面**：不同的UI展示方式，适应不同使用场景

## 安装要求

确保已安装以下依赖：

```bash
pip install rich openai asyncio streamlit fastapi uvicorn
```

## 配置文件

### 1. MCP设置文件 (mcp_setting.json)

配置MCP工具服务器：

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

### 2. 预设运行配置 (preset_running_config.json)

该配置文件定义了智能体的运行参数和行为设置：

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
  "systemPrefix": "你是一个有用的AI助手。",
  "maxLoopCount": 10,
  "available_workflows": {},
  "system_context": {}
}
```

## 示例应用详解

### 1. sage_cli.py - 命令行交互工具

**功能特点：**
- 🎨 美观的彩色消息框架显示
- ⚡ 流式输出，实时显示AI响应
- 🔧 支持工具调用和结果展示
- 📊 显示可用工具列表
- 💬 支持连续对话和会话管理

**使用方法：**

```bash
# 基本用法
python sage_cli.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com

# 完整参数示例
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

**主要参数：**
- `--api_key` (必需): API密钥
- `--model` (必需): 模型名称
- `--base_url` (必需): API基础URL
- `--no-deepthink`: 禁用深度思考模式
- `--no-multi-agent`: 禁用多智能体模式
- `--workspace`: 工作目录路径
- `--user_id`: 用户ID
- `--memory_root`: 记忆存储根目录

### 2. sage_demo.py - Web界面演示应用

**功能特点：**
- 🌐 基于Streamlit的现代Web界面
- 📊 实时显示系统信息和工具列表
- ⚙️ 可视化配置深度思考和多智能体选项
- 💬 支持对话历史管理
- 🎯 流式消息显示和实时更新

**使用方法：**

```bash
# 基本启动
python sage_demo.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com

# 指定端口和主机
python sage_demo.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com \
  --host 0.0.0.0 \
  --port 8502

# 完整配置
python sage_demo.py \
  --api_key YOUR_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://api.deepseek.com \
  --workspace ./workspace \
  --mcp_config ./mcp_setting.json \
  --preset_running_config ./preset_running_config.json \
  --memory_root ./memory
```

**主要参数：**
- `--api_key` (必需): API密钥
- `--model` (必需): 模型名称  
- `--base_url` (必需): API基础URL
- `--host`: 服务器主机地址 (默认: localhost)
- `--port`: 服务器端口 (默认: 8501)
- `--workspace`: 工作目录
- `--mcp_config`: MCP配置文件路径
- `--preset_running_config`: 预设配置文件路径

### 3. sage_server.py - HTTP API服务器

**功能特点：**
- 🚀 基于FastAPI的高性能HTTP服务器
- 📡 支持Server-Sent Events (SSE) 流式通信
- 🔄 RESTful API接口设计
- 🎛️ 支持会话管理和中断控制
- 📊 提供系统状态和工具信息查询
- 🔧 支持动态配置和多用户会话

**使用方法：**

```bash
# 基本启动
python sage_server.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com \
  --default_llm_model_name deepseek/deepseek-chat

# 完整配置启动
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
  --memory_root ./memory \
  --logs-dir ./logs

# 守护进程模式
python sage_server.py \
  --default_llm_api_key YOUR_API_KEY \
  --default_llm_api_base_url https://api.deepseek.com \
  --default_llm_model_name deepseek/deepseek-chat \
  --daemon \
  --pid-file sage_server.pid
```

**主要参数：**
- `--default_llm_api_key` (必需): 默认LLM API密钥
- `--default_llm_api_base_url` (必需): 默认LLM API基础URL
- `--default_llm_model_name` (必需): 默认LLM模型名称
- `--host`: 服务器主机地址 (默认: 0.0.0.0)
- `--port`: 服务器端口 (默认: 8001)
- `--workspace`: 工作空间目录
- `--mcp-config`: MCP配置文件路径
- `--preset_running_config`: 预设运行配置文件路径
- `--daemon`: 以守护进程模式运行
- `--pid-file`: PID文件路径

**API接口：**

```bash
# 流式聊天接口
POST /chat/stream
Content-Type: application/json

{
  "messages": [{"role": "user", "content": "你好"}],
  "session_id": "optional-session-id",
  "deep_thinking": true,
  "multi_agent": true
}

# 中断会话
POST /session/{session_id}/interrupt

# 获取会话状态
GET /session/{session_id}/status

# 获取系统信息
GET /system/info

# 获取可用工具
GET /tools/list
```

## 交互界面展示

### CLI界面消息类型

程序会显示不同类型的消息，每种类型都有独特的颜色和图标：

- 🔧 **工具调用** (黄色)
- ⚙️ **工具结果** (黄色)  
- 🎯 **子任务结果** (红色)
- ❌ **错误** (红色)
- ⚙️ **系统** (黑色)
- 💬 **普通消息** (蓝色)

### Web界面功能

- 📊 侧边栏显示系统配置和工具列表
- 🎛️ 可视化切换深度思考和多智能体模式
- 💬 流式对话显示，支持历史记录
- 🗑️ 一键清除对话历史

## 使用场景

### 1. 开发调试 - 使用 CLI
适合开发者进行快速测试和调试：
```bash
python sage_cli.py --api_key KEY --model MODEL --base_url URL
```

### 2. 演示展示 - 使用 Web界面
适合向客户或团队展示功能：
```bash
python sage_demo.py --api_key KEY --model MODEL --base_url URL --port 8502
```

### 3. 生产部署 - 使用 API服务器
适合集成到现有系统或提供API服务：
```bash
python sage_server.py --default_llm_api_key KEY --default_llm_api_base_url URL --default_llm_model_name MODEL
```

## 故障排除

### 常见问题

1. **API密钥错误**
   - 检查API密钥是否正确
   - 确认API服务可用

2. **模型不存在**
   - 验证模型名称是否正确
   - 检查API提供商支持的模型列表

3. **工具调用失败**
   - 检查MCP设置文件配置
   - 确认工具服务器正常运行

4. **配置文件错误**
   - 验证JSON格式是否正确
   - 检查文件路径是否存在

5. **端口占用**
   - 更换端口号或停止占用端口的进程
   - 使用 `lsof -i :端口号` 查看端口占用情况

### 调试模式

如果遇到问题，可以查看详细的错误信息：

```bash
# 程序会自动显示错误堆栈信息
# 检查日志输出以获取更多调试信息
```

## 开发说明

### 代码结构

- `sage_cli.py`：命令行交互工具主程序
- `sage_demo.py`：Streamlit Web界面演示应用
- `sage_server.py`：FastAPI HTTP服务器
- `mcp_setting.json`：MCP工具配置文件
- `preset_running_config.json`：预设运行配置文件

### 自定义配置

可以通过修改配置文件来自定义：

- 默认模型参数
- 系统提示词
- 可用工具列表
- 工作流配置
- 系统上下文

### 扩展开发

每个示例都可以作为基础进行扩展：

- **CLI扩展**：添加新的命令行参数和交互功能
- **Web扩展**：增加新的页面和可视化组件
- **API扩展**：添加新的接口端点和功能

## 更新日志

- 支持三种不同的交互方式
- 统一的配置文件格式
- 优化的流式消息显示
- 完善的错误处理和调试信息
- 支持会话管理和状态控制

## 许可证

本项目遵循相应的开源许可证。
