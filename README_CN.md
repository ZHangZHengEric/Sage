![logo](assets/logo.png)

[![English](https://img.shields.io/badge/English-Click-yellow)](README.md)
[![简体中文](https://img.shields.io/badge/简体中文-点击查看-orange)](README_CN.md)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-brightgreen.svg)](https://python.org)
[![Version](https://img.shields.io/badge/Version-0.8-green.svg)](https://github.com/ZHangZHengEric/Sage)

# 🚀 Sage 多智能体框架

> **生产就绪、模块化、智能的多智能体编排框架，专为复杂问题解决而设计**

Sage 是一个先进的多智能体系统，通过无缝的智能体协作，智能地将复杂任务分解为可管理的子任务。采用企业级可靠性和可扩展性设计，提供**深度研究模式**进行全面分析和**快速执行模式**进行快速任务完成。

## ✨ 核心亮点

🧠 **智能任务分解** - 自动将复杂问题分解为可管理的子任务，支持依赖关系跟踪  
🔄 **智能体编排** - 专业智能体间的无缝协调，具备强大的错误处理机制  
🛠️ **可扩展工具系统** - 基于插件的架构，支持MCP服务器和自动发现  
⚡ **双重执行模式** - 根据需求选择深度分析或快速执行  
🌐 **交互式Web界面** - 基于Streamlit的精美UI，实时流式可视化  
📊 **高级令牌跟踪** - 全面的使用统计和所有智能体的成本监控  
⚙️ **丰富配置** - 环境变量、配置文件、CLI选项和运行时更新  
🔧 **开发者友好** - 清洁的API、全面的文档、示例和广泛的错误处理  
🎯 **生产就绪** - 强大的错误恢复、日志记录、重试机制和性能优化

## 🤖 支持的模型

Sage 已经过以下语言模型的广泛测试：

### ✅ 官方测试模型
- **🔥 DeepSeek-V3** - `deepseek-chat` - 复杂推理的卓越性能
- **🌟 Qwen-3** - `qwen-turbo`, `qwen-plus` - 出色的中英文能力  
- **🧠 GPT-4.1** - `gpt-4-turbo`, `gpt-4o` - 所有任务的顶级性能
- **⚡ Claude-3.5 Sonnet** - `claude-3-5-sonnet-20241022` - 卓越的推理能力

### 🌐 兼容提供商
- **OpenAI** - 直接API集成
- **OpenRouter** - 访问200+模型
- **Anthropic** - Claude系列模型
- **Google AI** - Gemini系列
- **DeepSeek** - 原生API支持
- **阿里云** - Qwen系列
- **Mistral AI** - 所有Mistral模型

> 💡 **注意**: 虽然Sage针对上述模型进行了优化，但它设计为可与任何OpenAI兼容的API端点配合使用。

## 🏗️ 架构概览

```mermaid
graph TD
    A[🔍 用户输入] --> B(📋 任务分析智能体)
    B --> C{✅ 分析完成?}
    C -->|是| D[🎯 规划智能体]
    C -->|否| B
    D --> E[⚡ 执行智能体]
    E --> F[👁️ 观察智能体]
    F --> G{🎪 任务完成?}
    G -->|是| H[📄 总结智能体]
    G -->|否| D
    H --> I[🎉 最终输出]
    
    subgraph "🛠️ 工具生态系统"
        E --> J[🔧 工具管理器]
        J -->|本地| K[📱 内置工具]
        J -->|远程| L[🌐 MCP服务器]
        L --> M[🔌 外部API]
        K --> N[📊 结果]
        M --> N
        N --> F
    end
    
    subgraph "📊 令牌跟踪"
        B --> P[💰 使用监控]
        D --> P
        E --> P
        F --> P
        H --> P
        P --> Q[📈 成本分析]
    end
    
    style A fill:#e1f5fe
    style I fill:#e8f5e8
    style J fill:#fff3e0
    style P fill:#f3e5f5
```

## 🚀 快速开始

### 安装

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
pip install -r requirements.txt
```

### 🎮 交互式Web演示

通过我们精美的Web界面体验Sage，实时智能体可视化：

```bash
# 使用 DeepSeek-V3 (推荐)
streamlit run examples/sage_demo.py -- \
  --api_key YOUR_DEEPSEEK_API_KEY \
  --model deepseek-chat \
  --base_url https://api.deepseek.com/v1

# 使用 OpenRouter (多模型)
streamlit run examples/sage_demo.py -- \
  --api_key YOUR_OPENROUTER_API_KEY \
  --model deepseek/deepseek-chat \
  --base_url https://openrouter.ai/api/v1

# 使用 GPT-4
streamlit run examples/sage_demo.py -- \
  --api_key YOUR_OPENAI_API_KEY \
  --model gpt-4o \
  --base_url https://api.openai.com/v1
```

### 🌐 现代化Web应用（FastAPI + React）

通过我们前沿的Web应用体验Sage，采用现代React前端和FastAPI后端：

![Sage Web应用](assets/sage_web_app.png)

**功能特性：**
- 🤖 **多智能体协作** - 可视化工作流，包含分解、规划、执行、观察和总结
- 🧠 **深度思考模式** - 可展开的思考气泡，显示智能体推理过程
- 🚀 **FastAPI后端** - 高性能异步API服务器，支持流式响应
- ⚛️ **React前端** - 现代化响应式UI，采用Ant Design组件
- 📡 **实时通信** - WebSocket + SSE双重支持，实现实时更新
- 🎨 **精美界面** - 可折叠深度思考气泡，现代化设计
- 🔧 **工具管理** - 自动工具发现和管理
- 📱 **响应式设计** - 适配所有屏幕尺寸
- 🔧 **TypeScript支持** - 全程类型安全

**快速开始：**
```bash
cd examples/fastapi_react_demo

# 后端设置
python start_backend.py

# 前端设置（新终端）
cd frontend
npm install
npm run dev
```

在 `http://localhost:8080` 访问应用。详细设置说明请参见 [FastAPI React Demo README](examples/fastapi_react_demo/README.md)。

### 💻 命令行使用

```python
from agents.agent.agent_controller import AgentController
from agents.tool.tool_manager import ToolManager
from openai import OpenAI

# DeepSeek-V3示例
model = OpenAI(
    api_key="your-deepseek-api-key", 
    base_url="https://api.deepseek.com/v1"
)
tool_manager = ToolManager()
controller = AgentController(model, {
    "model": "deepseek-chat",
    "temperature": 0.7,
    "max_tokens": 4096
})

# 执行任务并进行全面跟踪
messages = [{"role": "user", "content": "分析当前AI趋势并提供可操作的见解"}]
result = controller.run(messages, tool_manager, deep_thinking=True, summary=True)

# 访问结果和使用统计
print("最终输出:", result['final_output']['content'])
print("令牌使用:", result['token_usage'])
print("执行时间:", result['execution_time'])
```

## 🎯 核心功能

### 🤖 **多智能体协作 (v0.8)**
- **任务分析智能体**: 增强的深度理解，支持上下文感知
- **规划智能体**: 战略性分解，支持依赖管理和工具选择
- **执行智能体**: 智能工具执行，支持错误恢复和重试机制
- **观察智能体**: 高级进度监控，支持完成检测
- **总结智能体**: 全面结果综合，支持结构化输出

### 🛠️ **高级工具系统**
- **插件架构**: 热重载工具开发，支持自动注册
- **MCP 服务器支持**: 与模型上下文协议服务器无缝集成
- **自动发现**: 从目录和模块智能检测工具
- **类型安全**: 全面的参数验证和模式强制
- **错误处理**: 强大的错误恢复、超时管理和详细日志
- **性能监控**: 工具执行时间跟踪和优化建议

### 📊 **Token使用和成本监控**
- **实时跟踪**: 监控所有智能体和操作的token消耗
- **详细分析**: 输入、输出、缓存和推理token细分
- **成本估算**: 基于模型定价和使用模式计算成本
- **性能指标**: 跟踪执行时间、成功率和效率
- **导出功能**: CSV、JSON 导出供进一步分析

```python
# 获取全面的token统计
stats = controller.get_comprehensive_token_stats()
print(f"总Token数: {stats['total_tokens']}")
print(f"总成本: ${stats['estimated_cost']:.4f}")
print(f"智能体细分: {stats['agent_breakdown']}")

# 打印详细统计
controller.print_comprehensive_token_stats()
```

### ⚙️ **丰富的配置系统**
- **环境变量**: `SAGE_DEBUG`, `OPENAI_API_KEY`, `SAGE_MAX_LOOP_COUNT` 等
- **配置文件**: YAML/JSON 配置，支持验证和热重载
- **运行时更新**: 无需重启的动态配置更改
- **命令行选项**: 全面的命令行界面和帮助系统
- **配置文件管理**: 保存和加载配置配置文件

### 🔄 **执行模式**

#### 深度研究模式（推荐用于复杂任务）
```python
result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,    # 启用全面任务分析
    summary=True,          # 生成详细的带见解总结
    deep_research=True     # 完整多智能体流水线
)

# 带实时更新的流式版本
for chunk in controller.run_stream(
    messages, 
    tool_manager,
    deep_thinking=True,
    summary=True,
    deep_research=True
):
    for message in chunk:
        print(f"[{message['type']}] {message['role']}: {message['show_content']}")
```

#### 标准执行模式（平衡性能）
```python
result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,    # 启用任务分析
    summary=True,          # 生成总结
    deep_research=False    # 跳过详细研究阶段
)
```

#### 快速执行模式（最大速度）
```python
result = controller.run(
    messages,
    tool_manager, 
    deep_thinking=False,   # 跳过分析
    deep_research=False    # 直接执行
)
```

## 📊 实时流式输出和监控

实时观察您的智能体工作，带有详细的进度跟踪：

```python
import time

start_time = time.time()
token_count = 0

for chunk in controller.run_stream(messages, tool_manager):
    for message in chunk:
        # 显示智能体活动
        print(f"🤖 {message['role']}: {message['show_content']}")
        
        # 跟踪进度
        if 'usage' in message:
            token_count += message['usage'].get('total_tokens', 0)
        
        # 实时统计
        elapsed = time.time() - start_time
        print(f"⏱️  时间: {elapsed:.1f}s | 🪙 Token: {token_count}")
```

## 🔧 高级工具开发

创建具有完整框架集成的复杂自定义工具：

```python
from agents.tool.tool_base import ToolBase
from typing import Dict, Any, Optional
import requests

class DataAnalysisTool(ToolBase):
    """高级数据分析工具，支持缓存和验证"""
    
    @ToolBase.tool()
    def analyze_data(self, 
                    data_source: str, 
                    analysis_type: str,
                    options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行全面的数据分析和可视化
        
        Args:
            data_source: 数据源URL或路径
            analysis_type: 分析类型（statistical/trend/correlation）
            options: 额外的分析选项
        """
        try:
            # 您的实现代码
            result = self._perform_analysis(data_source, analysis_type, options)
            
            return {
                "success": True,
                "data": result,
                "metadata": {
                    "execution_time": self.execution_time,
                    "data_size": len(result.get("records", [])),
                    "analysis_type": analysis_type
                }
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__
            }
    
    def _perform_analysis(self, source, analysis_type, options):
        # 实现细节
        pass
```

## 🛡️ 错误处理和可靠性

Sage 包含全面的错误处理和恢复机制：

```python
from agents.utils.exceptions import SageException, with_retry, exponential_backoff

# 带指数退避的自动重试
@with_retry(exponential_backoff(max_attempts=3, base_delay=1.0))
def robust_execution():
    return controller.run(messages, tool_manager)

# 自定义错误处理
try:
    result = controller.run(messages, tool_manager)
except SageException as e:
    print(f"Sage 错误: {e}")
    print(f"错误代码: {e.error_code}")
    print(f"恢复建议: {e.recovery_suggestions}")
```

## 📈 性能监控

监控和优化您的智能体性能：

```python
# 启用详细的性能跟踪
controller.enable_performance_monitoring()

# 带监控的执行
result = controller.run(messages, tool_manager)

# 分析性能
perf_stats = controller.get_performance_stats()
print(f"执行时间: {perf_stats['total_time']:.2f}s")
print(f"智能体分解: {perf_stats['agent_times']}")
print(f"工具使用: {perf_stats['tool_stats']}")
print(f"瓶颈: {perf_stats['bottlenecks']}")

# 导出性能数据
controller.export_performance_data("performance_report.json")
```

## 🔌 MCP 服务器集成

与模型上下文协议服务器无缝集成：

```bash
# 启动 MCP 服务器
python mcp_servers/weather_server.py &
python mcp_servers/database_server.py &

# 在您的应用中使用
tool_manager.register_mcp_server("weather", "http://localhost:8001")
tool_manager.register_mcp_server("database", "http://localhost:8002")

# 工具自动可用
result = controller.run([{
    "role": "user", 
    "content": "获取东京的天气并保存到数据库"
}], tool_manager)
```

## 📚 文档

- **[快速开始指南](docs/QUICK_START.md)** - 5分钟内快速上手
- **[架构概览](docs/ARCHITECTURE.md)** - 详细的系统设计
- **[API 参考](docs/API_REFERENCE_CN.md)** - 完整的 API 文档
- **[工具开发](docs/TOOL_DEVELOPMENT.md)** - 创建自定义工具
- **[配置指南](docs/CONFIGURATION.md)** - 高级配置选项
- **[示例](docs/EXAMPLES_CN.md)** - 实际使用示例

## 🎯 生产部署

Sage 具备企业级特性，已为生产环境做好准备：

```python
from agents.config.settings import get_settings, update_settings

# 生产环境配置
update_settings(
    debug=False,
    max_loop_count=5,
    tool_timeout=30,
    enable_logging=True,
    log_level="INFO"
)

# 使用生产设置初始化
controller = AgentController.from_config("production.yaml")
```

## 🔄 最新更新 (v0.8)

### ✨ 新功能
- 🎯 **增强的Token跟踪**: 全面的使用统计和成本监控
- 🛡️ **强大的错误处理**: 高级错误恢复和重试机制
- ⚡ **性能优化**: 更好的资源管理，执行速度提升40%
- 🔧 **改进的工具系统**: 自动发现、更好的验证和MCP集成
- 📊 **实时监控**: 实时性能指标和瓶颈检测
- 🤖 **扩展的模型支持**: 原生支持 DeepSeek-V3、Qwen-3 等模型

### 🔧 技术改进
- 🏗️ **智能体架构**: 重构以提高模块化和可维护性
- 💾 **内存管理**: 为长时间运行的任务优化内存使用
- 🌐 **流式增强**: 改进实时更新和更好的UI反馈
- ⚙️ **配置系统**: 更灵活和强大的配置选项
- 📝 **文档**: 完全重写，包含更多示例和最佳实践

### 🐛 Bug修复
- 修复流式模式下的token使用计算错误
- 解决长时间运行智能体会话中的内存泄漏
- 改进对格式错误工具响应的错误处理
- 增强与不同OpenAI API版本的兼容性

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

## 🙏 致谢

- OpenAI 提供的强大语言模型
- DeepSeek 提供的卓越V3模型
- 阿里云提供的通义千问系列
- 开源社区提供的灵感和工具
- 所有帮助 Sage 变得更好的贡献者

---

<div align="center">
  <sub>由 Sage 团队用 ❤️ 构建</sub>
</div>
