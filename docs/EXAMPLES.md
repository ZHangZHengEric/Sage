---
layout: default
title: Examples & Use Cases
nav_order: 10
description: "Practical app and use cases for the Sage Multi-Agent Framework"
---

{: .note }
> Looking for the Chinese version? Check out [示例和用例](EXAMPLES_CN.html)

## Table of Contents
{: .no_toc .text-delta }

1. TOC
{:toc}

# 🎯 Examples and Use Cases

This document provides practical app for using Sage Multi-Agent Framework in various scenarios.

## 📋 Table of Contents

- [Getting Started Examples](#-getting-started-app)
- [Research and Analysis](#-research-and-analysis)
- [Problem Solving](#-problem-solving)
- [Custom Tool Examples](#-custom-tool-app)
- [Configuration Examples](#-configuration-app)
- [Real-world Applications](#-real-world-applications)

## 🚀 Getting Started Examples

### Basic Query Processing

```python
from agents.agent.agent_controller import AgentController
from agents.tool.tool_manager import ToolManager
from openai import OpenAI

# Initialize
model = OpenAI(api_key="your-api-key")
tool_manager = ToolManager()
controller = AgentController(model, {"model": "gpt-4", "temperature": 0.7})

# Simple query
messages = [{"role": "user", "content": "What are the benefits of renewable energy?", "type": "normal"}]
result = controller.run(messages, tool_manager)
print(result['final_output']['content'])
```

### Streaming Response

```python
# Real-time streaming
messages = [{"role": "user", "content": "Analyze current AI trends", "type": "normal"}]

for chunk in controller.run_stream(messages, tool_manager):
    for message in chunk:
        print(f"[{message['role']}] {message['content'][:100]}...")
```

## 🔍 Research and Analysis

### Market Research Example

```python
# Comprehensive market research
messages = [{
    "role": "user",
    "content": "Conduct a market analysis for electric vehicles in 2024. Include market size, key players, trends, and future outlook.",
    "type": "normal"
}]

result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,    # Enable task analysis
    summary=True,          # Generate comprehensive summary
    deep_research=True     # Use full agent pipeline
)

print("Market Research Results:")
print(result['final_output']['content'])
```

### Technical Analysis

```python
# Code review and optimization suggestions
messages = [{
    "role": "user", 
    "content": """
    Review this Python code and suggest optimizations:
    
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
print("Code Review:")
print(result['final_output']['content'])
```

## 💡 Problem Solving

### Business Strategy

```python
# Strategic planning assistance
messages = [{
    "role": "user",
    "content": "Help me create a go-to-market strategy for a new AI-powered productivity app targeting small businesses.",
    "type": "normal"
}]

result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,
    max_loop_count=15  # Allow more planning iterations
)
```

### Technical Problem Solving

```python
# Debugging assistance
messages = [{
    "role": "user",
    "content": "My Python web application is running slowly. It uses Flask, PostgreSQL, and Redis. Help me identify potential performance bottlenecks and solutions.",
    "type": "normal"
}]

result = controller.run(messages, tool_manager, deep_research=True)
```

## 🛠️ Custom Tool Examples

### Calculator Tool (Built-in Example)

```python
from sagents.tool.tool_base import tool

class Calculator:
    """A collection of mathematical calculation tools"""
    
    @tool()
    def calculate(self, expression: str) -> dict:
        """
        Evaluate a mathematical expression
        
        Args:
            expression: The mathematical expression to evaluate
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
        Calculate the factorial of a number
        
        Args:
            n: The number to calculate factorial for
        """
        try:
            import math
            if n < 0:
                raise ValueError("Factorial is only defined for non-negative integers")
            result = math.factorial(n)
            return {"result": result, "input": n, "status": "success"}
        except Exception as e:
            return {"error": str(e), "input": n, "status": "error"}
```

### Custom API Tool

```python
from sagents.tool.tool_base import tool
import requests

class APITool:
    """Example API integration tool"""
    
    @tool()
    def fetch_data(self, url: str, method: str = "GET") -> dict:
        """
        Fetch data from an API endpoint
        
        Args:
            url: The API endpoint URL
            method: HTTP method (GET, POST, etc.)
        """
        try:
            response = requests.request(method, url, timeout=30)
            return {
                "status_code": response.status_code,
                "data": response.text[:1000],  # Limit response size
                "success": True
            }
        except Exception as e:
            return {
                "error": str(e),
                "success": False
            }
```

## ⚙️ Configuration Examples

### Production Configuration

```python
# Production setup with error handling
from agents.config.settings import Settings, get_settings

# Get default settings
settings = get_settings()

# Production configuration
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

### Multi-Environment Setup

```python
import os

# Environment-specific configuration
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

## 🌍 Real-world Applications

### Content Creation Pipeline

```python
# Blog post creation workflow
messages = [{
    "role": "user",
    "content": "Create a comprehensive blog post about sustainable computing practices. Include an outline, research key points, and write the full article with actionable tips.",
    "type": "normal"
}]

# Use full pipeline for comprehensive content
result = controller.run(
    messages,
    tool_manager, 
    deep_thinking=True,
    summary=True,
    max_loop_count=20
)

print("Generated Blog Post:")
print(result['final_output']['content'])
```

### Data Analysis Workflow

```python
# Analyze data
messages = [{
    "role": "user",
    "content": "Analyze this data and provide insights on trends and recommendations: [Your data here]",
    "type": "normal"
}]

result = controller.run(
    messages, 
    tool_manager,
    deep_thinking=True,    # Enable task analysis
    summary=True,          # Generate comprehensive summary
    deep_research=True     # Use full agent pipeline
)
```

### Customer Support Automation

```python
# Intelligent customer support
def handle_support_request(customer_query: str, customer_history: str = ""):
    messages = [
        {"role": "system", "content": "You are a helpful customer support agent.", "type": "normal"},
        {"role": "user", "content": f"Customer Query: {customer_query}\nHistory: {customer_history}", "type": "normal"}
    ]
    
    result = controller.run(
        messages,
        tool_manager,
        deep_thinking=False,  # Quick response for support
        summary=False
    )
    
    return result['final_output']['content']

# Usage
response = handle_support_request(
    "I can't log into my account",
    "Premium customer since 2020, last login 3 days ago"
)
```

## 🔄 Advanced Patterns

### Batch Processing

```python
# Process multiple queries efficiently
queries = [
    "Summarize latest AI research papers",
    "Analyze market trends for electric vehicles", 
    "Create a project timeline for mobile app development"
]

results = []
for query in queries:
    messages = [{"role": "user", "content": query, "type": "normal"}]
    result = controller.run(messages, tool_manager, deep_thinking=True)
    results.append(result['final_output']['content'])

print("Batch Processing Results:")
for i, result in enumerate(results):
    print(f"\nQuery {i+1}: {queries[i]}")
    print(f"Result: {result[:200]}...")
```

### Error Handling and Retry

```python
from agents.utils.exceptions import SageException
import time

def robust_query(query: str, max_retries: int = 3):
    """Execute query with retry logic"""
    
    for attempt in range(max_retries):
        try:
            messages = [{"role": "user", "content": query, "type": "normal"}]
            result = controller.run(messages, tool_manager)
            return result['final_output']['content']
            
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                raise
    
# Usage
try:
    response = robust_query("Analyze current market conditions")
    print(response)
except Exception as e:
    print(f"Failed after all retries: {e}")
```

## 🧪 Testing Examples

### Unit Testing

```python
import pytest
from unittest.mock import Mock

def test_agent_controller():
    """Test agent controller basic functionality"""
    mock_model = Mock()
    mock_model.chat.completions.create.return_value.choices = [
        Mock(message=Mock(content="Test response"))
    ]
    
    controller = AgentController(mock_model, {"model": "gpt-4"})
    
    messages = [{"role": "user", "content": "Test query", "type": "normal"}]
    result = controller.run(messages)
    
    assert result is not None
    assert 'final_output' in result
```

### Integration Testing

```python
def test_full_workflow():
    """Test complete workflow integration"""
    # This requires actual API key for integration testing
    if not os.getenv('OPENAI_API_KEY'):
        pytest.skip("API key not available")
    
    model = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    tool_manager = ToolManager()
    controller = AgentController(model, {"model": "gpt-3.5-turbo"})
    
    messages = [{"role": "user", "content": "What is 2+2?", "type": "normal"}]
    result = controller.run(messages, tool_manager)
    
    assert "4" in result['final_output']['content']
```

## 📊 Performance Monitoring

```python
import time
from typing import Dict, Any

def measure_performance(query: str) -> Dict[str, Any]:
    """Measure execution performance"""
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

# Usage
performance = measure_performance("Explain quantum computing")
print(f"Execution time: {performance['execution_time']:.2f} seconds")
print(f"Messages generated: {performance['message_count']}")
```

## 📝 Notes on API Parameters

### AgentController.run() Parameters

The `run()` method supports the following parameters:

- `input_messages`: List of message dictionaries (required)
- `tool_manager`: ToolManager instance (optional)
- `session_id`: Session identifier (optional)
- `deep_thinking`: Enable task analysis phase (default: True)
- `summary`: Enable task summary phase (default: True)
- `max_loop_count`: Maximum planning-execution-observation loops (default: 10)
- `deep_research`: Enable full agent pipeline vs direct execution (default: True)

### AgentController.run_stream() Parameters

The `run_stream()` method supports the same parameters as `run()` and yields message chunks for real-time processing.

These app demonstrate the flexibility and power of Sage Multi-Agent Framework. Start with simple app and gradually explore more complex use cases as you become familiar with the system. 
