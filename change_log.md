
2026-02-10 11:25:00
1. Feature: Added Node.js support to Sandbox. Introduced `execute_javascript_code` tool, updated `sandbox.py` to handle `node` environment, and configured `npm` to use `npmmirror.com` for fast dependency installation. Implemented intelligent caching to skip redundant `npm install`.

2026-02-10 11:45:00
1. Fix: Resolved `AttributeError` in `TaskExecutorAgent._prepare_tools` where `suggested_tools` could be a string. Added type check to ensure it's a list before appending `load_skill`. Also aligned `skill_manager` check to verify `list_skills()`.
