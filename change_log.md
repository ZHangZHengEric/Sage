# Change Log

## 2026-02-14
- 增强 `SkillProxy` (`sagents/skill/skill_proxy.py`)：支持嵌套代理 `SkillManager`，确保 Session 级 Skill 优先级覆盖全局 Skill，并统一 `available_skills` 合并逻辑。
- 修复 Sandbox (`sagents/utils/sandbox/sandbox.py`)：更新 seatbelt profile 允许 WebAssembly 执行 (`sysctl`, `ipc-posix`, `file-map-executable`)；重定向 `npm_config_cache` 及 `HOME` 目录至沙箱内部，解决 `clawhub` 等工具在 macOS 下的权限错误。
- 优化 Sandbox (`sagents/utils/sandbox/sandbox.py`)：针对 Docker 容器环境下的 V8 WebAssembly OOM 问题，彻底移除 `RLIMIT_AS` (虚拟内存) 设置（包括 Launcher 脚本内部），保持系统默认 (Unlimited)，物理内存限制仍由 cgroup (Docker mem_limit) 负责，避免因虚拟地址空间限制导致 Node.js/V8 初始化失败。
- 调试增强 (`sagents/sagents.py`)：在 `run_stream` 入口处增加 `skill_manager` 详细日志，打印当前可用技能列表、SkillProxy 层级结构及过滤模式，便于排查 System Prompt 技能泄露问题。
- 修复 Skill 过滤失效 (`sagents/skill/skill_manager.py`, `sagents/context/session_context.py`)：`SkillManager` 新增 `include_global_skills` 参数；`SessionContext` 在初始化 Session 级 Manager 时显式禁用全局技能加载，解决因自动包含默认工作区导致的技能过滤逃逸问题。