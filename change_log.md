# Change Log

## 2026-02-14
- 增强 `SkillProxy` (`sagents/skill/skill_proxy.py`)：支持嵌套代理 `SkillManager`，确保 Session 级 Skill 优先级覆盖全局 Skill，并统一 `available_skills` 合并逻辑。
- 修复 Sandbox (`sagents/utils/sandbox/sandbox.py`)：更新 seatbelt profile 允许 WebAssembly 执行 (`sysctl`, `ipc-posix`, `file-map-executable`)；重定向 `npm_config_cache` 及 `HOME` 目录至沙箱内部，解决 `clawhub` 等工具在 macOS 下的权限错误。
- 优化 Sandbox (`sagents/utils/sandbox/sandbox.py`)：针对 Docker 容器环境下的 V8 WebAssembly OOM 问题，彻底移除 `RLIMIT_AS` (虚拟内存) 设置（包括 Launcher 脚本内部），保持系统默认 (Unlimited)，物理内存限制仍由 cgroup (Docker mem_limit) 负责，避免因虚拟地址空间限制导致 Node.js/V8 初始化失败。
- 调试增强 (`sagents/sagents.py`)：在 `run_stream` 入口处增加 `skill_manager` 详细日志，打印当前可用技能列表、SkillProxy 层级结构及过滤模式，便于排查 System Prompt 技能泄露问题。
- 修复 Skill 过滤失效 (`sagents/skill/skill_manager.py`, `sagents/context/session_context.py`)：`SkillManager` 新增 `include_global_skills` 参数；`SessionContext` 在初始化 Session 级 Manager 时显式禁用全局技能加载，解决因自动包含默认工作区导致的技能过滤逃逸问题。
2026-02-15 21:00:00 Refactored ToDoTool and ToolManager: removed ToDoTool._update_system_context and replaced it with a static parse_todo_list method. ToolManager now directly reads the todo file from the file system to sync session_context after sandbox execution, ensuring reliable state updates in isolated environments.
2026-02-15 21:30:00 Fixed AttributeError in TaskObservationAgent by replacing non-existent tool_manager.get_tool_config with get_openai_tools. Verified AgentBase._execute_tool compatibility with ToolProxy via get_tool.
2026-02-15 22:00:00 Optimized ToDoTool: updated todo_write to support partial updates. Existing tasks only require id and changed fields, while new tasks require content.
2026-02-15 22:30:00 Updated sage_cli.py: Removed deprecated --no-multi-agent argument. Added --deepthink argument to explicitly enable deep thinking mode, alongside existing configuration options.
2026-02-15 23:00:00 Enhanced SimpleAgent: Enabled ToDoTool for SimpleAgent in simple mode. Updated SimpleAgent prompts to instruct mandatory usage of todo_write for task creation and status updates. Ensured ToDoTool registration in SAgent's simple workflow.
2026-02-16 10:00:00 Frontend Update: Added YAML export support for Agent configuration. Users can now choose between JSON and YAML formats in the export dialog. Implemented using `js-yaml`.
2026-02-18 10:30:00 修复无AgentID时请求填充逻辑，避免访问空Agent配置。
2026-02-18 11:00:00 无AgentID时用request构建配置，保证后续逻辑使用请求信息。
2026-02-18 11:30:00 调整为先覆盖request再全部基于request判断，新增可用知识库与子Agent字段。
