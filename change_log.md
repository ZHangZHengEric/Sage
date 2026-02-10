
2026-02-10 19:10:00
1. 接口新增：新增 API `/api/agent/template/default_system_prompt`，用于前端在创建空白 Agent 时获取默认的 System Prompt 草稿。
2. 逻辑关联：该接口直接复用 `PromptManager` 中的 `agent_intro_template`（支持多语言），确保前端显示的草稿与后端默认行为完全一致。

2026-02-10 22:30:00
1. 交互优化：修改 AgentList.vue，在创建空白 Agent 时自动调用 API 获取默认 System Prompt 并预填到编辑器中。
2. 策略调整：强制要求创建空白 Agent 时的默认 Prompt 始终使用中文版本，忽略当前界面语言设置，确保 Agent 人设的一致性。
