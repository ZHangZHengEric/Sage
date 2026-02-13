# Change Log

## 2026-02-11
- Designed and added a new SVG logo (`sage_logo.svg`) for the web frontend, featuring a stylized circuit 'S' design.
- Updated `app/web/index.html` to use the new logo as the favicon.
- Updated `sagents/prompts/task_decompose_prompts.py`: Added skill suggestion requirement (item 10) in zh/en/pt versions and fixed formatting issues.
- Updated `sagents/agent/agent_base.py`: Implemented structured XML formatting for `<available_skills>` and added `<skill_usage>` tag.
- Updated `sagents/skill/skill_proxy.py`: Added `list_skill_info` method to support detailed skill listing.
- Removed `tests/agent/test_skill_formatting.py` as skill formatting testing was cancelled by user.
- Added unit tests for ToolManager isolation and ToolProxy priority logic (`tests/test_tool_isolation.py`).
- Added unit tests for FibreSubAgent integration and FibreTools parameter renaming (`tests/agent/test_fibre_integration.py`).
- Fixed import errors in `sagents/tool/__init__.py` and `sagents/tool/tool_proxy.py` discovered during testing.
- Refined ToolManager singleton logic: Restored `isolated` parameter and added `is_auto_discover` control for non-singleton instances.
- Enhanced ToolProxy: 
    - `register_tools_from_object` now registers tools into the existing highest-priority ToolManager (index 0) instead of creating a new one.
    - Clarified tool priority logic: ToolManagers at the beginning of the list (index 0) have the highest priority.
- Updated FibreSubAgent: Uses `ToolManager(isolated=True)` for local tool isolation.
- Renamed `role_description` to `description` in FibreTools and removed `role` from FibreOrchestrator.
- Removed `LocalToolManager` class in favor of `ToolManager(isolated=True)`.

## 2026-02-13
- 新增 `brave_search` MCP 服务 (`mcp_servers/search/brave_search_server.py`)，支持双模式搜索（反爬虫抓取 + API 降级）及网页内容提取 (`visit_page`)。添加了单元测试及 `markdownify`/`beautifulsoup4` 依赖。
