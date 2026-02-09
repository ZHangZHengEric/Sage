
2026-02-09 22:50:00
1. Feature: `SessionContext.load_recent_skill_to_context` now supports detecting `<skill>skill_name</skill>` tags in user messages, prioritizing the most recent occurrence (tag or tool call).

2026-02-09 23:10:00
1. Fix: Updated `_install_requirements` in `sandbox.py` to use Tsinghua PyPI mirror and trusted host for reliable package installation in sandbox environments.

2026-02-09 23:40:00
1. Fix: Refactored session_id handling in ToolManager to enforce parameter safety. Added explicit checks to remove session_id from kwargs before standard and MCP tool execution, preventing duplicate argument errors.
