---
layout: default
title: 快速开始指南
nav_order: 3
description: "5分钟快速上手Sage多智能体框架"
---

# 🚀 快速开始指南

几分钟内开始使用 Sage 多智能体框架！

## 📦 安装

### 前置要求

- Python 3.10 或更高版本
- pip 包管理器
- Git

### 克隆和设置

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
pip install -r requirements.txt
```

## 目录
{: .no_toc .text-delta }

1. TOC
{:toc}

## 📋 前提条件

- **Python 3.10+** 已安装在您的系统上
- **OpenAI API 密钥** 或兼容的 API 端点（OpenRouter、DeepSeek 等）
- **Git** 用于克隆仓库

## ⚡ 5分钟快速设置

### 1. 克隆和安装

```bash
# 克隆仓库
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage

# 安装依赖
pip install -r requirements.txt
```

### 2. 设置环境变量

```bash
# 选项 1：设置环境变量
export OPENAI_API_KEY="your-api-key-here"
export SAGE_DEBUG=true
export SAGE_MAX_LOOP_COUNT=10

# 选项 2：创建 .env 文件（推荐）
cat > .env << EOF
OPENAI_API_KEY=your-api-key-here
SAGE_DEBUG=true
SAGE_ENVIRONMENT=development
SAGE_MAX_LOOP_COUNT=10
SAGE_TOOL_TIMEOUT=30
EOF
```

### 3. 运行您的第一个演示

```bash
# 增强功能网页界面（推荐）
streamlit run app/sage_demo.py -- \
  --api_key $OPENAI_API_KEY \
  --model mistralai/mistral-small-3.1-24b-instruct:free \
  --base_url https://openrouter.ai/api/v1

# 命令行界面
python app/multi_turn_demo.py
```

🎉 **就是这样！** 您现在应该看到 Sage 网页界面在 `http://localhost:8501` 运行，支持实时token跟踪！

## 🎮 使用网页界面

### 增强功能 (v2.0)

1. **💬 聊天界面**: 用自然语言输入您的问题
2. **⚙️ 高级设置**: 配置智能体、模型和性能选项
3. **🛠️ 工具浏览器**: 浏览自动发现的可用工具
4. **📊 Token监控**: 实时token使用和成本跟踪
5. **📈 性能仪表板**: 监控执行时间和瓶颈
6. **🔄 流式可视化**: 实时观察智能体工作

### 示例交互

尝试这些示例提示来体验 Sage 的增强功能：

```
🔍 复杂研究任务:
"研究人工智能的最新趋势，分析其对商业的影响，并提供可行的建议"

🧮 高级分析:
"比较可再生能源在成本、效率和环境影响方面的详细数据分析"

🛠️ 多步问题解决:
"帮我为新的SaaS产品创建全面的营销策略，包括市场分析、竞争定位和活动规划"

📊 数据驱动任务:
"计算初创公司在不同增长情况和投资需求下的财务预测"
```

## 💻 您的第一个带Token跟踪的Python脚本

创建一个具有增强监控的现代脚本：

```python
# my_first_sage_script.py
import os
import time
from agents.agent.agent_controller import AgentController
from agents.tool.tool_manager import ToolManager
from openai import OpenAI

def main():
    # 使用增强配置初始化组件
    api_key = os.getenv('OPENAI_API_KEY')
    model = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1"  # 使用OpenRouter进行成本效益访问
    )
    tool_manager = ToolManager()
    
    # 使用生产设置创建智能体控制器
    controller = AgentController(
        model, 
        {
            "model": "mistralai/mistral-small-3.1-24b-instruct:free",
            "temperature": 0.7,
            "max_tokens": 4096
        }
    )
    
    # 定义您的任务
    messages = [{
        "role": "user", 
        "content": "解释多智能体系统如何工作及其在现代AI中的应用",
        "type": "normal"
    }]
    
    print("🚀 开始Sage多智能体执行...")
    start_time = time.time()
    
    # 使用完整流水线和监控执行
    result = controller.run(
        messages, 
        tool_manager,
        deep_thinking=True,   # 启用全面任务分析
        summary=True,         # 生成详细总结
        deep_research=True    # 完整多智能体流水线
    )
    
    execution_time = time.time() - start_time
    
    # 打印增强信息的结果
    print("🎯 最终输出:")
    print(result['final_output']['content'])
    
    print(f"\n📊 执行摘要:")
    print(f"  • 生成了 {len(result['new_messages'])} 条消息")
    print(f"  • 总执行时间: {execution_time:.2f}s")
    
    # 显示全面的token统计
    print(f"\n💰 Token使用统计:")
    controller.print_comprehensive_token_stats()
    
    # 获取详细统计以进行进一步处理
    stats = controller.get_comprehensive_token_stats()
    print(f"\n📈 成本分析:")
    print(f"  • 总token数: {stats['total_tokens']}")
    print(f"  • 估计成本: ${stats.get('estimated_cost', 0):.4f}")

if __name__ == "__main__":
    main()
```

运行它：
```bash
python my_first_sage_script.py
```

## 🔧 增强配置选项

### 优化设置的API提供商

```python
# OpenAI（带流式token跟踪）
model = OpenAI(api_key="sk-...")

# OpenRouter（成本效益，多模型）
model = OpenAI(
    api_key="sk-or-v1-...",
    base_url="https://openrouter.ai/api/v1"
)

# DeepSeek（高性能）
model = OpenAI(
    api_key="sk-...",
    base_url="https://api.deepseek.com/v1"
)
```

### 性能优化的执行模式

```python
# 深度研究模式（推荐用于复杂分析）
result = controller.run(
    messages, tool_manager,
    deep_thinking=True,   # 全面任务分析
    summary=True,         # 带见解的详细总结
    deep_research=True    # 完整多智能体流水线
)

# 标准模式（平衡性能）
result = controller.run(
    messages, tool_manager,
    deep_thinking=True,   # 任务分析
    summary=True,         # 总结生成
    deep_research=False   # 分析后直接执行
)

# 快速模式（最大速度）
result = controller.run(
    messages, tool_manager,
    deep_thinking=False,  # 跳过分析
    deep_research=False   # 直接执行
)
```

### 带监控的实时流式处理

```python
import time

start_time = time.time()
total_tokens = 0

print("🔄 带实时监控的流式执行:")

for chunk in controller.run_stream(messages, tool_manager, deep_thinking=True):
    for message in chunk:
        print(f"🤖 [{message.get('type', 'unknown')}] {message['role']}: {message.get('content', '')[:100]}...")
        
        # 实时跟踪token使用
        if 'usage' in message:
            total_tokens += message['usage'].get('total_tokens', 0)
            elapsed = time.time() - start_time
            print(f"   💰 Tokens: {total_tokens} | ⏱️  时间: {elapsed:.1f}s")

print(f"\n✅ 流式处理完成！最终token计数: {total_tokens}")
```

## 🛠️ 高级自定义工具

创建具有增强功能的生产就绪自定义工具：

```python
# custom_tools/advanced_weather_tool.py
from sagents.tool.tool_base import tool
from typing import Dict, Any
import time

class WeatherAnalysisTool:
    """带缓存和验证的高级天气分析工具"""

    @tool(
        description_i18n={
            "zh": "获取带预测和趋势的全面天气分析",
            "en": "Get comprehensive weather analysis with forecasts and trends"
        },
        param_description_i18n={
            "city": {"zh": "城市名称", "en": "Name of the city"},
            "days": {"zh": "预测天数 (1-7)", "en": "Number of forecast days (1-7)"},
            "include_trends": {"zh": "包含历史趋势分析", "en": "Include historical trends analysis"}
        }
    )
    def weather_analysis(
        self,
        city: str,
        days: int = 3,
        include_trends: bool = False
    ) -> Dict[str, Any]:
        """执行带增强错误处理的天气分析"""
        start_time = time.time()
        
        try:
            # 您的天气API逻辑在这里
            weather_data = self._fetch_weather_data(city, days)
            
            result = {
                "success": True,
                "city": city,
                "current_weather": weather_data["current"],
                "forecast": weather_data["forecast"][:days],
                "metadata": {
                    "execution_time": time.time() - start_time,
                    "data_source": "OpenWeatherMap",
                    "cache_used": False
                }
            }
            
            if include_trends:
                result["trends"] = self._analyze_trends(city)
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "error_type": type(e).__name__,
                "city": city,
                "metadata": {
                    "execution_time": time.time() - start_time
                }
            }
    
    def _fetch_weather_data(self, city: str, days: int) -> Dict[str, Any]:
        # 模拟实现 - 用真实API替换
        return {
            "current": f"{city}晴朗，72°F",
            "forecast": [f"第{i+1}天: 多云" for i in range(days)]
        }
    
    def _analyze_trends(self, city: str) -> Dict[str, Any]:
        # 模拟趋势分析
        return {"trend": "变暖", "confidence": 0.85}
```

## 📊 Token成本优化

### 监控和控制成本

```python
# 设置token使用限制
controller.set_token_limits(
    max_tokens_per_request=4000,
    max_total_tokens=50000,
    cost_alert_threshold=1.00  # $1.00时警报
)

# 跨不同模型跟踪成本
cost_tracker = controller.get_cost_tracker()
print(f"当前会话成本: ${cost_tracker.get_session_cost():.4f}")

# 导出详细使用情况供账单使用
controller.export_token_usage("usage_report.csv")
```

## 🎯 下一步

1. **[架构指南](ARCHITECTURE_CN.md)** - 了解Sage内部工作原理
2. **[工具开发](TOOL_DEVELOPMENT_CN.md)** - 构建强大的自定义工具
3. **[高级配置](CONFIGURATION_CN.md)** - 微调性能
4. **[生产部署](../app/production_setup.py)** - 部署到生产环境
5. **[API参考](API_REFERENCE_CN.md)** - 完整API文档

## 🔍 故障排除

### 常见问题

**Token跟踪显示0:**
```bash
# 确保您使用兼容的API端点
export OPENAI_API_VERSION="2024-02-15-preview"
```

**执行缓慢:**
```python
# 启用性能监控
controller.enable_performance_monitoring()
perf_stats = controller.get_performance_stats()
print("瓶颈:", perf_stats['bottlenecks'])
```

**内存问题:**
```python
# 定期重置token统计
controller.reset_all_token_stats()
```

## 💡 专业提示

- **使用流式处理** 用于长时间运行的任务以查看进度
- **监控token使用** 以优化成本
- **启用性能跟踪** 以识别瓶颈
- **根据任务复杂性使用适当的执行模式**
- **利用MCP服务器** 进行外部工具集成

---

**🎉 恭喜！** 您现在已准备好使用Sage构建强大的多智能体应用程序。查看我们的[示例](../app/)以了解更多高级用例！ 
