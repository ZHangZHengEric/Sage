---
layout: default
title: Tool Development
nav_order: 6
description: "Current tool development guide for Sage"
has_children: false
---

{: .note }
> Looking for Chinese? See [工具开发指南](TOOL_DEVELOPMENT_CN.html).

# Tool Development Guide

This guide documents the tool APIs that are present in the current codebase.

## 1. Tool Types In The Current Repo

Sage currently exposes two main code-level tool definitions:

1. standard Python tools via `@tool`
2. built-in MCP-style tools via `@sage_mcp_tool`

The relevant implementations are:

- [`sagents/tool/tool_base.py`](../sagents/tool/tool_base.py)
- [`sagents/tool/mcp_tool_base.py`](../sagents/tool/mcp_tool_base.py)
- [`sagents/tool/tool_manager.py`](../sagents/tool/tool_manager.py)

## 2. Standard Tool With `@tool`

Use `@tool()` for normal Python tools discovered by `ToolManager`.

```python
from sagents.tool.tool_base import tool


class CalculatorTool:
    @tool()
    def add(self, a: int, b: int) -> dict:
        """
        Add two integers.

        Args:
            a: First integer
            b: Second integer
        """
        return {"result": a + b}
```

What the decorator does:

- parses the docstring
- infers JSON-schema-like parameter types from annotations
- records required parameters
- registers metadata for discovery

## 3. Useful `@tool()` Options

The current decorator supports these optional keyword arguments:

- `description_i18n`
- `param_description_i18n`
- `return_data`
- `return_properties_i18n`
- `param_schema`
- `disabled`

Example:

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
        Search documents.

        Args:
            query: Query text
        """
        return {"items": []}
```

## 4. Built-in MCP Tool With `@sage_mcp_tool`

Use `@sage_mcp_tool(server_name=...)` when you want a built-in MCP-style tool that is registered under a named MCP server surface.

```python
from sagents.tool.mcp_tool_base import sage_mcp_tool


@sage_mcp_tool(server_name="demo")
def get_status(name: str) -> dict:
    """
    Get demo status.

    Args:
        name: Target name
    """
    return {"name": name, "status": "ok"}
```

The decorator:

- parses docstrings and type hints
- creates a `SageMcpToolSpec`
- stores the tool in the MCP discovery registry

## 5. Discovery And Registration

`ToolManager` in [`sagents/tool/tool_manager.py`](../sagents/tool/tool_manager.py) is responsible for discovery.

```python
from sagents.tool import ToolManager

tool_manager = ToolManager()
```

Current behavior:

- discovers Python tools from the tool package
- discovers built-in MCP tools
- can initialize external MCP servers later

## 6. Writing Good Tools

Recommendations that fit the current runtime:

- keep parameters strongly typed
- write clear Google-style docstrings
- return JSON-serializable data
- keep outputs bounded; large outputs may be truncated by the tool manager
- avoid hidden side effects unless the tool is explicitly meant to change state

## 7. Example: Tool Returning Structured Data

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
        List files under a directory.

        Args:
            root: Directory path
        """
        import os
        return {"files": sorted(os.listdir(root))}
```

## 8. Where To Put Tools

For project-specific tools, keep them in a Python package that your runtime can import, then ensure the relevant directory is available to the tool loader or use the server-side tool management surfaces.

## 9. Notes

- Do not use older examples that import `agents.tool.tool_manager`.
- Do not rely on older docs that mention `agents.config` or other removed config helpers.
- For current behavior, prefer reading the three source files linked at the top of this page.
