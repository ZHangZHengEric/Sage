
2026-02-10 18:45:00
1. 逻辑重构：统一了 `agent_base.py` 中 System Message Role Definition 的生成逻辑。无论内容来源是 `system_prefix_override`、`SYSTEM_PREFIX_FIXED`、`self.system_prefix` 还是默认模板，现在都会统一：
   - 合并 `custom_instructions`（如果有）。
   - 被包裹在 `<role_definition>` 标签中。
   这修复了之前非默认分支可能丢失 XML 标记和自定义指令的漏洞。
