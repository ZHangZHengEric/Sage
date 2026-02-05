
2026-02-05 15:00:00 - 修复了 FibreTools 实例化错误，通过强制注册绑定方法解决依赖注入问题。同时将 sys_spawn_agent 的 system_instruction 参数重命名为 system_prompt，并优化了相关提示词，使其更关注能力定义而非具体任务。
2026-02-05 17:30:00 - 修复FibreAgent在CLI模式下子agent消息污染主session历史的问题，现在fibre_cli.py会根据session_id过滤消息块。同时为fibre_cli.py添加了--no_terminal_log参数，支持在终端运行时屏蔽日志输出。
2026-02-05 17:45:00 - 修复 fibre_cli.py 中缺少 logging 模块导入导致的 NameError 错误。
2026-02-05 18:10:00 - 优化CLI多智能体输出显示，现在消息框会显示具体的 Agent 名称（如 FibreAgent 或子 Agent 名称），解决所有 Agent 都显示为 SimpleAgent 的问题。同时修复了 SimpleAgent 和 AgentBase 中 MessageChunk 生成时未携带 agent_name 的问题。
2026-02-05 18:15:00 - 修复了 simple_agent.py 中因为添加 agent_name 导致的缩进错误。
2026-02-05 18:30:00 - 重构 fibre_cli.py 的输出逻辑，使用 rich.live.Live 替换原有的顺序打印模式，实现了多 Agent 并发输出时的“Dashboard”视图，避免了内容交替打印导致的显示混乱。
2026-02-05 18:40:00 - 优化 fibre_cli.py 的 Live 视图体验，关闭自动刷新改为手动刷新以恢复流式打字感，并限制 Live 区域显示的行数（最近20行），避免消息过长导致终端刷屏和滚动问题。
2026-02-05 18:45:00 - 优化 simple_agent.py 的工具建议逻辑，禁止顶级 FibreAgent 使用 sys_finish_task 工具，避免误结束整个对话。
