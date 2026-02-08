from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tool_manager import ToolManager
    from .tool_proxy import ToolProxy
    from .tool_schema import AgentToolSpec

def __getattr__(name):
    if name == "ToolManager":
        from .tool_manager import ToolManager
        return ToolManager
    elif name == "ToolProxy":
        from .tool_proxy import ToolProxy
        return ToolProxy
    elif name == "AgentToolSpec":
        from .tool_schema import AgentToolSpec
        return AgentToolSpec
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    'ToolManager',
    'ToolProxy',
    'AgentToolSpec',
]
