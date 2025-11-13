"""
Router module that exports all routers for the agent platform server.
"""

from .mcp import mcp_router
from .tool import tool_router
from .agent import agent_router
from .converation import conversation_router
from .stream import stream_router
from .file_server import file_server_router
from .kdb import kdb_router

# Export all routers for easy import
__all__ = [
    "mcp_router",
    "tool_router", 
    "agent_router",
    "conversation_router",
    "stream_router",
    "file_server_router",
    "kdb_router"
]