4. 修复 `agent_base.py` 中引用缺失的 `skills_info_label` 问题：在 `sagents/prompts/agent_base_prompts.py` 中补充了该提示词，并明确指引智能体使用 `load_skill` 加载可用技能。
