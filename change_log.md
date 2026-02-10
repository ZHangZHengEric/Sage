
2026-02-10 18:15:00
1. 提示词优化：更新 `agent_base_prompts.py` 中的 `skills_usage_hint`，明确 Skill 与 Tool 的区别。
2. 概念澄清：强调 Skill 是“任务指南与手册”及配套工具箱，不能直接调用，需通过 `load_skill` 加载。
