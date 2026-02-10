
2026-02-10 12:35:00
1. Optimization: ExecuteCommandTool now integrates `session_id` to automatically persist scripts in `agent_workspace/scripts` within the session scope.
2. Fix: Corrected JSON string parsing for list arguments (`requirement_list`, `npm_packages`) in Python/JS execution tools.

2026-02-10 14:15:00
1. 功能增强：`execute_shell_command` 新增 Shell 历史记录功能，命令日志保存在 Session Workspace 的 `.shell_history` 文件中。
2. 文档更新：完善 `execute_shell_command`, `execute_python_code`, `execute_javascript_code` 的 `session_id` 参数多语言描述，明确其为自动注入。
3. 测试验证：新增测试脚本验证了 Session 路径解析、脚本持久化及 Shell 历史记录功能的正确性。
