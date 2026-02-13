"""
Router module that exports all routers for the agent platform server.
"""

from .agent import agent_router
from .chat import chat_router
from .conversation import conversation_router
from .kdb import kdb_router
from .mcp import mcp_router
from .oss import oss_router
from .skill import skill_router
from .system import system_router
from .tool import tool_router
from .trace import trace_router
from .user import user_router
from .llm_provider import router as llm_provider_router

# Export all routers for easy import
__all__ = [
    "register_routes",
]


def register_routes(app):
    app.include_router(mcp_router)
    app.include_router(agent_router)
    app.include_router(conversation_router)
    app.include_router(tool_router)
    app.include_router(kdb_router)
    app.include_router(user_router)
    app.include_router(system_router)
    app.include_router(oss_router)
    app.include_router(chat_router)
    app.include_router(trace_router)
    app.include_router(skill_router)
    app.include_router(llm_provider_router)
