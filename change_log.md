
2026-02-09 22:50:00
1. Feature: `SessionContext.load_recent_skill_to_context` now supports detecting `<skill>skill_name</skill>` tags in user messages, prioritizing the most recent occurrence (tag or tool call).

2026-02-09 23:10:00
1. Fix: Updated `_install_requirements` in `sandbox.py` to use Tsinghua PyPI mirror and trusted host for reliable package installation in sandbox environments.

2026-02-09 23:40:00
1. Fix: Refactored session_id handling in ToolManager to enforce parameter safety. Added explicit checks to remove session_id from kwargs before standard and MCP tool execution, preventing duplicate argument errors.

2026-02-10 10:51:00
1. Fix: Implemented `register_tools_from_object` in `ToolProxy`. Now delegates registration to `ToolManager` and automatically adds newly registered tools (like `load_skill`) to the proxy's available tools whitelist, ensuring dynamic tool registration works in restricted modes.

2026-02-10 10:56:00
1. Fix: Updated `SessionContext`, `AgentBase`, and `SimpleAgent` to verify `skill_manager.list_skills()` before enabling skill-related features. This ensures that an empty `SkillManager` is treated equivalent to `None`, preventing `load_skill` registration and skill prompts when no skills are available.

2026-02-10 11:00:00
1. Fix: Updated `ToolProxy.get_tool` to return `None` instead of raising `ValueError` when a tool is not available. This prevents crashes in `SessionContext` initialization when checking for tools (like `load_skill`) that haven't been registered yet.
