# Change Log

- **2026-06-18 16:58** 格式化 `sagents/utils/llm_request_utils.py`（ruff 0.15.14 单行签名），修复 CI Ruff format 检查。

- **2026-06-18 15:46** 修复发消息报 400「role 'tool' 缺前序 tool_calls」：新增 `drop_orphan_tool_messages` 并在发往 LLM 前清理孤儿 tool 消息，兜住压缩覆盖/offload/多调用 assistant 被丢弃导致的 tool 失配。

- **2026-06-18 15:40** 工作台修复补强：会话切换/新建时重置自动弹出抑制，并为面板 Transition 加 mode=out-in，消除离场过渡期间的 node.parentNode 报错。
- **2026-06-18 15:25** 修复桌面端工作台关闭后被流式新增项反复自动打开的问题。
- **2026-06-18 11:27** 更新 `sagents/README.md`，补充新版记忆/上下文压缩策略说明。
- **2026-06-16 13:43** 重写 `sagents/README.md`，补充核心编排层学习指南。
