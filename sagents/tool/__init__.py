from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tool_manager import ToolManager
    from .tool_proxy import ToolProxy

def __getattr__(name):
    if name == "ToolManager":
        from .tool_manager import ToolManager
        return ToolManager
    elif name == "ToolProxy":
        from .tool_proxy import ToolProxy
        return ToolProxy
    elif name == "get_tool_manager":
        from .tool_manager import get_tool_manager
        return get_tool_manager
    elif name == "emit_tool_progress":
        from .tool_progress import emit_tool_progress
        return emit_tool_progress
    elif name == "emit_tool_progress_closed":
        from .tool_progress import emit_tool_progress_closed
        return emit_tool_progress_closed
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'ToolManager',
    'ToolProxy',
    'get_tool_manager',
    'emit_tool_progress',
    'emit_tool_progress_closed',
]
