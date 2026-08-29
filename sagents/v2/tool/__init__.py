"""SAgents V2 module for tool/__init__.py."""

from sagents.v2.tool.contracts import (
    CancelSemantics,
    IdempotencyStrategy,
    ReconcileResult,
    ReconcileState,
    ResumeStrategy,
    SideEffectLevel,
    ToolCall,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.plugins.ephemeral import (
    InMemoryToolCatalog,
    InMemoryToolExecutor,
)
from sagents.v2.tool.composite import (
    CompositeToolCatalog,
    CompositeToolExecutor,
    ExcludingToolCatalog,
    FilteredToolCatalog,
    RoutedToolExecutor,
)
from sagents.v2.tool.provider import ToolCatalog, ToolExecutor
from sagents.v2.tool.decorators import decorated_tool_definition, tool
from sagents.v2.tool.decorated import DecoratedToolProvider, ToolInvocation
from sagents.v2.tool.plugins.mcp import McpServerConfig, McpToolPlugin

__all__ = [
    "CancelSemantics",
    "CompositeToolCatalog",
    "CompositeToolExecutor",
    "DecoratedToolProvider",
    "ExcludingToolCatalog",
    "FilteredToolCatalog",
    "IdempotencyStrategy",
    "InMemoryToolCatalog",
    "InMemoryToolExecutor",
    "ReconcileResult",
    "ReconcileState",
    "ResumeStrategy",
    "RoutedToolExecutor",
    "SideEffectLevel",
    "ToolCall",
    "ToolCatalog",
    "ToolDefinition",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolInvocation",
    "decorated_tool_definition",
    "tool",
    "McpServerConfig",
    "McpToolPlugin",
]
