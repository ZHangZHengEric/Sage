
2026-02-10 12:35:00
1. Optimization: ExecuteCommandTool now integrates `session_id` to automatically persist scripts in `agent_workspace/scripts` within the session scope.
2. Fix: Corrected JSON string parsing for list arguments (`requirement_list`, `npm_packages`) in Python/JS execution tools.

2026-02-10 14:15:00
1. 功能增强：`execute_shell_command` 新增 Shell 历史记录功能，命令日志保存在 Session Workspace 的 `.shell_history` 文件中。
2. 文档更新：完善 `execute_shell_command`, `execute_python_code`, `execute_javascript_code` 的 `session_id` 参数多语言描述，明确其为自动注入。
3. 测试验证：新增测试脚本验证了 Session 路径解析、脚本持久化及 Shell 历史记录功能的正确性。

2026-02-10 14:35:00
1. 功能增强：SimpleAgent 和 TaskExecutorAgent 现在支持自动提取并保存响应中的 Markdown 代码块到 `agent_workspace/artifacts` 目录。
2. 命名规则：Markdown 文件使用首行作为文件名（如果存在），其他代码块使用时间戳自动命名。
3. 架构优化：新增 `sagents/utils/content_saver.py` 工具模块，统一处理内容提取和保存逻辑，并将生成物归档至 `artifacts` 子目录。
