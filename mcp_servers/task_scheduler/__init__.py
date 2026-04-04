# Task Scheduler MCP Server
# Runtime behavior is implemented in task_scheduler_server and persists tasks
# through the backend /tasks APIs rather than a local sqlite wrapper.

from .task_scheduler_server import mcp

__all__ = ["mcp"]
