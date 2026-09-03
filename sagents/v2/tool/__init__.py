"""SAgents V2 module for tool/__init__.py."""

from sagents.v2._lazy import exported_names, resolve_export

from sagents.v2.tool.contracts import (
    CancelSemantics,
    IdempotencyStrategy,
    ReconcileResult,
    ReconcileState,
    ResumeStrategy,
    SideEffectLevel,
    ToolCall,
    ToolCancellationResult,
    ToolCancellationState,
    ToolDefinition,
    ToolExecutionResult,
)
from sagents.v2.tool.composite import (
    CompositeToolCatalog,
    CompositeToolExecutor,
    ExcludingToolCatalog,
    FilteredToolCatalog,
    InvocationGrantToolCatalog,
    RoutedToolExecutor,
)
from sagents.v2.tool.provider import CancellableToolExecutor, ToolCatalog, ToolExecutor
from sagents.v2.tool.decorators import decorated_tool_definition, tool
from sagents.v2.tool.decorated import DecoratedToolProvider, ToolInvocation
from sagents.v2.tool.localization import (
    localize_tool_definition,
    normalize_tool_language,
)
from sagents.v2.tool.selection import (
    DEFAULT_ALWAYS_VISIBLE_TOOLS,
    ToolSelectionConfig,
    ToolSelectionPolicy,
    ToolSelectionPrepareContext,
    ToolSelectionRequest,
    ToolSelectionResult,
)

_LAZY_EXPORTS = {
    "DirectToolSelectionPolicy": (
        "sagents.v2.tool.plugins.selection_direct",
        "DirectToolSelectionPolicy",
    ),
    "EphemeralToolPlugin": ("sagents.v2.tool.plugins.ephemeral", "EphemeralToolPlugin"),
    "InMemoryToolCatalog": ("sagents.v2.tool.plugins.ephemeral", "InMemoryToolCatalog"),
    "InMemoryToolExecutor": (
        "sagents.v2.tool.plugins.ephemeral",
        "InMemoryToolExecutor",
    ),
    "LLMToolSelectionPolicy": (
        "sagents.v2.tool.plugins.selection_llm",
        "LLMToolSelectionPolicy",
    ),
    "LexicalToolSelectionPolicy": (
        "sagents.v2.tool.plugins.selection_lexical",
        "LexicalToolSelectionPolicy",
    ),
    "McpServerConfig": ("sagents.v2.tool.plugins.mcp", "McpServerConfig"),
    "McpToolPlugin": ("sagents.v2.tool.plugins.mcp", "McpToolPlugin"),
    "RecentToolSelectionPolicy": (
        "sagents.v2.tool.plugins.selection_recent",
        "RecentToolSelectionPolicy",
    ),
}

__all__ = [
    "CancelSemantics",
    "CancellableToolExecutor",
    "CompositeToolCatalog",
    "CompositeToolExecutor",
    "DecoratedToolProvider",
    "EphemeralToolPlugin",
    "ExcludingToolCatalog",
    "FilteredToolCatalog",
    "InvocationGrantToolCatalog",
    "IdempotencyStrategy",
    "InMemoryToolCatalog",
    "InMemoryToolExecutor",
    "ReconcileResult",
    "ReconcileState",
    "ResumeStrategy",
    "RoutedToolExecutor",
    "SideEffectLevel",
    "ToolCall",
    "ToolCancellationResult",
    "ToolCancellationState",
    "ToolCatalog",
    "ToolDefinition",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolInvocation",
    "decorated_tool_definition",
    "tool",
    "McpServerConfig",
    "McpToolPlugin",
    "localize_tool_definition",
    "normalize_tool_language",
    "DEFAULT_ALWAYS_VISIBLE_TOOLS",
    "DirectToolSelectionPolicy",
    "LLMToolSelectionPolicy",
    "LexicalToolSelectionPolicy",
    "RecentToolSelectionPolicy",
    "ToolSelectionConfig",
    "ToolSelectionPolicy",
    "ToolSelectionPrepareContext",
    "ToolSelectionRequest",
    "ToolSelectionResult",
]


def __getattr__(name: str):
    return resolve_export(name, _LAZY_EXPORTS, globals())


def __dir__() -> list[str]:
    return exported_names(_LAZY_EXPORTS, globals())
