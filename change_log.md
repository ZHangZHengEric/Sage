
2026-02-09 22:45:00
1. Refactor: `SkillTool.load_skill` now accepts `session_id` to use session-specific `SkillManager` instead of global one, fixing isolation issues.
2. Feature: `SessionContext` now restricts fibre-specific tools (`sys_spawn_agent`, etc.) in non-fibre modes using `ToolProxy`.
3. Feature: `ToolManager` automatically injects `session_id` into tool functions if requested in signature.
