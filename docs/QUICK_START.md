---
layout: default
title: Quick Start Guide
nav_order: 2
description: "Get started with Sage Multi-Agent Framework in just 5 minutes"
---

# 🚀 Quick Start Guide

Get up and running with Sage Multi-Agent Framework in minutes!

## 📦 Installation

### Prerequisites

- Python 3.10 or higher
- pip package manager
- Git

### Clone and Setup

```bash
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage
pip install -r requirements.txt
```

## Table of Contents
{: .no_toc .text-delta }

1. TOC
{:toc}

## 📋 Prerequisites

- **Python 3.10+** installed on your system
- **OpenAI API key** or compatible API endpoint (OpenRouter, DeepSeek, etc.)
- **Git** for cloning the repository

## ⚡ 5-Minute Setup

### 1. Clone and Install

```bash
# Clone the repository
git clone https://github.com/ZHangZHengEric/Sage.git
cd Sage

# Install dependencies
pip install -r requirements.txt
```

### 2. Set Environment Variables

```bash
# Option 1: Set environment variables
export OPENAI_API_KEY="your-api-key-here"
export SAGE_DEBUG=true
export SAGE_MAX_LOOP_COUNT=10

# Option 2: Create .env file (recommended)
cat > .env << EOF
OPENAI_API_KEY=your-api-key-here
SAGE_DEBUG=true
SAGE_ENVIRONMENT=development
SAGE_MAX_LOOP_COUNT=10
SAGE_TOOL_TIMEOUT=30
EOF
```

### 3. Run Your First Demo

```bash
# Web interface with enhanced features (recommended)
streamlit run app/sage_demo.py -- \
  --api_key $OPENAI_API_KEY \
  --model mistralai/mistral-small-3.1-24b-instruct:free \
  --base_url https://openrouter.ai/api/v1

# Command line interface
python app/multi_turn_demo.py
```

🎉 **That's it!** You should now see the Sage web interface running at `http://localhost:8501` with real-time token tracking!

## 🎮 Using the Web Interface

### Enhanced Features (v0.9)

1. **💬 Chat Interface**: Type your questions in natural language
2. **⚙️ Advanced Settings**: Configure agents, models, and performance options
3. **🛠️ Tool Explorer**: Browse available tools with auto-discovery
4. **📊 Token Monitoring**: Real-time token usage and cost tracking
5. **📈 Performance Dashboard**: Monitor execution times and bottlenecks
6. **🔄 Streaming Visualization**: Watch agents work in real-time

### Example Interactions

Try these example prompts to see Sage's enhanced capabilities:

```
🔍 Complex Research Task:
"Research the latest trends in artificial intelligence, analyze their impact on business, and provide actionable recommendations"

🧮 Advanced Analysis:
"Compare renewable energy sources across cost, efficiency, and environmental impact with detailed data analysis"

🛠️ Multi-step Problem Solving:
"Help me create a comprehensive marketing strategy for a new SaaS product, including market analysis, competitive positioning, and campaign planning"

📊 Data-Driven Task:
"Calculate the financial projections for a startup with different growth scenarios and investment requirements"
```

## 💻 Your First Python Script with Token Tracking

Create a modern script with enhanced monitoring:

```python
# my_first_sage_script.py
import os
import time
from agents.agent.agent_controller import AgentController
from agents.tool.tool_manager import ToolManager
from openai import OpenAI

def main():
    # Initialize components with enhanced configuration
    api_key = os.getenv('OPENAI_API_KEY')
    model = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1"  # Use OpenRouter for cost-effective access
    )
    tool_manager = ToolManager()
    
    # Create agent controller with production settings
    controller = AgentController(
        model, 
        {
            "model": "mistralai/mistral-small-3.1-24b-instruct:free",
            "temperature": 0.7,
            "max_tokens": 4096
        }
    )
    
    # Define your task
    messages = [{
        "role": "user", 
        "content": "Explain how multi-agent systems work and their applications in modern AI",
        "type": "normal"
    }]
    
    print("🚀 Starting Sage Multi-Agent execution...")
    start_time = time.time()
    
    # Execute with full pipeline and monitoring
    result = controller.run(
        messages, 
        tool_manager,
        deep_thinking=True,   # Enable comprehensive task analysis
        summary=True,         # Generate detailed summary
        deep_research=True    # Full multi-agent pipeline
    )
    
    execution_time = time.time() - start_time
    
    # Print results with enhanced information
    print("🎯 Final Output:")
    print(result['final_output']['content'])
    
    print(f"\n📊 Execution Summary:")
    print(f"  • Generated {len(result['new_messages'])} messages")
    print(f"  • Total execution time: {execution_time:.2f}s")
    
    # Display comprehensive token statistics
    print(f"\n💰 Token Usage Statistics:")
    controller.print_comprehensive_token_stats()
    
    # Get detailed statistics for further processing
    stats = controller.get_comprehensive_token_stats()
    print(f"\n📈 Cost Analysis:")
    print(f"  • Total tokens: {stats['total_tokens']}")
    print(f"  • Estimated cost: ${stats.get('estimated_cost', 0):.4f}")

if __name__ == "__main__":
    main()
```

Run it:
```bash
python my_first_sage_script.py
```

## 🔧 Enhanced Configuration Options

### API Providers with Optimal Settings

```python
# OpenAI (with streaming token tracking)
model = OpenAI(api_key="sk-...")

# OpenRouter (cost-effective, multiple models)
model = OpenAI(
    api_key="sk-or-v1-...",
    base_url="https://openrouter.ai/api/v1"
)

# DeepSeek (high performance)
model = OpenAI(
    api_key="sk-...",
    base_url="https://api.deepseek.com/v1"
)
```

### Execution Modes with Performance Optimization

```python
# Deep Research Mode (recommended for complex analysis)
result = controller.run(
    messages, tool_manager,
    deep_thinking=True,   # Comprehensive task analysis
    summary=True,         # Detailed summary with insights
    deep_research=True    # Full multi-agent pipeline
)

# Standard Mode (balanced performance)
result = controller.run(
    messages, tool_manager,
    deep_thinking=True,   # Task analysis
    summary=True,         # Summary generation
    deep_research=False   # Direct execution after analysis
)

# Rapid Mode (maximum speed)
result = controller.run(
    messages, tool_manager,
    deep_thinking=False,  # Skip analysis
    deep_research=False   # Direct execution
)
```

### Real-time Streaming with Monitoring

```python
import time

start_time = time.time()
total_tokens = 0

print("🔄 Streaming execution with real-time monitoring:")

for chunk in controller.run_stream(messages, tool_manager, deep_thinking=True):
    for message in chunk:
        print(f"🤖 [{message.get('type', 'unknown')}] {message['role']}: {message.get('show_content', '')[:100]}...")
        
        # Track token usage in real-time
        if 'usage' in message:
            total_tokens += message['usage'].get('total_tokens', 0)
            elapsed = time.time() - start_time
            print(f"   💰 Tokens: {total_tokens} | ⏱️  Time: {elapsed:.1f}s")

print(f"\n✅ Streaming completed! Final token count: {total_tokens}")
```

## 🛠️ Advanced Custom Tools

Create production-ready custom tools with enhanced features:

```python
# custom_tools/advanced_weather_tool.py
from sagents.tool.tool_base import tool
from typing import Dict, Any
import time

class WeatherAnalysisTool:
    """Advanced weather analysis tool with caching and validation"""

    @tool(
        description_i18n={
            "en": "Get comprehensive weather analysis with forecasts and trends",
            "zh": "获取包含预测与趋势的天气分析"
        },
        param_description_i18n={
            "city": {"en": "Name of the city", "zh": "城市名称"},
            "days": {"en": "Number of forecast days (1-7)", "zh": "预测天数（1-7）"},
            "include_trends": {"en": "Include historical trends analysis", "zh": "包含历史趋势分析"}
        }
    )
    def weather_analysis(
        self,
        city: str,
        days: int = 3,
        include_trends: bool = False
    ) -> Dict[str, Any]:
        """Execute weather analysis with enhanced error handling"""
        start_time = time.time()
        
        try:
            # Your weather API logic here
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
        # Mock implementation - replace with real API
        return {
            "current": f"Sunny, 72°F in {city}",
            "forecast": [f"Day {i+1}: Partly cloudy" for i in range(days)]
        }
    
    def _analyze_trends(self, city: str) -> Dict[str, Any]:
        # Mock trends analysis
        return {"trend": "warming", "confidence": 0.85}
```

## 📊 Token Cost Optimization

### Monitor and Control Costs

```python
# Set token usage limits
controller.set_token_limits(
    max_tokens_per_request=4000,
    max_total_tokens=50000,
    cost_alert_threshold=1.00  # Alert at $1.00
)

# Track costs across different models
cost_tracker = controller.get_cost_tracker()
print(f"Current session cost: ${cost_tracker.get_session_cost():.4f}")

# Export detailed usage for billing
controller.export_token_usage("usage_report.csv")
```

## 🎯 Next Steps

1. **[Architecture Guide](ARCHITECTURE.md)** - Understand how Sage works internally
2. **[Tool Development](TOOL_DEVELOPMENT.md)** - Build powerful custom tools
3. **[Advanced Configuration](CONFIGURATION.md)** - Fine-tune performance
4. **[Production Deployment](../app/production_setup.py)** - Deploy to production
5. **[API Reference](API_REFERENCE.md)** - Complete API documentation

## 🔍 Troubleshooting

### Common Issues

**Token tracking shows 0:**
```bash
# Ensure you're using compatible API endpoints
export OPENAI_API_VERSION="2024-02-15-preview"
```

**Slow execution:**
```python
# Enable performance monitoring
controller.enable_performance_monitoring()
perf_stats = controller.get_performance_stats()
print("Bottlenecks:", perf_stats['bottlenecks'])
```

**Memory issues:**
```python
# Reset token stats periodically
controller.reset_all_token_stats()
```

## 💡 Pro Tips

- **Use streaming** for long-running tasks to see progress
- **Monitor token usage** to optimize costs
- **Enable performance tracking** to identify bottlenecks
- **Use appropriate execution modes** based on task complexity
- **Leverage MCP servers** for external tool integration

---

**🎉 Congratulations!** You're now ready to build powerful multi-agent applications with Sage. Check out our [app](../app/) for more advanced use cases! 
