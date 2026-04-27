"""Tool implementation package with lazy exports.

Importing this package should not eagerly import every tool implementation,
because some tools pull in optional third-party dependencies that are not
needed for most callers. Use attribute access to load only the requested tool.
"""

from importlib import import_module

# 协议性内部工具：不下发到 SAgent.run_stream（即不进入 SSE/前端）。
# 这些工具是 agent 控制信号（如 turn_status 报告本轮状态），非用户可见结果。
# 用作 sagents.sagents._redact_hidden_tools_from_chunk 的过滤白名单。
HIDDEN_FROM_STREAM_TOOL_NAMES = frozenset({"turn_status"})

__all__ = [
    "HIDDEN_FROM_STREAM_TOOL_NAMES",
    "ExecuteCommandTool",
    "FileSystemTool",
    "MemoryTool",
    "WebFetcherTool",
    "ImageUnderstandingTool",
    "ToDoTool",
    "QuestionnaireTool",
    "LintTool",
    "TurnStatusTool",
    "CodebaseTool",
]

_EXPORTS = {
    "ExecuteCommandTool": ".execute_command_tool",
    "FileSystemTool": ".file_system_tool",
    "MemoryTool": ".memory_tool",
    "WebFetcherTool": ".web_fetcher_tool",
    "ImageUnderstandingTool": ".image_understanding_tool",
    "ToDoTool": ".todo_tool",
    "QuestionnaireTool": ".questionnaire_tool",
    "LintTool": ".lint_tool",
    "TurnStatusTool": ".turn_status_tool",
    "CodebaseTool": ".codebase_tool",
}


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if not module_name:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
