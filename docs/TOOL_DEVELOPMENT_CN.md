---
layout: default
title: 工具开发指南
nav_order: 7
description: "当前 Sage 工具开发指南"
has_children: false
---

{: .note }
> 英文版本请查看 [Tool Development](TOOL_DEVELOPMENT.html)。

# 工具开发指南

本文档只描述当前代码库里仍然有效的 Tool 开发接口。

## 1. 当前仓库里的 Tool 类型

目前主要有两类代码级 Tool 定义方式：

1. 通过 `@tool` 定义标准 Python 工具
2. 通过 `@sage_mcp_tool` 定义内置 MCP 风格工具

相关实现文件：

- [`sagents/tool/tool_base.py`](../sagents/tool/tool_base.py)
- [`sagents/tool/mcp_tool_base.py`](../sagents/tool/mcp_tool_base.py)
- [`sagents/tool/tool_manager.py`](../sagents/tool/tool_manager.py)

## 2. 使用 `@tool` 定义标准工具

普通 Python 工具建议使用 `@tool()`，由 `ToolManager` 自动发现。

```python
from sagents.tool.tool_base import tool


class CalculatorTool:
    @tool()
    def add(self, a: int, b: int) -> dict:
        """
        两个整数求和。

        Args:
            a: 第一个整数
            b: 第二个整数
        """
        return {"result": a + b}
```

当前装饰器会自动做这些事：

- 解析 docstring
- 根据类型注解推断参数 schema
- 记录必填参数
- 把元数据注册到发现系统

## 3. `@tool()` 支持的常用参数

当前支持的可选参数包括：

- `description_i18n`
- `param_description_i18n`
- `return_data`
- `return_properties_i18n`
- `param_schema`
- `disabled`

示例：

```python
from sagents.tool.tool_base import tool


class SearchTool:
    @tool(
        description_i18n={"zh": "搜索文档", "en": "Search documents"},
        param_description_i18n={
            "query": {"zh": "查询内容", "en": "Search query"}
        },
    )
    def search(self, query: str) -> dict:
        """
        搜索文档。

        Args:
            query: 查询文本
        """
        return {"items": []}
```

## 4. 使用 `@sage_mcp_tool` 定义内置 MCP 工具

如果你要定义一个挂到某个 MCP server 名称下的内置工具，使用 `@sage_mcp_tool(server_name=...)`。

```python
from sagents.tool.mcp_tool_base import sage_mcp_tool


@sage_mcp_tool(server_name="demo")
def get_status(name: str) -> dict:
    """
    获取 demo 状态。

    Args:
        name: 目标名称
    """
    return {"name": name, "status": "ok"}
```

当前行为：

- 解析 docstring 和类型注解
- 生成 `SageMcpToolSpec`
- 注册到内置 MCP 工具发现表

## 5. 发现与注册

[`sagents/tool/tool_manager.py`](../sagents/tool/tool_manager.py) 中的 `ToolManager` 负责发现和管理工具。

```python
from sagents.tool import ToolManager

tool_manager = ToolManager()
```

当前会自动：

- 发现 Python Tool
- 发现内置 MCP Tool
- 后续初始化外部 MCP Server

## 6. 编写工具的建议

在当前运行时里，建议遵循这些约束：

- 参数尽量使用明确类型
- docstring 使用清晰的 Google 风格
- 返回值保持 JSON 可序列化
- 输出不要无限增大，过长内容会被工具管理器截断
- 除非工具本身就是副作用型，否则避免隐藏状态变更

## 7. 返回结构化数据的示例

```python
from sagents.tool.tool_base import tool


class RepoTool:
    @tool(
        return_data={
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"}}
            }
        }
    )
    def list_files(self, root: str) -> dict:
        """
        列出目录下文件。

        Args:
            root: 目录路径
        """
        import os
        return {"files": sorted(os.listdir(root))}
```

## 8. 工具代码放哪里

项目自定义工具应放在运行时可导入的 Python 包内，然后确保对应目录会被工具加载器发现，或者通过服务端工具管理接口接入。

## 9. 说明

- 不要再使用 `agents.tool.tool_manager` 这类旧路径。
- 不要再参考依赖 `agents.config` 的旧文档示例。
- 如果要看当前真实行为，以上 3 个源码文件比旧文档更权威。
