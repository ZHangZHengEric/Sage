---
layout: default
title: 示例和用例
nav_order: 11
description: "Sage多智能体框架的实际示例和用例"
---

{: .note }
> 需要英文版本？请查看 [Examples & Use Cases](EXAMPLES.html)

## 目录
{: .no_toc .text-delta }

1. TOC
{:toc}

# 🎯 示例和用例

本文档提供在各种场景中使用 Sage 多智能体框架的实际示例。

## 📋 目录

- [入门示例](#-入门示例)
- [研究和分析](#-研究和分析)
- [问题解决](#-问题解决)
- [自定义工具示例](#-自定义工具示例)
- [配置示例](#-配置示例)
- [实际应用](#-实际应用)

## 🚀 入门示例

### 基本查询处理

```python
from agents.agent.agent_controller import AgentController
from agents.tool.tool_manager import ToolManager
from openai import OpenAI

# 初始化
model = OpenAI(api_key="your-api-key")
tool_manager = ToolManager()
controller = AgentController(model, {"model": "gpt-4", "temperature": 0.7})

# 简单查询
messages = [{"role": "user", "content": "可再生能源有什么好处？", "type": "normal"}]
result = controller.run(messages, tool_manager)
print(result['final_output']['content'])
```

### 流式响应

```python
# 实时流式输出
messages = [{"role": "user", "content": "分析当前AI趋势", "type": "normal"}]

for chunk in controller.run_stream(messages, tool_manager):
    for message in chunk:
        print(f"[{message['role']}] {message['content'][:100]}...")
```

## 🔍 研究和分析

### 市场研究示例

```python
# 全面的市场研究
messages = [{
    "role": "user",
    "content": "对2024年电动汽车市场进行分析。包括市场规模、主要参与者、趋势和未来展望。",
    "type": "normal"
}]

result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,    # 启用任务分析
    summary=True,          # 生成全面总结
    deep_research=True     # 使用完整智能体流水线
)

print("市场研究结果:")
print(result['final_output']['content'])
```

### 技术分析

```python
# 代码审查和优化建议
messages = [{
    "role": "user", 
    "content": """
    审查这段Python代码并提出优化建议:
    
    def process_data(data):
        result = []
        for item in data:
            if item > 0:
                result.append(item * 2)
        return result
    """,
    "type": "normal"
}]

result = controller.run(messages, tool_manager, deep_thinking=True)
print("代码审查:")
print(result['final_output']['content'])
```

## 💡 问题解决

### 业务策略

```python
# 战略规划协助
messages = [{
    "role": "user",
    "content": "帮我为一个针对小企业的新AI驱动生产力应用制定上市策略。",
    "type": "normal"
}]

result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,
    max_loop_count=15  # 允许更多规划循环
)
```

### 技术问题解决

```python
# 调试协助
messages = [{
    "role": "user",
    "content": "我的Python网络应用运行缓慢。它使用Flask、PostgreSQL和Redis。帮我识别潜在的性能瓶颈和解决方案。",
    "type": "normal"
}]

result = controller.run(messages, tool_manager, deep_research=True)
```

## 🛠️ 自定义工具示例

### 计算器工具（内置示例）

```python
from sagents.tool.tool_base import tool

class Calculator:
    """数学计算工具集合"""
    
    @tool()
    def calculate(self, expression: str) -> dict:
        """
        计算数学表达式
        
        Args:
            expression: 要计算的数学表达式
        """
        try:
            import math
            result = eval(expression, {"__builtins__": None}, {
                "math": math, "sqrt": math.sqrt, "sin": math.sin,
                "cos": math.cos, "tan": math.tan, "pi": math.pi, "e": math.e
            })
            return {"result": result, "expression": expression, "status": "success"}
        except Exception as e:
            return {"error": str(e), "expression": expression, "status": "error"}

    @tool()
    def factorial(self, n: int) -> dict:
        """
        计算阶乘
        
        Args:
            n: 要计算阶乘的数字
        """
        try:
            import math
            if n < 0:
                raise ValueError("阶乘只对非负整数定义")
            result = math.factorial(n)
            return {"result": result, "input": n, "status": "success"}
        except Exception as e:
            return {"error": str(e), "input": n, "status": "error"}
```

### 自定义API工具

```python
from sagents.tool.tool_base import tool
import requests

class APITool:
    """API集成工具示例"""
    
    @tool()
    def fetch_data(self, url: str, method: str = "GET") -> dict:
        """
        从API端点获取数据
        
        Args:
            url: API端点URL
            method: HTTP方法（GET、POST等）
        """
        try:
            response = requests.request(method, url, timeout=30)
            return {
                "status_code": response.status_code,
                "data": response.text[:1000],  # 限制响应大小
                "success": True
            }
        except Exception as e:
            return {
                "error": str(e),
                "success": False
            }
```

## ⚙️ 配置示例

### 生产配置

```python
# 带错误处理的生产设置
from agents.config.settings import Settings, get_settings

# 获取默认设置
settings = get_settings()

# 生产配置
production_config = {
    "model": "gpt-4",
    "temperature": 0.3,
    "max_tokens": 8192,
    "timeout": 120
}

controller = AgentController(
    model=model,
    model_config=production_config
)
```

### 多环境设置

```python
import os

# 环境特定配置
env = os.getenv('SAGE_ENVIRONMENT', 'development')

if env == 'production':
    config = {
        "model": "gpt-4",
        "temperature": 0.2,
        "max_tokens": 8192
    }
elif env == 'development':
    config = {
        "model": "gpt-3.5-turbo", 
        "temperature": 0.7,
        "max_tokens": 4096
    }

controller = AgentController(model, config)
```

## 🌍 实际应用

### 内容创建流水线

```python
# 博客文章创建工作流
messages = [{
    "role": "user",
    "content": "创建一篇关于可持续计算实践的综合博客文章。包括大纲、研究要点和带有可执行建议的完整文章。",
    "type": "normal"
}]

# 使用完整流水线进行综合内容创建
result = controller.run(
    messages,
    tool_manager, 
    deep_thinking=True,
    summary=True,
    max_loop_count=20
)

print("生成的博客文章:")
print(result['final_output']['content'])
```

### 数据分析工作流

```python
# 分析数据
messages = [{
    "role": "user",
    "content": "分析这些数据并提供趋势洞察和建议：[您的数据在这里]",
    "type": "normal"
}]

result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,    # 启用任务分析
    summary=True,          # 生成全面总结
    deep_research=True     # 使用完整智能体流水线
)
```

### 客户支持自动化

```python
# 智能客户支持
def handle_support_request(customer_query: str, customer_history: str = ""):
    messages = [
        {"role": "system", "content": "您是一个有用的客户支持代理。", "type": "normal"},
        {"role": "user", "content": f"客户查询: {customer_query}\n历史: {customer_history}", "type": "normal"}
    ]
    
    result = controller.run(
        messages,
        tool_manager,
        deep_thinking=False,  # 支持需要快速响应
        summary=False
    )
    
    return result['final_output']['content']

# 使用方法
response = handle_support_request(
    "我无法登录我的账户",
    "2020年以来的高级客户，3天前最后一次登录"
)
```

## 🔄 高级模式

### 批处理

```python
# 高效处理多个查询
queries = [
    "总结最新的AI研究论文",
    "分析电动汽车的市场趋势", 
    "为移动应用开发创建项目时间线"
]

results = []
for query in queries:
    messages = [{"role": "user", "content": query, "type": "normal"}]
    result = controller.run(messages, tool_manager, deep_thinking=True)
    results.append(result['final_output']['content'])

print("批处理结果:")
for i, result in enumerate(results):
    print(f"\n查询 {i+1}: {queries[i]}")
    print(f"结果: {result[:200]}...")
```

### 错误处理和重试

```python
import time

def robust_query(query: str, max_retries: int = 3):
    """带重试逻辑的查询执行"""
    
    for attempt in range(max_retries):
        try:
            messages = [{"role": "user", "content": query, "type": "normal"}]
            result = controller.run(messages, tool_manager)
            return result['final_output']['content']
            
        except Exception as e:
            print(f"尝试 {attempt + 1} 失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 指数退避
            else:
                raise
    
# 使用方法
try:
    response = robust_query("分析当前市场状况")
    print(response)
except Exception as e:
    print(f"所有重试后失败: {e}")
```

## 🧪 测试示例

### 单元测试

```python
import pytest
from unittest.mock import Mock

def test_agent_controller():
    """测试智能体控制器基本功能"""
    mock_model = Mock()
    mock_model.chat.completions.create.return_value.choices = [
        Mock(message=Mock(content="测试响应"))
    ]
    
    controller = AgentController(mock_model, {"model": "gpt-4"})
    
    messages = [{"role": "user", "content": "测试查询", "type": "normal"}]
    result = controller.run(messages)
    
    assert result is not None
    assert 'final_output' in result
```

### 集成测试

```python
def test_full_workflow():
    """测试完整工作流集成"""
    # 集成测试需要实际的API密钥
    if not os.getenv('OPENAI_API_KEY'):
        pytest.skip("API密钥不可用")
    
    model = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    tool_manager = ToolManager()
    controller = AgentController(model, {"model": "gpt-3.5-turbo"})
    
    messages = [{"role": "user", "content": "2+2等于多少？", "type": "normal"}]
    result = controller.run(messages, tool_manager)
    
    assert "4" in result['final_output']['content']
```

## 📊 性能监控

```python
import time
from typing import Dict, Any

def measure_performance(query: str) -> Dict[str, Any]:
    """测量执行性能"""
    start_time = time.time()
    
    messages = [{"role": "user", "content": query, "type": "normal"}]
    result = controller.run(messages, tool_manager)
    
    end_time = time.time()
    execution_time = end_time - start_time
    
    return {
        "result": result,
        "execution_time": execution_time,
        "message_count": len(result.get('new_messages', [])),
        "success": result.get('final_output') is not None
    }

# 使用方法
performance = measure_performance("解释量子计算")
print(f"执行时间: {performance['execution_time']:.2f} 秒")
print(f"生成的消息数: {performance['message_count']}")
```

## 📝 API参数说明

### AgentController.run() 参数

`run()` 方法支持以下参数：

- `input_messages`: 消息字典列表（必需）
- `tool_manager`: ToolManager实例（可选）
- `session_id`: 会话标识符（可选）
- `deep_thinking`: 启用任务分析阶段（默认：True）
- `summary`: 启用任务总结阶段（默认：True）
- `max_loop_count`: 最大规划-执行-观察循环次数（默认：10）
- `deep_research`: 启用完整智能体流水线vs直接执行（默认：True）

### AgentController.run_stream() 参数

`run_stream()` 方法支持与 `run()` 相同的参数，并为实时处理生成消息块。

这些示例展示了 Sage 多智能体框架的灵活性和强大功能。从简单的示例开始，随着对系统的熟悉逐渐探索更复杂的用例。 
