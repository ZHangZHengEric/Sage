2. 重构 `TaskPlanningAgent` 与 `ExecuteCommandTool`：提取并增强列表解析逻辑为 `sagents.utils.common_utils.ensure_list` 通用函数。
   - `TaskPlanningAgent`：使用新函数替换原 `_try_parse_list`，增强 XML 解析的健壮性。
   - `ExecuteCommandTool`：`execute_javascript_code` 的 `npm_packages` 参数现支持与 Python 依赖相同的宽松解析（List/JSON/字符串），解决了参数类型报错问题。
